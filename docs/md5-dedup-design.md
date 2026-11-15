# MD5 内容去重设计

> **状态**：✅ 已实现

## 1. 目标与背景

### 现有去重机制

| 层级 | 实现 | 触发位置 | 行为 |
|------|------|----------|------|
| 频道层 | `state.watched` | `cmd_watch` | 同 chat_id 已监听则拒绝 |
| 消息层 | F6 `_is_duplicate` 按 (chat_id, message_id) 扫三池 | `handle_media` | 同消息 → silent enqueue 到 `duplicate_queue` |

**缺口**：相同**内容**但来自**不同消息**（转发、跨频道、重新上传）无法识别。

### 本次新增

两层基于内容的查重：

1. **fuid 快速查（下载前）**：用 Telegram `document.id` / `photo.id` 作为 file unique id，**不需要下载**就可识别"同一份原始文件被引用"
2. **MD5 精确查（下载后）**：异步计算 MD5，识别"内容字节级相同但 file_id 不同"（譬如别人下载后重新上传）

### 用户体验

- 命中 → **toast** 提示 10 秒，让用户主动选择处理
- 用户离线/没看见 → 后端按场景默认行为兜底（fuid_pending 默认入队、finish 默认保留）

### 不替代 F6

F6 的 task_id silent enqueue 保留不变。三套机制并存：

```
handle_media:
    ├─ F6 _is_duplicate 命中（同消息）→ silent enqueue
    ├─ fuid 命中（同 file_id 不同消息）→ toast
    └─ 否则正常下载 → _finish 异步算 MD5 → 命中 → toast
```

---

## 2. 索引结构

### 2.1 文件位置

⚠️ **2026-08-19 起存在 `state.db`**（SQLite）的两张表：`content_md5`（md5_hex → 记录）
和 `content_fuid`（fuid_key → md5_hex），见 `downloader/kvstore.py`。
**内存结构没变**，仍是 `{"md5": {...}, "fuid": {...}}`；变的只是落盘方式——
从「整份重写 `content_index.json`」变成「新增一条写一行」。

旧的 `content_index.json` **保留不删**（回滚路径 + SQLite 出问题时的兜底），
但迁移后不再更新。本文下面提到 `content_index.json` 的地方读作「content_index 这份数据」。

**不持久化** PII / 文件内容，仅元数据 + 路径。两者都在 `.gitignore` 里。

### 2.2 完整 schema

```json
{
  "md5": {
    "<md5_hex>": {
      "task_id":          "-1001234_5678",
      "filename":         "video.mp4",
      "path":             "/home/me/Desktop/Telegram/频道名/20260428_xxx/video.mp4",
      "size":             104857600,
      "source_label":     "频道名",
      "finished_at":      "2026-04-28T12:34:56.789012"
    }
  },
  "fuid": {
    "d_5912345678901234567": "<md5_hex>",
    "p_4823456789012345678": "<md5_hex>"
  }
}
```

### 2.3 字段说明

**`md5` 表**（key 为 32 字符 hex）：
- `task_id` — 首次写入此索引时的 task_id（用于追溯，但 task_id 可能被回收，不可作引用）
- `filename` — 文件名（不含路径）
- `path` — 完整下载路径。**注意**：mover 搬走后此字段陈旧（详见 §10.Q5）；不主动维护
- `size` — 字节数
- `source_label` — 来源频道名（取自 `state.watched[cid_str]["name"]`）
- `finished_at` — 首次完成时间（ISO 字符串）

**`fuid` 表**（key 用前缀区分类型）：
- `d_<document.id>` — document 媒体（mp4 / pdf / zip 等）
- `p_<photo.id>` — photo 媒体
- 其他媒体类型不入 fuid 索引（无稳定 id 可用）
- value 永远是 md5_hex 字符串，必须在 `md5` 表中存在

### 2.4 一致性约束

