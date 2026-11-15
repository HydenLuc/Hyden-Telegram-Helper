# 历史消息下载设计

> **状态**：✅ 已实现

## 1. 目标与背景

### 1.1 现状缺口

`handle_media`（`tg/handlers.py:139`）只处理**实时消息**（`bot_start_time` 之后到达）。如果用户：
- 监听一个新频道，频道之前的历史媒体永远拿不到
- bot 在某段时间没运行，期间频道发的消息错过
- 想从 chat 历史里精挑某些媒体

→ 都需要"主动拉历史"能力。

### 1.2 4 个场景

| 场景 | 触发 | 行为 |
|------|------|------|
| **A** 全频道历史 | 输入频道 ID/名 → 「开始扫描」| 扫整个频道，**流式边扫边下** |
| **B** 指定范围 | ID 范围 OR 日期范围（互斥）| 扫指定范围，**流式边扫边下** |
| **C** 遗漏补下 | 输入频道，「开始扫描」| **先扫完返回 scan_results**，用户勾选后再下载 |
| **D** 单条消息 | chat_id + message_id → 「下载」| 直接调现有 `/api/download`，**不进 job 系统** |

A/B/C 走 history-pull job 系统；D 完全独立（与 job schema 无关，scene 枚举不含 D）。

---

## 2. 数据结构

### 2.1 `history_jobs.json`

```json
{
  "<job_id_uuid>": {
    "job_id":         "<uuid>",
    "scene":          "A" | "B" | "C",

    "chat_id":        -1001234,
    "chat_name":      "频道名",          // 创建时通过 client.get_entity 解析填入

    "status":         "running" | "paused" | "ready_for_selection" | "done" | "error",
    "phase":          "scanning" | "downloading" | "finished",   // 仅作 UI 展示
    "error_msg":      null | "<str>",

    "last_seen_id":   0,                  // 断点：上次扫到的最大 message_id
    "next_task_seq":  0,                  // task_id 后缀计数器（跨重启连续）
    "total_scanned":  0,
    "total_queued":   0,                  // 已 spawn download 的数量
    "total_skipped":  0,                  // 含 task_id 命中 + (A/B) fuid 命中
    "total_duplicates": 0,                // 仅 fuid / task_id 命中数

    "created_at":     "ISO",
    "updated_at":     "ISO",
    "finished_at":    null | "ISO",

    // 场景 B 字段（仅 scene="B"）
    "filter_type":    null | "id" | "date",   // M4 互斥
    "min_id":         null | <int>,
    "max_id":         null | <int>,
    "min_date":       null | "ISO",
    "max_date":       null | "ISO",

    // 场景 C 字段（仅 scene="C"）
    "scan_results":   [
      {
        "message_id":         <int>,
        "filename":           "<str>",
        "size_mb":            <float>,
        "date":               "ISO",
        "duplicate":          false | true,    // M2: fuid 命中标记
        "matched_filename":   null | "<str>",  // duplicate=true 时填
        "matched_path":       null | "<str>",
        "selected":           false             // 前端勾选状态（持久化）
      }
    ]
  }
}
```

### 2.2 字段说明

- **`status`**：状态机（详见 §11.1）
- **`phase`**：UI 展示用，区分"扫描中" / "用户勾选阶段"（仅 C）/ "下载完成"
- **`last_seen_id`**：断点（M10：每条扫描成功后内存更新，每 100 条触发一次持久化；扫完/停止时强制持久化）
- **`next_task_seq`**：task_id 后缀计数器，跨重启**持久化连续**（避免重启后撞名）
- **`scan_results`**：仅 C 场景使用；M8：扫描完成 / 停止 / 启动批量写盘时持久化

### 2.3 `state.history_jobs`

`state.py` 新增：

```python
history_jobs: dict[str, dict] = {}    # job_id → record
```

加载：`bot.py` / `downloader/main.py` 启动时 `state.history_jobs = storage.load_history_jobs()`，把 `status=running` 的 job 自动改 `paused`（崩溃恢复语义）。

---

## 3. 媒体过滤

### 3.1 `is_downloadable_media(message)`

新建 `downloader/history/utils.py`：

```python
from telethon.tl.types import (
    MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage,
    DocumentAttributeSticker, DocumentAttributeAnimated, DocumentAttributeAudio,
)

def is_downloadable_media(message) -> bool:
    """是否值得下载（排除 sticker / gif / voice / 链接卡片 / 纯文字）。"""
    if not message.media:
        return False
    if isinstance(message.media, MessageMediaWebPage):
        return False
    if isinstance(message.media, MessageMediaPhoto):
        return True
    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        if doc is None:
            return False
        attrs = {type(a) for a in (doc.attributes or [])}
        if DocumentAttributeSticker in attrs:
            return False
        if DocumentAttributeAnimated in attrs:    # GIF
            return False
        for a in (doc.attributes or []):
            if isinstance(a, DocumentAttributeAudio) and getattr(a, "voice", False):
                return False
        return True
    return False
```

