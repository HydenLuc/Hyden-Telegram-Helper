# 重复下载确认设计

> **状态**：✅ 已实现

## 目标

监听触发同一条消息再次抵达时（`task_id = {chat_id}_{message_id}` 相同），不再静默跳过；改为加入「待确认重复下载」队列，等用户在 Web UI 主动选择「重新下载」或「忽略」。

## 现状

`downloader/tg/handlers.py:163-167`：

```python
existing_files = state.grouped_state.get(gs_key, {}).get("files", {})
if task_id in existing_files and existing_files[task_id].get("status") == "done":
    _log.info(f"[skip] {task_id} 已下载完成，跳过")
    return
```

命中即静默 return。用户感知不到、无法主动重下、也不会在 UI 看到该事件。

## 整体设计

### 关键决策

1. **REPLACE** 现有 skip：去掉 `_log.info` + `return`，改为构造 duplicate_queue 项 push 之、然后 return
2. **检查范围扩到三处**：`completed_downloads`、`active_downloads`、`pending_tasks` —— 任意一处含同 `chat_id+message_id` 即视为重复
3. **duplicate_queue 自身按 `task_id` 去重**：同 task_id 已在队列里 → 第二次触发不重复 push
4. 重新下载用 `/api/download` 同款逻辑，task_id 改用 `_dup{ts}` 后缀

### 数据结构

```python
# downloader/state.py 新增
duplicate_queue: list[dict] = []
```

每条记录字段：

```python
{
    "task_id":            "{chat_id}_{message_id}",  # 队列内唯一键
    "chat_id":            int,
    "message_id":         int,
    "filename":           str,                # 文件名（取消息推断或为空）
    "size_mb":            float,              # 文件大小，未知为 0.0
    "source_label":       str,                # 来源频道名（entity_display_name）
    "last_downloaded_at": str | None,         # 取自 completed_downloads.finished_at
    "previous_status":    str,                # done / downloading / waiting / queued (in pending)
    "queued_at":          str,                # 加入队列的 ISO 时间
    "grouped_id":         int | None,
}
```

### 持久化

新增 `duplicate_queue.json`，结构：`{"queue": [...]}`。

- 加载：`bot.py main()` 中 `state.pending_tasks = ...` 之后
- 写入：`storage.save_duplicate_queue(state.duplicate_queue)`，**走 `common/atomic_io.py` 原子写**
- 启动时不做内容验证；条目陈旧也不主动清理（用户自己点忽略）

`config.py` 新增：

```python
DUPLICATE_QUEUE_FILE = Path("duplicate_queue.json")
```

`.gitignore` 加 `duplicate_queue.json`。

### `downloader/storage.py` 新增

```python
def load_duplicate_queue() -> list[dict]:
    if not config.DUPLICATE_QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(config.DUPLICATE_QUEUE_FILE.read_text("utf-8"))
        return data.get("queue", [])
    except Exception:
        return []

def save_duplicate_queue(queue: list[dict]) -> None:
    atomic_write_json(config.DUPLICATE_QUEUE_FILE, {"queue": queue})
```

## handle_media 改造

### 改造点：`downloader/tg/handlers.py`

替换原 dedup 块（约 153-167 行）：

```python
task_id = f"{event.chat_id}_{message.id}"
gs_key = (
    f"{event.chat_id}_{message.grouped_id}"
    if message.grouped_id else task_id
)

# REPLACE 原 skip：检测重复 → 加入 duplicate_queue
if _is_duplicate(event.chat_id, message.id):
    _enqueue_duplicate(event, message, task_id)
    return
```

`_enqueue_duplicate` 与 `_is_duplicate` 加在 handlers.py 同一文件（不抽到 utils；handlers 已是入口模块）。

### `_is_duplicate(chat_id, message_id)`

**按字段扫描，不按 dict key**。这样能覆盖手动 `/api/download` 触发的任务（task_id 带 `_api{ts}` 后缀，与 watch 的 plain `{chat_id}_{message_id}` 不同），完整实现 6.3 的"覆盖三个池子"语义。