- 写入：`md5[hex]` 与至少一个 `fuid[key]` **同时**写入并立即原子持久化
- 读取：先查 `fuid` → 拿 `md5_hex` → 再查 `md5` 表得详细信息（两步查找）
- 启动：原子加载到 `state.content_index`；解析失败 → 回退空索引（不阻塞启动）
- 持久化：写时机延后到 §4.3 流程结束；与 mover_state.json 一致的"立即原子写"策略

---

## 3. 三种触发场景 × 按钮语义

按钮文案与数量**因场景而异**，前端按 `trigger_source` 分支渲染。

| `trigger_source` | 触发位置 | duplicate_type | 按钮 1 | 按钮 2 | 按钮 3 | 10s 超时默认 |
|------------------|---------|----------------|--------|--------|--------|--------------|
| `handle_media`   | watch 触发，下载未启动 | `fuid` | 「加入队列」: 入 duplicate_queue | 「跳过下载」: 丢弃，不下载 | 「直接下载」: 启动 download_one（绕过查重） | **加入队列** |
| `api_download`   | `/api/download` 调用，下载未启动 | `fuid` | 「加入队列」: 入 duplicate_queue | 「跳过下载」: 丢弃，不下载 | 「直接下载」: 启动 download_one（绕过查重） | **加入队列** |
| `finish`         | `_finish` 后异步算 MD5 命中，文件已下完 | `md5` | 「查看重复」: `/api/open` 打开 matched_path 所在文件夹 | 「跳过」: 删除当前下载的文件 + 删 completed 记录（mover 已搬走则跳过删文件） | 「保留」: no-op，两个文件都保留 | **保留**（即 no-op，仅移出 pending_toasts） |

### 3.1 几个关键语义边界

- 「直接下载」（fuid 场景）：复用 `/api/download` 的核心路径，**生成新孤立 save_dir**（`unique_dir`），task_id 用 `_dup{ts}` 后缀；**不复用 `_group_dirs` 缓存**（避免 5min TTL 跨期问题）
- 「跳过」（finish 场景）：
  - 先尝试 `os.unlink(downloaded_path)` —— 失败则视为 mover 已搬走，静默
  - 再从 `state.completed_downloads` 移除 task_id 对应记录，原子持久化
  - **不**联动 mover；mover 已经在搬运的话照常完成
- 「保留」=「跳过下载」=超时默认（按场景）—— 无论哪种实现都保证：移出 `pending_toasts`，**不触动文件**
- 「查看重复」：固定指向 `Path(matched_path).parent` 而非 file 本身（打开文件管理器到所在目录）

---

## 4. 查重流程

### 4.1 `handle_media`

在现有 dedup 顺序之后插入 fuid 检查：

```
1. paused / time / watched / media gate（保留不变）
2. F6 _is_duplicate(chat_id, message_id) 命中 → silent enqueue 到 duplicate_queue → return
3. ★ fuid_key = _extract_fuid(message)
4. ★ if fuid_key and fuid_key in state.content_index["fuid"]:
       _create_toast(trigger_source="handle_media", duplicate_type="fuid", ...)
       return
5. 现有 grouped_state 维护（保留不变）
6. 现有 _group_dirs 处理 + download_one（保留不变）
```

**fuid 命中后**：不进 grouped_state、不创建 save_dir、不增加 `watched_rec.task_count`（与 F6 silent enqueue 行为一致）。grouped_state 维护仅在真正下载启动时进行。

### 4.2 `/api/download`

在 `client.get_messages` 之后插入 fuid 检查：

```
1. 取 message（保留不变）
2. ★ fuid_key = _extract_fuid(msg)
3. ★ if fuid_key and fuid_key in state.content_index["fuid"]:
       toast_id = _create_toast(trigger_source="api_download", duplicate_type="fuid", ...)
       return 200 {ok: true, duplicate_pending: true, toast_id: toast_id}
4. 现有 unique_dir + download_one（保留不变）
```

**HTTP 响应**：返回 `{ok: true, duplicate_pending: true, toast_id: "..."}`，前端可立即弹 toast，但权威 toast 信息走 WebSocket（详见 §5）。

### 4.3 `_finish` 后异步 MD5