### 3.2 服务端过滤辅助

`iter_messages(chat, filter=InputMessagesFilterPhotoVideo, ...)` 服务端粗过滤照片+视频，省带宽。但 sticker / gif 通过 `InputMessagesFilterDocument` 也会回来——所以**仍需要客户端 `is_downloadable_media` 二次过滤**。

实现选择：v1 不传 `filter` 参数（保守：拿全部，客户端过滤）；如果用户反馈带宽问题，后续可加按场景选择 filter。

---

## 4. 查重逻辑（场景区分）

### 4.1 公共预建索引

每个 job 启动时一次性预建（避免 O(N²) 扫描）：

```python
completed_set = {
    (r["chat_id"], r["message_id"])
    for r in state.completed_downloads
    if r.get("status") == "done"
}
active_pending_set = {
    (r["chat_id"], r["message_id"])
    for r in (
        list(state.active_downloads.values())
        + list(state.pending_tasks.values())
    )
}
# fuid 索引就是 state.content_index["fuid"]，O(1) 查询
```

### 4.2 场景 A / B（流式边扫边下）

每条扫到的消息：

```python
async for msg in iter_messages(...):
    if not is_downloadable_media(msg):
        continue
    job["total_scanned"] += 1

    # 1) task_id 三池查重（活跃/待恢复/已完成）
    key = (chat_id, msg.id)
    if key in completed_set or key in active_pending_set:
        job["total_skipped"] += 1
        continue

    # 2) fuid 预查（M2 决定 A/B 场景静默跳过 + 计数）
    fuid_key = _extract_fuid(msg)
    if fuid_key and fuid_key in state.content_index["fuid"]:
        job["total_duplicates"] += 1
        job["total_skipped"] += 1
        continue

    # 3) 排队下载（M6 流式：每条 await semaphore）
    await _history_semaphore.acquire()      # 限制 3 并发
    asyncio.create_task(_run_one_history_download(job, msg))
    job["total_queued"] += 1
```

A/B 场景 **不**填 scan_results，fuid/task_id 命中直接静默 + 计数。用户在 job 视图能看到 `total_duplicates / total_skipped / total_queued` 累积统计。

### 4.3 场景 C（先扫完再勾选）

```python
async for msg in iter_messages(...):
    if not is_downloadable_media(msg):
        continue
    job["total_scanned"] += 1

    key = (chat_id, msg.id)
    # task_id 命中（已下过）→ 静默跳过
    if key in completed_set or key in active_pending_set:
        job["total_skipped"] += 1
        continue

    # fuid 命中 → 入 scan_results，标记 duplicate=true（M2）
    fuid_key = _extract_fuid(msg)
    duplicate = False
    matched_filename = matched_path = None
    if fuid_key and fuid_key in state.content_index["fuid"]:
        md5_hex = state.content_index["fuid"][fuid_key]
        existing = state.content_index["md5"].get(md5_hex)
        if existing:
            duplicate = True
            matched_filename = existing.get("filename")
            matched_path = existing.get("path")

    job["scan_results"].append({
        "message_id":       msg.id,
        "filename":         media_filename(msg),
        "size_mb":          round(_size_of(msg) / 1048576, 1),
        "date":             msg.date.isoformat(),
        "duplicate":        duplicate,
        "matched_filename": matched_filename,
        "matched_path":     matched_path,
        "selected":         False,
    })
```

C 场景**不直接 spawn 下载**；扫描完成后 `status="ready_for_selection"`，等用户勾选。

---

## 5. 并发控制（多层 semaphore）

```python
# downloader/history/manager.py 模块级
_scan_semaphore     = asyncio.Semaphore(2)   # M9: 同时运行 scan job 上限
_history_semaphore  = asyncio.Semaphore(3)   # M6: 同时运行的历史下载任务上限
```

- `_scan_semaphore`：每个 job 在主循环开头 `async with _scan_semaphore`，避免多 job 同时打 Telegram API
- `_history_semaphore`：A/B 场景每条消息 spawn 前 `await _history_semaphore.acquire()`，下载完成后 release（在 `_run_one_history_download` finally 块里）

**关键细节**：`_history_semaphore` 与现有的 `state._conn_gate`（`MAX_TOTAL_CONNECTIONS=20`）是**独立**两层。`_history_semaphore` 限制"同时排队的 history 任务数"，避免 `active_downloads` 字典膨胀；`_conn_gate` 是物理 Telegram 连接预算，由 `download_one` 内部 `_acquire_connections` 负责。两层都有意义。

---

## 6. task_id 与 source 字段

### 6.1 `task_id` 命名（n4）