```python
def _is_duplicate(chat_id: int, message_id: int) -> bool:
    # active_downloads 与 pending_tasks 记录均含 chat_id / message_id 字段
    # （见 download/manager.py:309-310, 319-320）
    for rec in state.active_downloads.values():
        if rec.get("chat_id") == chat_id and rec.get("message_id") == message_id:
            return True
    for rec in state.pending_tasks.values():
        if rec.get("chat_id") == chat_id and rec.get("message_id") == message_id:
            return True
    for rec in state.completed_downloads:
        if (rec.get("chat_id") == chat_id
            and rec.get("message_id") == message_id
            and rec.get("status") == "done"):
            return True
    return False
```

性能：active 与 pending 量级最多几百，completed 上限 5000。每条 watch 触发扫一次，O(n) 可接受；如未来 completed 上调到 5 万级再考虑加索引。

注：
- `completed_downloads` 中也有 error / timeout 记录，**只 done 算重复**。失败的允许 watch 自动重试。
- 历史 `completed_downloads` 记录可能缺 `chat_id` / `message_id` 字段（`P1-5b` 之前的旧条目）。`.get(...) == X` 在缺字段时返回 None != X，自然不命中，**向后兼容**。

### `_enqueue_duplicate(event, message, task_id)`

```python
def _enqueue_duplicate(event, message, task_id: str) -> None:
    # 队列内按 task_id 去重
    if any(d.get("task_id") == task_id for d in state.duplicate_queue):
        _log.info(f"[duplicate] {task_id} 已在待确认队列，忽略此次触发")
        return

    # 推断 filename 与 size
    try:
        filename = media_filename(message)
    except Exception:
        filename = ""
    size = 0
    if isinstance(message.media, MessageMediaDocument):
        size = message.media.document.size or 0
    size_mb = round(size / 1048576, 1)

    # 推断 source_label
    cid_str = str(event.chat_id)
    source_label = ""
    rec = state.watched.get(cid_str)
    if isinstance(rec, dict):
        source_label = rec.get("name") or ""

    # 推断 previous_status + last_downloaded_at
    previous_status = "unknown"
    last_at = None
    if task_id in state.active_downloads:
        previous_status = state.active_downloads[task_id].get("status", "downloading")
    elif task_id in state.pending_tasks:
        previous_status = "queued"
    else:
        for r in state.completed_downloads:
            if r.get("task_id") == task_id and r.get("status") == "done":
                previous_status = "done"
                last_at = r.get("finished_at")
                # finished_at 是 epoch float，前端再格式化
                break

    state.duplicate_queue.append({
        "task_id":            task_id,
        "chat_id":            event.chat_id,
        "message_id":         message.id,
        "filename":           filename,
        "size_mb":            size_mb,
        "source_label":       source_label,
        "last_downloaded_at": last_at,
        "previous_status":    previous_status,
        "queued_at":          datetime.now().isoformat(),
        "grouped_id":         message.grouped_id,
    })
    storage.save_duplicate_queue(state.duplicate_queue)
    _log.info(f"[duplicate] {task_id} 已加入待确认队列（{previous_status}）")
```

### grouped_state 与 watch task_count 不变

重复触发**不**进 `grouped_state`、**不**计入 `watched_rec.task_count`（与现有 skip 行为一致：duplicate 不算"真实新触发"）。原代码中 grouped_state 维护与 task_count 自增都在 dedup 之后，REPLACE 后这部分代码原位不动，只是不会走到（_enqueue_duplicate 之后 return）。

## API 设计

### `GET /api/duplicate-queue`

```json
{
  "ok": true,
  "queue": [ ...每条 record... ],
  "count": 5
}
```

### `DELETE /api/duplicate-queue/{task_id}`

忽略单条：

```python
async def _api_dq_delete(request):
    tid = request.match_info["task_id"]
    before = len(state.duplicate_queue)
    state.duplicate_queue = [d for d in state.duplicate_queue if d.get("task_id") != tid]
    if len(state.duplicate_queue) == before:
        return web.json_response({"ok": False, "error": "not in queue"}, 404)
    storage.save_duplicate_queue(state.duplicate_queue)
    await _broadcast()
    return web.json_response({"ok": True})
```

### `DELETE /api/duplicate-queue`

清空全部：