```python
# downloader/download/manager.py:_finish 末尾追加
if status == "done" and rec.get("path"):
    fuid_key = rec.get("fuid_key")  # 由 download_one 入口存到 active_downloads → completed
    asyncio.create_task(_compute_and_index(
        task_id=rec["task_id"],
        file_path=Path(rec["path"]),
        fuid_key=fuid_key,
        filename=rec.get("filename", ""),
        size=rec.get("total", 0),
        source_label=_resolve_source_label(rec.get("chat_id")),
        finished_at_iso=datetime.now().isoformat(),
    ))
```

`_compute_and_index` 详细逻辑：

```python
_md5_semaphore = asyncio.Semaphore(2)

async def _compute_and_index(task_id, file_path, fuid_key, filename, size, source_label, finished_at_iso):
    async with _md5_semaphore:
        loop = asyncio.get_running_loop()
        try:
            md5_hex = await loop.run_in_executor(None, _md5_sync, file_path)
        except FileNotFoundError:
            # mover 已搬走（archive 场景常见，见 Hole 2 决策）
            _log.info(f"[md5] {task_id} 文件已不存在（mover 搬走），跳过索引")
            return
        except Exception as e:
            _log.warning(f"[md5] {task_id} 计算失败：{type(e).__name__}: {e}")
            return

        # 命中已有索引 → finish toast
        existing = state.content_index["md5"].get(md5_hex)
        if existing and existing["task_id"] != task_id:
            _create_toast(
                trigger_source="finish",
                duplicate_type="md5",
                task_id=task_id,
                chat_id=...,
                message_id=...,
                filename=filename,
                size_mb=round(size / 1048576, 1),
                source_label=source_label,
                matched_filename=existing["filename"],
                matched_path=existing["path"],
                matched_finished_at=existing["finished_at"],
                downloaded_path=str(file_path),
            )
            return

        # 未命中 → 写入索引
        state.content_index["md5"][md5_hex] = {
            "task_id": task_id,
            "filename": filename,
            "path": str(file_path),
            "size": size,
            "source_label": source_label,
            "finished_at": finished_at_iso,
        }
        if fuid_key:
            state.content_index["fuid"][fuid_key] = md5_hex
        storage.save_content_index(state.content_index)


def _md5_sync(file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()
```

### 4.4 fuid 提取

```python
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

def _extract_fuid(message) -> str | None:
    media = getattr(message, "media", None)
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc:
            return f"d_{doc.id}"
    if isinstance(media, MessageMediaPhoto):
        photo = media.photo
        if photo:
            return f"p_{photo.id}"
    return None
```

`document.id` 和 `photo.id` 都是 int，前缀 `d_` / `p_` 防止巧合冲突。其他媒体（如 sticker、voice）类型不入 fuid 索引（在本次范围外）。

`download_one` 入口要把 `fuid_key` 同步存到 `active_downloads[task_id]["fuid_key"]`，这样 `_finish` 迁移到 completed 时能拿到。

---

## 5. Toast 设计

### 5.1 数据结构

`state.pending_toasts: list[dict]`，每条记录：

```python
{
    "toast_id":            "<UUID4>",                  # 主键
    "trigger_source":      "handle_media" | "api_download" | "finish",
    "duplicate_type":      "fuid" | "md5",
    "task_id":             "-1001234_5678",            # 触发时的 task_id（仅显示与日志，不作为下载键）
    "chat_id":             -1001234,
    "message_id":          5678,
    "filename":            "video.mp4",                # 当前重复文件
    "size_mb":             123.4,
    "source_label":        "频道名",
    "matched_filename":    "video_old.mp4",            # 之前已下载的同内容文件
    "matched_path":        "/abs/path/.../video_old.mp4",
    "matched_finished_at": "2026-04-20T...",
    "downloaded_path":     null | "/abs/path/...",     # 仅 trigger_source=="finish" 时填
    "created_at":          "2026-04-29T01:23:45.678",
    "expires_at_epoch":    1714356235.678              # created_at + 10s，后端定时任务用
}
```

### 5.2 生命周期