```python
task_id = f"{chat_id}_{msg_id}_hist_{job_short}_{seq}"
```
- `job_short` = `job_id[:8]`
- `seq` = `job["next_task_seq"]`，每次 spawn 后 `+= 1` 并立即触发持久化（保证跨重启唯一）

### 6.2 `source` 字段（M7）

`download_one` 入口（`download/manager.py:286`）签名扩展：

```python
async def download_one(task_id, message, file_path, label,
                       chat_id=0, message_id=0, resume=False,
                       source: str = "realtime"):   # 新增，默认实时
```

写入 `active_downloads[task_id]["source"] = source`；`_finish` 自动透传到 `completed_downloads`。

调用方传值：
- `handle_media` → `source="realtime"`
- `_start_api_download` (web/api.py:400) → `source="realtime"`（手动调 /api/download 视为 realtime）
- `_start_api_download(skip_md5_index=True)`（toast 直接下载、F6 重新下载）→ `source="realtime"`
- **`_run_one_history_download`（新增）→ `source="history"`**

`pending_tasks` 持久化（`download/manager.py:336-345`）也加 `source` 字段；`_recover_one` 恢复时从 pending_tasks 读回，否则崩溃恢复后字段会丢。

**前端 v1 不区分显示**（M7）；source 仅持久化，方便未来 filter。

---

## 7. 各场景流程

### 7.1 场景 A：全频道历史

```python
async def _run_scene_a(job):
    chat = await client.get_entity(job["chat_id"])
    completed_set, active_pending_set = _build_dedup_sets()

    async with _scan_semaphore:
        kwargs = {"reverse": True}    # 旧→新，方便 last_seen_id 单调递增
        if job["last_seen_id"] > 0:
            kwargs["min_id"] = job["last_seen_id"]   # 断点续

        try:
            async for msg in client.iter_messages(chat, **kwargs):
                if job["status"] != "running":   # 用户点了停止
                    break
                if not is_downloadable_media(msg):
                    continue
                job["total_scanned"] += 1
                _maybe_persist(job)               # 每 100 条触发持久化

                key = (job["chat_id"], msg.id)
                if key in completed_set or key in active_pending_set:
                    job["total_skipped"] += 1
                    job["last_seen_id"] = max(job["last_seen_id"], msg.id)
                    continue

                fuid_key = _extract_fuid(msg)
                if fuid_key and fuid_key in state.content_index["fuid"]:
                    job["total_duplicates"] += 1
                    job["total_skipped"] += 1
                    job["last_seen_id"] = max(job["last_seen_id"], msg.id)
                    continue

                await _history_semaphore.acquire()
                asyncio.create_task(_run_one_history_download(job, msg))
                job["total_queued"] += 1
                job["last_seen_id"] = max(job["last_seen_id"], msg.id)
        except (FloodWaitError, FloodPremiumWaitError) as e:
            # iter_messages 抛出 → 暂停 job 等待重试
            job["status"] = "paused"
            job["error_msg"] = f"FloodWait {e.seconds}s"
            await _persist(job)
            return
        except Exception as e:
            job["status"] = "error"
            job["error_msg"] = f"{type(e).__name__}: {e}"
            await _persist(job)
            return

    if job["status"] == "running":
        job["status"] = "done"
        job["phase"] = "finished"
        job["finished_at"] = datetime.now().isoformat()
    await _persist(job)
```

### 7.2 场景 B：指定范围

只在 `kwargs` 构造上区别于 A：

```python
if job["filter_type"] == "id":
    kwargs["min_id"] = max(job["min_id"], job["last_seen_id"]) if job["min_id"] else job["last_seen_id"]
    if job["max_id"]:
        kwargs["max_id"] = job["max_id"]
elif job["filter_type"] == "date":
    # offset_date 是"早于此日期"的过滤，与 reverse=True 配合
    if job["max_date"]:
        kwargs["offset_date"] = datetime.fromisoformat(job["max_date"])
    # min_date 没有原生支持，扫描时客户端过滤
```

`min_date` 用客户端过滤：`if msg.date.isoformat() < job["min_date"]: continue`（必要时也可 `break` 提前结束）。

`filter_type` 互斥（M4）—— UI radio 二选一，后端 schema 强制其一为 null。

### 7.3 场景 C：遗漏补下

扫描阶段（与 A 相同结构，但分支不同）：