```python
async def _api_dq_clear(_request):
    n = len(state.duplicate_queue)
    state.duplicate_queue = []
    storage.save_duplicate_queue(state.duplicate_queue)
    await _broadcast()
    return web.json_response({"ok": True, "removed": n})
```

### `POST /api/duplicate-queue/{task_id}/download`

触发重新下载（移除队列后，复用 `_api_download` 的核心逻辑）：

```python
async def _api_dq_download(request):
    from downloader.download.manager import download_one
    tid = request.match_info["task_id"]
    entry = next((d for d in state.duplicate_queue if d.get("task_id") == tid), None)
    if not entry:
        return web.json_response({"ok": False, "error": "not in queue"}, 404)

    chat_id = int(entry["chat_id"])
    message_id = int(entry["message_id"])

    try:
        msg = await client.get_messages(chat_id, ids=message_id)
    except Exception as e:
        return web.json_response(
            {"ok": False, "error": f"获取消息失败: {e}"}, 500
        )
    if msg is None or not msg.media or isinstance(msg.media, MessageMediaWebPage):
        return web.json_response(
            {"ok": False, "error": "消息不存在或无媒体内容"}, 404
        )

    # 准备 save_dir（与 _api_download 一致）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        entity = await client.get_entity(chat_id)
        source_name = sanitize(entity_display_name(entity), f"chat_{chat_id}")
    except Exception:
        source_name = f"chat_{chat_id}"
    raw_text = (msg.message or "").strip()
    suffix = sanitize(raw_text[:10], "未命名文件夹") if raw_text else "未命名文件夹"
    save_dir = unique_dir(config.DOWNLOAD_DIR / source_name / f"{ts}_{suffix}")
    save_dir.mkdir(parents=True, exist_ok=True)
    if msg.message:
        (save_dir / "文字信息.txt").write_text(msg.message, encoding="utf-8")
    file_path = unique_file(save_dir / media_filename(msg))
    detail_path = save_dir / "消息详情.txt"
    header = _format_details_header(msg)
    entry_md = _format_media_entry(msg, 1, file_path.name)
    detail_path.write_text(header + "\n" + entry_md + "\n", encoding="utf-8")

    # task_id 用 _dup{ts} 后缀（区别于 watch 触发与 _api_download 触发）
    new_task_id = f"{chat_id}_{message_id}_dup{int(time.time())}"
    label = f"{source_name}/{save_dir.name}"

    t = asyncio.create_task(download_one(new_task_id, msg, file_path, label,
                                         chat_id=chat_id, message_id=message_id))
    state.task_outer_tasks[new_task_id] = t
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)

    # 移出队列
    state.duplicate_queue = [d for d in state.duplicate_queue if d.get("task_id") != tid]
    storage.save_duplicate_queue(state.duplicate_queue)

    await _broadcast()
    return web.json_response({
        "ok": True,
        "new_task_id": new_task_id,
        "filename": file_path.name,
        "save_dir": str(save_dir),
    })
```

注：保留旧记录 / 旧文件不删——这是用户的预期（防止误操作时还能找回）。新下载会生成新的独立文件夹（`unique_dir` 自动加 `_0000` 后缀）。

### 路由注册（`web/server.py`）

```python
app.router.add_get(   "/api/duplicate-queue",                    _api_dq_list)
app.router.add_delete("/api/duplicate-queue",                    _api_dq_clear)
app.router.add_delete("/api/duplicate-queue/{task_id}",          _api_dq_delete)
app.router.add_post(  "/api/duplicate-queue/{task_id}/download", _api_dq_download)
```

### WebSocket payload 增加字段

`websocket.py:_build_state` 加：

```python
"duplicate_queue": state.duplicate_queue,
"duplicate_count": len(state.duplicate_queue),
```

`/api/status` 同步加 `duplicate_count`（不送完整 queue，节流；前端单独 GET `/api/duplicate-queue` 拿详情）。

## 前端 UI

### 「下载中」标题旁新增按钮

```html
<button id="dup-toggle" class="btn btn-sm">重复文件 (<span id="dup-count">0</span>)</button>
```