```
创建：_create_toast(...) → state.pending_toasts.append(...) → 立即 _broadcast()
推送：WebSocket payload 字段 pending_toasts: list[dict] 全量送
更新：用户点按钮 → 调对应 API → 服务端处理 + 移出 pending_toasts → _broadcast()
超时：后端定时任务（每 1s）扫描 → expires_at_epoch < now() → 按 trigger_source 默认行为处理
```

### 5.3 后端定时任务

新增 `downloader/toast_monitor.py`：

```python
async def toast_monitor_loop():
    while True:
        try:
            await asyncio.sleep(1)
            await _expire_pending_toasts()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.error(f"toast monitor 异常：{e}")

async def _expire_pending_toasts():
    now = time.time()
    expired = [t for t in state.pending_toasts if t["expires_at_epoch"] < now]
    if not expired:
        return
    for toast in expired:
        await _apply_default_action(toast)

async def _apply_default_action(toast):
    """超时默认行为：fuid 场景默认入队，finish 场景默认保留。"""
    src = toast.get("trigger_source")
    state.pending_toasts = [t for t in state.pending_toasts if t["toast_id"] != toast["toast_id"]]
    if src in ("handle_media", "api_download"):
        # 默认「加入队列」
        _enqueue_from_toast(toast)
        _log.info(f"[toast] {toast['toast_id']} 超时默认入队（{src}/{toast['duplicate_type']}）")
    else:  # "finish"
        # 默认「保留」 = no-op
        _log.info(f"[toast] {toast['toast_id']} 超时默认保留（finish/md5）")
    storage.save_duplicate_queue(state.duplicate_queue) if src in ("handle_media", "api_download") else None
    await _broadcast()
```

`_enqueue_from_toast(toast)` 把 toast 字段映射到 duplicate_queue 条目（详见 §6），**复用 F6 的队列 dedup**（同 task_id 不重复入队）。

启动入口（`bot.py` / `downloader/main.py`）：

```python
asyncio.create_task(toast_monitor_loop())
```

不用合并到 `_broadcast_loop`（0.5s）或 `disk_check_loop`（60s），独立 1s 周期。

### 5.4 前端展示

- **位置**：右下角固定，**回顶按钮上方**（`bottom: 80px; right: 24px; z-index: 1100`），不与 disk-banner（top, z-index 1000）冲突
- **同时显示数量**：最多 3 张卡片，更多时按 created_at 排序保留最新 3 条
- **样式**：暗色主题、宽 ~360px、阴影 + 边框
- **倒计时数字**：基于 `expires_at_epoch - Date.now()/1000`，**不**前端独立计数（避免多浏览器漂移）
- **多浏览器**：每秒计算 `Math.max(0, Math.ceil(expires_at_epoch - now))`；倒计时归 0 后等待 WS 推送的 pending_toasts 自然移除（后端定时任务负责清理）
- **已被处理**：WS payload 里 toast 不再出现 → 前端 DOM 立即移除
- **按钮点击**：调对应 API 后立即移除本地 DOM（乐观更新）；多浏览器另一个会被服务端 404，前端 catch 后忽略

---

## 6. duplicate_queue 新增字段

F6 现有字段保留：
```
task_id, chat_id, message_id, filename, size_mb, source_label,
last_downloaded_at, previous_status, queued_at, grouped_id
```

新增字段（仅 fuid/md5 toast 入队的条目填）：
```
duplicate_type:      "task_id" | "fuid" | "md5"
matched_filename:    str
matched_path:        str
matched_finished_at: str
```

兼容性：
- 旧条目无新字段 → 前端 `|| ''` 兜底
- F6 silent enqueue 路径加 `duplicate_type: "task_id"` 但**不填** matched_* 字段（同消息没有"另一个文件"概念）
- 前端面板：`duplicate_type` 在 `("fuid", "md5")` 时额外显示一行"内容与 {matched_filename}（{matched_path}）相同，下载于 {matched_finished_at}"，`matched_path` 显示为可点击链接（调 `/api/open`，失败时 toast 警告"原文件可能已被搬运/移动"）

---

## 7. 状态管理改动

### 7.1 `downloader/state.py`