```python
async def _run_scene_c(job):
    chat = await client.get_entity(job["chat_id"])
    completed_set, active_pending_set = _build_dedup_sets()
    job["phase"] = "scanning"

    async with _scan_semaphore:
        kwargs = {"reverse": True}
        if job["last_seen_id"] > 0:
            kwargs["min_id"] = job["last_seen_id"]

        async for msg in client.iter_messages(chat, **kwargs):
            if job["status"] != "running":
                break
            if not is_downloadable_media(msg):
                continue
            job["total_scanned"] += 1
            _maybe_persist(job)

            key = (job["chat_id"], msg.id)
            if key in completed_set or key in active_pending_set:
                job["total_skipped"] += 1
                job["last_seen_id"] = max(job["last_seen_id"], msg.id)
                continue

            # M2: fuid 命中入 scan_results 标记 duplicate=true
            fuid_key = _extract_fuid(msg)
            duplicate = False
            matched_filename = matched_path = None
            if fuid_key and fuid_key in state.content_index["fuid"]:
                md5_hex = state.content_index["fuid"][fuid_key]
                existing = state.content_index["md5"].get(md5_hex)
                if existing:
                    duplicate = True
                    matched_filename = existing.get("filename")
                    matched_path = existing.get("path")

            job["scan_results"].append({
                "message_id":       msg.id,
                "filename":         media_filename(msg),
                "size_mb":          round((_size_of(msg) or 0) / 1048576, 1),
                "date":             msg.date.isoformat(),
                "duplicate":        duplicate,
                "matched_filename": matched_filename,
                "matched_path":     matched_path,
                "selected":         False,
            })
            job["last_seen_id"] = max(job["last_seen_id"], msg.id)

    if job["status"] == "running":
        job["status"] = "ready_for_selection"
        job["phase"] = "scanning"   # phase 维持表示扫描已完成等用户操作
    await _persist(job)
```

用户勾选后调 `POST /api/history-pull/{job_id}/download-selected`：

```python
async def download_selected(job_id, message_ids):
    job = state.history_jobs[job_id]
    job["phase"] = "downloading"
    selected_msgs = [r for r in job["scan_results"] if r["message_id"] in message_ids]
    chat = await client.get_entity(job["chat_id"])

    for r in selected_msgs:
        msg = await client.get_messages(chat, ids=r["message_id"])
        if msg is None or not msg.media:
            continue
        await _history_semaphore.acquire()
        asyncio.create_task(_run_one_history_download(job, msg))

    # 简化：勾选启动后立即 done，下载状态各自走 active_downloads/completed
    job["status"] = "done"
    job["phase"] = "finished"
    job["finished_at"] = datetime.now().isoformat()
    await _persist(job)
```

`scan_results` 保留（M10），用户可在 job 视图反复挑选。如果想再扫一遍，**新建 job** 或点"重新扫描（reset last_seen_id）"。

### 7.4 `_run_one_history_download(job, msg)`

复用 `_start_api_download`，但用 history 专属 task_id 和 source：

```python
async def _run_one_history_download(job, msg):
    try:
        seq = job["next_task_seq"]
        job["next_task_seq"] += 1
        await _persist(job)   # 立即持久化 seq（防撞名）

        # 复用 web/api.py:_start_api_download 但扩展 task_id_tag / task_id_seq / source
        await _start_api_download(
            msg, job["chat_id"], msg.id,
            task_id_tag=f"hist_{job['job_id'][:8]}",
            task_id_seq=seq,
            source="history",
        )
    finally:
        _history_semaphore.release()
```

`_start_api_download` 需要扩展（由本 spec 引入新参数）：

```python
async def _start_api_download(msg, chat_id, message_id, *,
                              skip_md5_index: bool = False,
                              task_id_tag: str = "api",     # 新增
                              task_id_seq: int | None = None,  # 新增
                              source: str = "realtime",     # 新增
                              ) -> dict:
    ...
    if task_id_seq is not None:
        task_id = f"{chat_id}_{message_id}_{task_id_tag}_{task_id_seq}"
    else:
        suffix = "_dup" if skip_md5_index else "_api"
        task_id = f"{chat_id}_{message_id}{suffix}{int(time.time())}"
    ...
    asyncio.create_task(download_one(..., source=source))
```

### 7.5 场景 D：单条消息

UI 收到 chat_id + message_id → 直接 `POST /api/download`（已有）。**不进 job 系统**，spec scene 枚举不含 D。

---

## 8. 持久化策略

### 8.1 写盘时机（汇总）

| 字段 | 写盘时机 |
|------|---------|
| `next_task_seq` | spawn download 前**立即**写盘（防撞名） |
| `last_seen_id` | 每 100 条扫描触发一次（与 chunk 边界对齐）+ 扫完/停止/error 时强制 |
| `total_scanned / total_queued / total_skipped` | 同上（与 last_seen_id 共写） |
| `scan_results`（C 场景）| 扫完 / 停止 / 启动批量下载时一次性写（M8）|
| `status / phase / finished_at / error_msg` | 状态变化时立即写 |

`_maybe_persist(job)` helper：