- `count == 0` 时按钮置灰但**始终显示**（spec 决策）
- 点击切换面板展开/收起
- 状态由 localStorage 持久化（与 `setupToggle` 一致）

### 面板

```html
<div id="dup-panel" style="display:none">
  <div class="dup-header">
    <span>排序：</span>
    <select id="dup-sort">
      <option value="time">时间</option>
      <option value="size">大小</option>
    </select>
    <button id="dup-clear" class="btn btn-sm">清空列表</button>
  </div>
  <table id="dup-table">
    <thead>
      <tr><th>文件名</th><th>大小</th><th>来源</th><th>上次完成</th><th>状态</th><th>操作</th></tr>
    </thead>
    <tbody id="dup-tbody"></tbody>
  </table>
</div>
```

每行渲染：

```js
function renderDupRow(d) {
  return `<tr data-task-id="${esc(d.task_id)}">
    <td>${esc(d.filename || '(未知)')}</td>
    <td>${d.size_mb > 0 ? d.size_mb + 'MB' : '-'}</td>
    <td>${esc(d.source_label)}</td>
    <td>${d.last_downloaded_at ? formatTs(d.last_downloaded_at) : '-'}</td>
    <td>${esc(d.previous_status)}</td>
    <td>
      <button class="dup-redownload" data-task-id="${esc(d.task_id)}">重新下载</button>
      <button class="dup-ignore"     data-task-id="${esc(d.task_id)}">忽略</button>
    </td>
  </tr>`;
}
```

### 操作

- **重新下载**：`confirm("确认重新下载 {filename}？")` → POST `/api/duplicate-queue/{task_id}/download` → 成功 toast + WS 自动刷新（duplicate_count 减一、active_downloads 加一）
- **忽略**：DELETE `/api/duplicate-queue/{task_id}` → WS 刷新
- **清空列表**：`confirm("清空所有 N 条待确认重复？")` → DELETE `/api/duplicate-queue`

### 排序（前端）

```js
function sortDup(queue, mode) {
  const arr = queue.slice();
  if (mode === 'size') arr.sort((a,b) => b.size_mb - a.size_mb);
  else arr.sort((a,b) => (b.queued_at || '').localeCompare(a.queued_at || ''));
  return arr;
}
```

默认按 queued_at 倒序（最新排首）。

### 数据流

- WS 推送的 `duplicate_queue` 直接填面板（不需要单独 GET）
- 面板首次展开时不需要拉数据（WS 已有）
- 操作返回后 `_broadcast()` 触发 WS 推送，前端无需手动 refetch

## 边界 case

| 场景 | 行为 |
|------|------|
| 用户手动 `/api/download` 在下，watch 触发同消息 | `_is_duplicate` 按 (chat_id, message_id) 字段扫 active_downloads 命中 → 进 duplicate_queue（不会并行重复下载） |
| Telethon 断线重连推送同消息 N 次 | 第 1 次进队列；第 2~N 次因 task_id 已在队列被 `_enqueue_duplicate` 跳过（队列内去重） |
| 用户清空 completed_downloads | 之前的 done 记录消失 → 下次同消息触发 `_is_duplicate` 不命中 → 走正常下载流程，符合"我已重置历史"的语义 |
| 重新下载时消息已被原频道删除 | `client.get_messages` 返回 None → API 404 + 队列条目仍保留（用户可点忽略） |
| 重新下载产生新 task_id `_dup{ts}` 完成后 | 新记录进 `completed_downloads`；下次同 message 再来 `_is_duplicate` 仍命中 done（新旧记录都视为重复）→ 再次进队列 |
| 持久化文件损坏 | `load_duplicate_queue` try/except 返回 `[]`，不阻塞启动 |

## 验收

- 监听一个频道，下载某文件成功 → 频道里转发同一条消息 → 该消息**不下载**，进入「重复文件」面板
- 面板按钮显示 `重复文件 (1)`
- 点忽略 → 面板清空
- 再次转发 → 重新进队列
- 点「重新下载」→ 弹确认 → 启动新下载（生成新的 `unique_dir` 文件夹）
- bot 重启 → `duplicate_queue.json` 加载，面板内容保留
- handle_media 中无任何静默 skip 路径（log grep `[skip]` 返回空）