```python
content_index: dict = {"md5": {}, "fuid": {}}
pending_toasts: list[dict] = []
```

### 7.2 `downloader/storage.py`

新增：

```python
def load_content_index() -> dict:
    if not config.CONTENT_INDEX_FILE.exists():
        return {"md5": {}, "fuid": {}}
    try:
        data = json.loads(config.CONTENT_INDEX_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"md5": {}, "fuid": {}}
        data.setdefault("md5", {})
        data.setdefault("fuid", {})
        return data
    except Exception as e:
        _log.error(f"[downloader] 加载 content_index.json 失败: {e}")
        return {"md5": {}, "fuid": {}}

def save_content_index(idx: dict) -> None:
    _atomic_write_json(config.CONTENT_INDEX_FILE, idx)
```

`pending_toasts` **不持久化**（重启后丢失，符合 toast 一次性 UI 提示语义）。重启时如有 `_finish` 进行中的 MD5 任务被打断，重启后不会重算（除非用户手动 retry）—— 接受此局限。

### 7.3 `config.py`

```python
CONTENT_INDEX_FILE = Path("content_index.json")
```

### 7.4 `.gitignore`

新增一行：
```
content_index.json
```

### 7.5 启动加载

`bot.py` 与 `downloader/main.py` 的 `main()` 中（与 pending_tasks/grouped_state/duplicate_queue 同位置）：

```python
state.content_index = storage.load_content_index()
if state.content_index["md5"] or state.content_index["fuid"]:
    _log.info(f"[downloader] 加载 content_index：{len(state.content_index['md5'])} md5 / {len(state.content_index['fuid'])} fuid")
```

启动入口同时启动 `toast_monitor_loop`（详见 §5.3）。

---

## 8. 后端 API

### 8.1 路由清单

```
GET    /api/toasts                          → 返回当前 pending_toasts（与 WS 一致，调试用）
POST   /api/toast/{toast_id}/queue          → 加入 duplicate_queue + 移出 pending_toasts
POST   /api/toast/{toast_id}/skip           → 跳过下载（fuid 场景：丢弃；finish 场景：删文件 + 删 completed）
POST   /api/toast/{toast_id}/download       → 启动「直接下载」（仅 fuid 场景有效）
POST   /api/toast/{toast_id}/keep           → 保留（仅 finish 场景有效，no-op + 移出）
POST   /api/toast/{toast_id}/open-matched   → 打开 matched_path 所在目录（finish 场景「查看重复」）
DELETE /api/toast/{toast_id}                → 强制删除 toast（不触发任何副作用，给前端兜底）
```

### 8.2 行为细节

- **/queue**：把 toast 字段映射到 duplicate_queue 条目（duplicate_type 取 toast.duplicate_type）；F6 队列内按 task_id 去重；移出 pending_toasts；`_broadcast()`
- **/skip**（fuid 场景）：移出 pending_toasts；`_broadcast()`
- **/skip**（finish 场景）：尝试 `os.unlink(toast["downloaded_path"])`（失败静默，可能 mover 搬走）；从 completed_downloads 移除 `task_id == toast["task_id"]` 的记录并 save_completed；移出 pending_toasts；`_broadcast()`
- **/download**：仅 trigger_source ∈ {handle_media, api_download} 接受；复用 `/api/download` 的内部路径（`client.get_messages` + 新建 `unique_dir` + `download_one`），task_id 后缀 `_dup{ts}`，**不**对新任务再做 fuid 查重（绕过）；移出 pending_toasts
- **/keep**：仅 trigger_source == "finish" 接受；no-op；移出 pending_toasts
- **/open-matched**：内部调 `/api/open` 同款逻辑，path 取 `Path(toast["matched_path"]).parent`；失败返回 `{ok: false, error: "..."}` 让前端展示警告
- 不存在的 toast_id：所有路由统一返回 `404 {ok: false, error: "toast not found"}`

### 8.3 路由注册

`downloader/web/server.py` 的 `_build_web_app` 末尾追加 7 条路由（紧接 duplicate-queue 路由之后，保持模块化分组）。