```python
async def _maybe_persist(job):
    if job["total_scanned"] % 100 == 0:
        await _persist(job)

async def _persist(job):
    job["updated_at"] = datetime.now().isoformat()
    storage.save_history_jobs(state.history_jobs)
```

### 8.2 启动恢复

`load_history_jobs()` 加载后，扫描所有 `status="running"` 的 job → 自动改 `paused`，写一句 log。这与 mover、md5 任务的崩溃恢复语义一致。

```python
def load_history_jobs() -> dict:
    if not HISTORY_JOBS_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_JOBS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        # 崩溃恢复：running → paused
        for j in data.values():
            if isinstance(j, dict) and j.get("status") == "running":
                j["status"] = "paused"
                j["error_msg"] = "进程中断，已自动暂停"
        return data
    except Exception as e:
        _log.error(f"加载 history_jobs.json 失败: {e}")
        return {}
```

**这个改动会让 storage 加载阶段有副作用**（修改 status），需要在 `load_history_jobs()` 后立即 `save_history_jobs()` 持久化校正状态。

---

## 9. UI 结构

### 9.1 「手动下载」折叠 section

位置：downloader 页面顶部，搜索聊天框（`#search-input`）下方。

```html
<section>
  <h2 id="manual-toggle" style="cursor:pointer;user-select:none">
    手动下载 <span id="manual-arrow">▶</span>
  </h2>
  <div id="manual-panel">

    <!-- 场景 D：下载指定消息（独立单条） -->
    <div class="manual-block">
      <div style="font-size:.85rem;color:#bbb;margin-bottom:6px">📎 下载指定消息（单条）</div>
      <input id="md-cid" placeholder="频道 ID" style="...">
      <input id="md-mid" placeholder="消息 ID" style="...">
      <button class="btn btn-sm" id="md-go">下载</button>
    </div>

    <!-- 场景 A：全频道历史 -->
    <div class="manual-block">
      <div>📚 下载频道全部历史</div>
      <input id="ha-chat" placeholder="频道 ID 或名称" style="...">
      <button class="btn btn-sm" id="ha-go">开始扫描</button>
    </div>

    <!-- 场景 B：指定范围 -->
    <div class="manual-block">
      <div>🎯 下载指定范围</div>
      <input id="hb-chat" placeholder="频道 ID 或名称">
      <div>
        <label><input type="radio" name="hb-mode" value="id" checked> 按 ID 范围</label>
        <label><input type="radio" name="hb-mode" value="date"> 按日期范围</label>
      </div>
      <div id="hb-id-block">
        <input id="hb-min-id" type="number" placeholder="起始 ID（可选）">
        <input id="hb-max-id" type="number" placeholder="结束 ID（可选）">
      </div>
      <div id="hb-date-block" style="display:none">
        <input id="hb-min-date" type="datetime-local">
        <input id="hb-max-date" type="datetime-local">
      </div>
      <button class="btn btn-sm" id="hb-go">开始扫描</button>
    </div>

    <!-- 当前 jobs（A/B）的进度展示 -->
    <div id="hist-jobs-list" style="margin-top:12px"></div>
  </div>
</section>
```

### 9.2 「遗漏补下」折叠 section

位置：「手动下载」section 下方。

```html
<section>
  <h2 id="missing-toggle" style="cursor:pointer">遗漏补下 <span id="missing-arrow">▶</span></h2>
  <div id="missing-panel">
    <input id="hc-chat" placeholder="频道 ID 或名称">
    <select id="hc-watched-list">
      <option value="">— 从已监听频道选择 —</option>
      <!-- 动态填充 watched 频道 -->
    </select>
    <button class="btn btn-sm" id="hc-go">开始扫描</button>

    <!-- 当前 C jobs 列表（每个 job 一个 block） -->
    <div id="hc-jobs-list"></div>
  </div>
</section>
```

### 9.3 Job 进度展示（A/B/C 通用）

```html
<div class="hist-job-card" data-job-id="...">
  <div class="hist-job-head">
    <span class="hist-job-title">📚 频道名 · 场景 A</span>
    <span class="hist-job-status status-running">scanning</span>
    <button class="btn btn-sm hist-stop-btn">停止</button>
    <button class="btn btn-sm hist-delete-btn" style="color:#ef9a9a">删除</button>
  </div>
  <div class="hist-job-stats">
    已扫描 <b>1234</b> 条 · 排队下载 <b>87</b> · 跳过 <b>42</b>（其中重复 18）
  </div>
  <!-- C 场景独有：扫描完成后展示 scan_results 表格 -->
  <div class="hist-scan-results" data-show-when="ready_for_selection">
    <div class="ctrl-row">
      <label><input type="checkbox" class="hc-select-all"> 全选</label>
      <label><input type="checkbox" class="hc-hide-dup"> 隐藏重复（已下载过）</label>
      <button class="btn btn-sm hc-download-selected">下载选中</button>
      <button class="btn btn-sm hc-rescan">重新扫描</button>
    </div>
    <table>
      <thead><tr><th></th><th>文件名</th><th>大小</th><th>时间</th><th>类型</th></tr></thead>
      <tbody>
        <!-- 每行：勾选 + 文件名 + 大小 + 日期 + 标签（"重复"标橙） -->
      </tbody>
    </table>
  </div>
</div>
```

`scan_results` 表格行渲染：
- `duplicate=true` → 行底色 `#3a2a10`，"重复"标签 + matched_filename hover tooltip
- 默认全部勾选；用户可手动取消

### 9.4 频道选择体验

「遗漏补下」section 提供已监听频道下拉（`#hc-watched-list`），点击自动填入 ID。手动输入的 ID 也支持。

---

## 10. 后端 API

### 10.1 路由清单

```
POST   /api/history-pull/start
GET    /api/history-pull/jobs
POST   /api/history-pull/{job_id}/stop
POST   /api/history-pull/{job_id}/rescan         # 重置 last_seen_id + scan_results 清空
POST   /api/history-pull/{job_id}/download-selected   # 仅 C 场景
DELETE /api/history-pull/{job_id}
```

### 10.2 请求 / 响应

**`POST /api/history-pull/start`**

```json
{
  "scene":       "A" | "B" | "C",
  "chat":        "频道 ID 或名称（字符串）",
  "filter_type": null | "id" | "date",   // 仅 B；A/C 必须 null
  "min_id":      null | <int>,           // B/id
  "max_id":      null | <int>,           // B/id
  "min_date":    null | "ISO",           // B/date
  "max_date":    null | "ISO",           // B/date
  "resume":      true | false            // false=新 job；true=找现有同频道+同 scene 的 paused job 续
}
```

响应：
```json
{ "ok": true, "job_id": "<uuid>", "chat_id": -1001234, "chat_name": "..." }
```

错误：
- 400 invalid scene / chat 缺失 / B 场景 filter_type 互斥违反
- 404 chat 解析失败（`get_entity` 抛异常 → n2 决策）
- 409 同 chat + 同 scene 已有 running job（n3 允许，但 resume=false 时给提示，需带 `force=true` 才创建新 job）

**`POST /api/history-pull/{job_id}/stop`**：将 status → paused（当前批次扫描完后停止）。

**`POST /api/history-pull/{job_id}/rescan`**：
- 仅 status ∈ (paused, done, error, ready_for_selection) 才允许
- `last_seen_id = 0`、`scan_results = []`、`total_scanned = total_queued = ... = 0`
- status → running，重新启动协程

**`POST /api/history-pull/{job_id}/download-selected`**（仅 C）：
```json
{ "message_ids": [1234, 1235, ...] }
```
未勾选的留在 scan_results。响应：`{ok: true, queued: N}`。

**`DELETE /api/history-pull/{job_id}`**：
- status=running → 先内部 stop（设 paused，等当前 chunk 完成）→ 再 delete
- 否则直接 delete
- **不影响**已经 spawn 的下载任务（它们继续走 active_downloads）

**`GET /api/history-pull/jobs`**：
```json
{ "ok": true, "jobs": [ ...全量 history_jobs 列表，按 created_at 倒序... ] }
```

调试用；前端主要从 WS 拿数据。

### 10.3 路由顺序

`server.py` 注册（避免参数与静态段冲突）：

```python
app.router.add_post(  "/api/history-pull/start",                          _api_hp_start)
app.router.add_get(   "/api/history-pull/jobs",                           _api_hp_list)
app.router.add_post(  "/api/history-pull/{job_id}/stop",                  _api_hp_stop)
app.router.add_post(  "/api/history-pull/{job_id}/rescan",                _api_hp_rescan)
app.router.add_post(  "/api/history-pull/{job_id}/download-selected",     _api_hp_download_selected)
app.router.add_delete("/api/history-pull/{job_id}",                       _api_hp_delete)
```

---

## 11. 状态管理

### 11.1 状态机

```
                     [start]
                        ↓
                    running
                  /    |    \
            [stop]  [end]  [error]
              ↓       ↓       ↓
            paused  ?       error
                      ↓
              scene=A/B → done
              scene=C   → ready_for_selection
                              ↓
                        [download-selected]
                              ↓
                            done
```

`phase` 字段独立，仅供 UI 区分阶段（scanning / downloading / finished）。

### 11.2 `monitoring_paused` 不影响（M5）

历史下载 job、`/api/download`、retry 都**不**读 `state.monitoring_paused`。仅 `handle_media`（自动监听入口）受其影响。spec 在文档化 `monitoring_paused` 语义的位置（如 pause-design.md）应同步更新这一点（v2 规划，本 spec 不强制）。

### 11.3 WS payload（n1）