---

## 9. 前端 UI

### 9.1 容器

`<body>` 末尾新增：

```html
<div id="toasts-container" style="position:fixed;bottom:80px;right:24px;z-index:1100;
     display:flex;flex-direction:column-reverse;gap:10px;max-width:380px"></div>
```

`column-reverse` 让最新的 toast 在最下方（贴近视觉焦点）。

### 9.2 卡片样式

```css
.toast-card{background:#1f1f1f;border:1px solid #444;border-radius:8px;
  padding:12px 14px;color:#e0e0e0;box-shadow:0 4px 16px rgba(0,0,0,.5);
  font-size:.85rem;line-height:1.5;animation:toast-in .25s ease-out}
.toast-card .toast-title{color:#ffd54f;font-weight:600;margin-bottom:6px}
.toast-card .toast-meta{color:#888;font-size:.78rem;word-break:break-all}
.toast-card .toast-path{color:#5db;font-family:monospace;font-size:.75rem;cursor:pointer}
.toast-card .toast-path:hover{text-decoration:underline}
.toast-card .toast-actions{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.toast-card .toast-countdown{color:#888;font-size:.75rem;margin-left:auto}
@keyframes toast-in{from{transform:translateX(20px);opacity:0}to{transform:translateX(0);opacity:1}}
```

### 9.3 渲染

每次 WS 推送（`render(d)` 内）调 `updateToasts(d.pending_toasts || [])`：

```js
function updateToasts(toasts) {
  const container = document.getElementById('toasts-container');
  // 按 created_at 倒序，截最新 3 条
  const sorted = toasts.slice().sort((a,b) => (b.created_at || '').localeCompare(a.created_at || '')).slice(0, 3);
  // 全量重渲染（toast 数量小，简单可靠）
  container.innerHTML = sorted.map(renderToastCard).join('');
}

function renderToastCard(t) {
  const isFuid = t.trigger_source !== 'finish';
  const sizeText = t.size_mb > 0 ? t.size_mb + ' MB' : '';
  const headerText = isFuid ? '⚠️ 检测到重复文件' : '⚠️ 已下载文件与历史重复';

  let body = '<div class="toast-meta">'
    + esc(t.filename || '(未知)') + (sizeText ? '  ·  ' + sizeText : '')
    + '</div>'
    + '<div class="toast-meta" style="margin-top:4px">与以下文件内容相同：</div>'
    + '<div class="toast-meta">' + esc(t.matched_filename || '(未知)') + '</div>'
    + '<div class="toast-path" data-toast-id="' + esc(t.toast_id) + '" data-action="open-matched" title="点击打开所在文件夹">'
    + esc(t.matched_path || '') + '</div>'
    + '<div class="toast-meta" style="margin-top:4px">下载于 ' + esc(t.matched_finished_at || '-') + '</div>';

  let buttons;
  if (isFuid) {
    buttons = '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="queue">加入队列</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="skip" style="color:#ef9a9a">跳过下载</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="download" style="color:#81c784">直接下载</button>';
  } else {
    buttons = '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="open-matched">查看重复</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="skip" style="color:#ef9a9a">跳过</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="keep">保留</button>';
  }

  return '<div class="toast-card" data-toast-id="' + esc(t.toast_id) + '">'
    + '<div class="toast-title">' + headerText + '</div>'
    + body
    + '<div class="toast-actions">' + buttons
    + '<span class="toast-countdown" data-expires="' + t.expires_at_epoch + '">10s</span>'
    + '</div></div>';
}
```

### 9.4 倒计时

独立的 `setInterval(updateCountdowns, 1000)`：

```js
function updateCountdowns() {
  const now = Date.now() / 1000;
  document.querySelectorAll('.toast-countdown').forEach(el => {
    const exp = parseFloat(el.dataset.expires);
    const left = Math.max(0, Math.ceil(exp - now));
    el.textContent = left + 's';
    if (left <= 3) el.style.color = '#ef5350';
  });
}
```

### 9.5 按钮事件代理