`web/websocket.py:_build_state` 增加：

```python
"history_jobs": list(state.history_jobs.values()),     # 全量推（每个 job 几 KB，<=10 个 job 总 <=100 KB）
```

或仅推摘要（如 100 个 scan_results 不全推）以避免 WS payload 暴大：

```python
"history_jobs": [
    {**{k: v for k, v in j.items() if k != "scan_results"},
     "scan_results_count": len(j.get("scan_results", []))}
    for j in state.history_jobs.values()
],
```

前端打开"勾选界面"时单独 GET `/api/history-pull/jobs?include=scan_results&job_id=xxx`。本 spec 推荐**摘要模式**避免 WS 暴大。

---

## 12. 边界 case

| 场景 | 行为 |
|------|------|
| 用户输入不存在的频道 | `client.get_entity` 抛 `ValueError`/`UsernameNotOccupiedError` → 400 返回 |
| 同频道多 job（n3）| 允许；各自独立 `last_seen_id`；提示用户避免重复 API 配额浪费 |
| 历史 job 跑到一半 bot 崩溃 | 重启时 status=running → paused；`last_seen_id` 最多丢 100 条范围；用户可点恢复继续 |
| iter_messages 中途 FloodWaitError | 捕获后 status → paused，error_msg 记录 wait 秒数；用户手动重启 |
| C 场景扫到 5000 条全是重复 | scan_results 全部 duplicate=true；前端默认勾选可取消，用户也可"全选 + 排除重复"批量启动 |
| 用户 stop 一个 C job，未勾选下载 | scan_results 保留；status=paused；点"继续扫描"从 last_seen_id 续 |
| 用户 rescan 一个 C job | last_seen_id=0、scan_results=[]、计数器清零；从头扫 |
| 全局暂停（M5）+ 启动历史 job | 允许（不受 monitoring_paused 影响） |
| 历史下载触发的下载完成后 | 走正常 `_finish` → 进 completed_downloads（带 source=history）→ MD5 索引（如非压缩包） |
| C 场景用户勾选下载，途中 bot 崩溃 | 已 spawn 的下载有 pending_tasks 持久化（P1-5b），下次启动自动恢复；scan_results 不变 |
| 删除 running job | 先 paused 再 delete；已 spawn 的下载不受影响 |
| 频道关闭 / 用户被踢 | iter_messages 抛异常 → status=error |

---

## 13. 不在本次范围

- Telegram 命令端触发（如 `拉历史 <id>`）
- 历史下载进度在 dashboard 展示
- 历史 job 与实时下载的优先级调度（共用 `_conn_gate`，先到先得）
- 历史 job 的自动清理（done/error 超过 N 天自动删）
- 多文件 group 关联（历史下载每条独立 save_dir，不复用 `_group_dirs`）
- A/B 场景下"扫描结果回顾"（A/B 不维护 scan_results，仅累积统计）
- C 场景下载完成后的 job → done 自动转换（实现：扫描完即标 done；下载状态由 active/completed 各自跟踪）
- 跨 chat 批量历史下载（v1 一次一频道）

---

## 14. 测试矩阵

### 14.1 后端 - 场景 A

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 启动 A job 扫小频道（~50 条） | 流式扫完，所有未下载消息进 active_downloads，job done |
| 2 | A 扫到一半 stop | status=paused，last_seen_id 记录到当前位置 |
| 3 | 续 paused job | 从 last_seen_id 之后继续，不重扫 |
| 4 | rescan paused job | last_seen_id=0，从头扫 |
| 5 | 同时跑 2 个 A job（不同频道）| 两个都 running，scan_semaphore 自然串行；无 FloodWait |
| 6 | 同时跑 3 个 A job | 第 3 个等 scan_semaphore，先在 status=running 阻塞在 `async with`，无并发扫描 |

### 14.2 后端 - 场景 B

| # | 步骤 | 期望 |
|---|------|------|
| 1 | filter_type=id，min_id=100, max_id=200 | 仅扫 (100, 200] 范围 |
| 2 | filter_type=date，min_date=昨天 | offset_date 配合 min_date 客户端过滤 |
| 3 | filter_type=id 同时填 min_date | 400 拒绝（互斥违反） |

### 14.3 后端 - 场景 C

| # | 步骤 | 期望 |
|---|------|------|
| 1 | C 扫完小频道 | status=ready_for_selection，scan_results 含未下载条目 |
| 2 | 中含 fuid 命中 | scan_results 标记 duplicate=true，matched_filename 填充 |
| 3 | 用户勾 5 条 download-selected | 5 条进 active_downloads，job→done，scan_results 保留 |
| 4 | 同 job 再次 download-selected 不同 5 条 | 失败（job 已 done）；用户需 rescan 才能重新扫 |
| 5 | scan_results 1000 条 | 持久化文件 ~150 KB，加载/保存 < 50 ms |

### 14.4 持久化与崩溃恢复

| # | 场景 | 期望 |
|---|------|------|
| 1 | 扫到 350 条 kill -9 | 重启后 status=paused，last_seen_id ≈ 300（最后 100 条边界）|
| 2 | 重启时 history_jobs.json 损坏 | 加载失败，回退空 dict，不阻塞启动 |
| 3 | next_task_seq 跨重启 | 新 spawn 的 task_id 不与重启前撞名 |
| 4 | running job 崩溃 → paused | 启动加载即转换并立即持久化 |

### 14.5 与现有功能交互

| # | 场景 | 期望 |
|---|------|------|
| 1 | 历史下载完成 → MD5 索引 | content_index 累积新条目（与实时下载同流程） |
| 2 | 历史下载触发 mover | archive 文件正常 mover；非 archive 留在 DOWNLOAD_DIR |
| 3 | active_downloads 同时含实时 + 历史 | 前端"下载中"区域统一显示；下次再加 source filter |
| 4 | 历史下载触发 fuid 命中（场景 C 用户勾选了 duplicate=true 条）| download_one 走完，_finish 异步 MD5，命中 → finish toast 弹出 |
| 5 | 历史下载完成数 + duplicate_queue | 不会进 duplicate_queue（A/B 静默；C 已用 scan_results 处理） |
| 6 | monitoring_paused=true，启动历史 job | 允许启动，job 正常运行 |
| 7 | exempt 频道触发实时下载 + 历史 job | 各自独立，互不影响 |

---

## 15. 决策记录

| # | 项 | 决策 |
|---|----|------|
| M1 | scene D 是否进 job | 不进，scene 枚举只 A/B/C |
| M2 | fuid 命中 | A/B 静默跳过+计数；C 入 scan_results 标 duplicate=true |
| M3 | C 遗漏时间下界 | 删除 bot_start_time 限制，仅靠 completed_set + active_pending_set |
| M4 | B 场景 ID/日期范围 | UI radio 互斥（filter_type 字段），后端校验 |
| M5 | monitoring_paused 影响 | 不影响历史下载、/api/download、retry |
| M6 | 扫描/下载流式 | 流式：每条消息 await `_history_semaphore.acquire()` |
| M7 | source 字段 | 持久化但 v1 前端不区分显示 |
| M8 | scan_results 写盘 | 仅扫完/停止/启动批量时写盘 |
| M9 | 同时运行 job 数 | `_scan_semaphore = asyncio.Semaphore(2)` |
| M10 | last_seen_id 与 scan_results | 每 100 条触发一次持久化；scan_results 保留可反复挑选 |
| n1 | history_jobs 进 WS | 必须，但用摘要模式（不送完整 scan_results） |
| n2 | 频道解析 | 创建 job 前 `client.get_entity` 校验 |
| n3 | 同频道多 job | 允许，各自独立 last_seen_id |
| n4 | task_id 后缀 | `{chat_id}_{msg_id}_hist_{job[:8]}_{seq}` |

### 写文档时新决策（自决，不再阻塞）

| # | 项 | 决策 |
|---|----|------|
| s1 | A/B 场景 fuid 命中是否记录 | 不进 scan_results，仅累积 `total_duplicates` 计数（A/B 用户已决定下载范围，无需逐条审视）|
| s2 | next_task_seq 跨重启 | 持久化（每次 spawn 前立即写盘），保证 task_id 唯一 |
| s3 | last_seen_id 写盘频率 | 每 100 条触发一次（与 chunk 边界对齐），不等扫完 |
| s4 | C 用户勾选下载后 job 状态 | 勾选启动后立即 status=done，下载完成情况由 active/completed 各自跟踪（不在 job 视图里跟踪每条下载终态） |
| s5 | 增加 `ready_for_selection` 状态 | C 场景扫描完成 → ready_for_selection（不直接 done），等用户操作 |
| s6 | scan job 启动失败的状态 | error + error_msg（如 chat 解析失败、FloodWait 不可恢复），用户可 rescan |
| s7 | iter_messages 全部用 reverse=True | 旧→新，方便 last_seen_id 单调递增；min_id 用作断点 |
| s8 | DELETE 一个 running job 的语义 | 内部先 stop（status→paused 等批次结束）→ 再删除字典条目；已 spawn 的下载不受影响 |
| s9 | 同 chat + 同 scene 已有 paused job 时再次启动 | 默认 409，请求带 `resume=true` 时复用旧 job、`force=true` 时新建 |
| s10 | scan_results 在 WS 摘要模式下的展现 | 推送只带 `scan_results_count`；前端打开 job 详情时单独 GET `/api/history-pull/jobs?job_id=xxx&include=scan_results` 拿全量 |