```js
document.getElementById('toasts-container').addEventListener('click', async e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const tid = btn.dataset.toastId;
  const action = btn.dataset.action;
  const map = {
    'queue':        ['POST',   '/api/toast/' + encodeURIComponent(tid) + '/queue'],
    'skip':         ['POST',   '/api/toast/' + encodeURIComponent(tid) + '/skip'],
    'download':     ['POST',   '/api/toast/' + encodeURIComponent(tid) + '/download'],
    'keep':         ['POST',   '/api/toast/' + encodeURIComponent(tid) + '/keep'],
    'open-matched': ['POST',   '/api/toast/' + encodeURIComponent(tid) + '/open-matched'],
  };
  const [method, url] = map[action] || [];
  if (!method) return;
  btn.disabled = true;
  try {
    const r = await apiFetch(url, {method});
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      // open-matched 失败 → 显示警告（matched_path 可能已被 mover 搬走）
      if (action === 'open-matched') {
        alert('打开失败：原文件可能已被搬运 / 移动\\n' + (j.error || ''));
      } else if (r.status !== 404) {
        // 404 视为已被其他浏览器处理，静默忽略
        alert('操作失败：' + (j.error || r.status));
      }
    }
    // 移除本地 DOM（乐观更新；WS 推送会再校正）
    const card = document.querySelector('[data-toast-id="' + tid + '"].toast-card');
    if (card) card.remove();
  } catch (e) {
    // 网络异常，等 WS 自然刷新
  }
});
```

---

## 10. 不在本次范围

- **启动时扫描 `DOWNLOAD_DIR` 建全量 MD5 索引**：用户可能有 TB 级历史，全量扫描成本高。索引只覆盖"启用此功能后新下载的文件"
- **跨模块去重**：unzipper / mover 不查 content_index，搬运 / 解压不触发去重
- **content_index LRU 淘汰**：条目只增不减；超大量场景（>10 万条）的清理策略后续再做
- **content_index 迁移工具**：从 completed.json / unzipper_history.json 反推已有文件的 MD5
- **删除文件时同步删索引**：用户在文件管理器手动删了 path 指向的文件，content_index 不感知（matched_path 会失效）
- **mover 完成后回填 content_index.path**：path 不主动维护，按 §10.Q5 决策由前端 /api/open 失败时显示警告即可
- **MD5 计算超时取消**：超大文件（>10GB）的 MD5 可能跑很久；不设超时，让 semaphore 自然限并发
- **Toast 持久化**：`pending_toasts` 不写盘，重启全丢失；同步重启时未完成的 `_compute_and_index` 任务也不会续算

---

## 11. 测试矩阵

### 11.1 fuid 命中（下载前）

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 频道 A 发文件 X，下载完 | content_index 写入 `d_<id>` → `<md5>` 关系；正常显示 completed |
| 2 | 频道 B 转发同文件 X（不同 message_id） | handle_media 触发 fuid 命中；不下载；toast 出现，duplicate_type=fuid |
| 3 | 用户点「加入队列」 | duplicate_queue 加一条（带 matched_*）；toast 消失 |
| 4 | 用户点「直接下载」 | 启动新下载（save_dir 独立、task_id 带 _dup 后缀）；toast 消失 |
| 5 | 用户点「跳过下载」 | 不下载、不入队；toast 消失 |
| 6 | 用户 10s 不响应 | 后端定时任务自动入 duplicate_queue；toast 消失 |

### 11.2 MD5 命中（下载后）

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 文件 Y（content 与 X 相同但 file_id 不同，譬如重新上传） | 下载完成；_finish 异步 MD5 → 命中已有 X 的 md5_hex → finish toast |
| 2 | 用户点「查看重复」 | `/api/open` 打开 X 所在文件夹 |
| 3 | 用户点「跳过」 | `os.unlink(downloaded_path)`；从 completed_downloads 移除 Y 的记录；toast 消失 |
| 4 | 用户点「保留」 | 两个文件都保留；toast 消失 |
| 5 | 用户 10s 不响应 | 默认「保留」，no-op，toast 消失 |
| 6 | matched_path 已被 mover 搬走，「查看重复」点击 | `/api/open` 失败 → 前端 alert 警告 |

### 11.3 Race / 并发

| # | 场景 | 期望 |
|---|------|------|
| 1 | archive 文件下载完，mover 立即开始 copy；MD5 同时启动 | `_md5_sync` 读到一半文件被 mover 删除 → FileNotFoundError → 静默放弃，archive 不入索引 |
| 2 | 同时 5 个文件 _finish | `_md5_semaphore(2)` 限 2 并行；其他 3 个等待；事件循环不阻塞（验证 WS 心跳延迟 < 1s） |
| 3 | 同 fuid 的两条消息几乎同时到达 | 第一条进 download 流程；第二条进入 fuid 索引时第一条还没算完 → 第二条也开始下载；下载完后第二个 _finish 算 MD5 → 命中第一个的 md5 → finish toast |
| 4 | 多浏览器都打开页面，都看到同一 toast | 用户在 A 点按钮 → state.pending_toasts 移除 → WS 推 → B DOM 也消失；A B 同时点 → 后到的 404，前端静默 |

### 11.4 与现有功能交互

| # | 场景 | 期望 |
|---|------|------|
| 1 | F6 task_id 命中（同消息重发） | silent enqueue（duplicate_type="task_id"），**不**走 toast |
| 2 | 关掉 watch（频道未监听） | 监听 gate 拦下，根本不走 fuid 检查 |
| 3 | monitoring_paused = true | 监听 gate 拦下，根本不走 fuid 检查 |
| 4 | 启动默认暂停期间，content_index 持久化的索引照常加载 | 加载日志显示 "{n} md5 / {m} fuid" |
| 5 | 重启时 `_compute_and_index` 还没跑完 | 该文件无 MD5 索引；下次相同内容到达时无法在 _finish 阶段命中（fuid 阶段也不命中，因为没写入）→ 走正常下载 |
| 6 | 「直接下载」启动的新任务自身完成后再算 MD5 | 命中刚才「直接下载」的母条 MD5 → 又出 finish toast（行为正确，文件被显式重复了；用户可点「跳过」清理） |

### 11.5 持久化与异常

| # | 场景 | 期望 |
|---|------|------|
| 1 | content_index.json 损坏（手动改成 `{` 不闭合） | 启动加载失败，回退空索引，不阻塞启动 |
| 2 | 持久化写盘时磁盘满 | atomic_write_json 抛异常，日志 ERROR；内存 state 仍有最新数据，下次重启会丢这一次 |
| 3 | toast_monitor_loop 异常 | catch + log，1s 后继续；不影响其他模块 |

---

## 附：决策记录

| 项 | 决策 | 备注 |
|----|------|------|
| Hole 1 | finish 场景按钮：查看重复 / 跳过 / 保留 | 与 fuid 场景按钮文案不同 |
| Hole 2 | MD5 计算 race：try/except FileNotFoundError → 静默放弃 | archive 文件接受不入索引 |
| Hole 3 | fuid key：`d_<document.id>` / `p_<photo.id>`，其他类型跳过 | 前缀防止 int 空间冲突 |
| Hole 4 | MD5 同步 IO 必须 `run_in_executor` | 否则阻塞事件循环 |
| Hole 5 | 倒计时后端 1s 周期任务；前端只显示 | 用户不在线也能兜底 |
| Hole X | finish toast 超时默认「保留」 | 最安全，避免误删 |
| Q1 | task_id 命中保持 F6 silent enqueue | 不走 toast |
| Q2 | toast「直接下载」走 /api/download 模式（孤立新文件夹） | 简单可靠 |
| Q3 | toast 加 chat_id / message_id / trigger_source / downloaded_path | 字段补全 |
| Q4 | 全部 WS 推送；HTTP 仅返回 toast_id | 单一信息源 |
| Q5 | matched_path 不主动维护；前端 /api/open 失败时警告 | 简单 |
| Q6 | `asyncio.Semaphore(2)` 限 MD5 并行 | 平衡 CPU/IO 与吞吐 |
