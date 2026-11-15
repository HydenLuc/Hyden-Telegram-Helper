# Downloader 内部机制

## 任务生命周期（状态机）

```
Telegram 新消息事件 / POST /api/download
            │
            ▼
    ┌───────────────┐
    │    waiting    │  已加入 active_downloads，等待连接门控放行
    └───────┬───────┘
            │ _acquire_connections(n_conns) 获得槽位
            ▼
    ┌───────────────┐
    │  downloading  │  dl_task 运行中（分块 or 单连接）
    └───┬───┬───┬───┘
        │   │   │
        │   │   └─────────── 用户调用 /api/task/{id}/pause
        │   │                        ▼
        │   │                ┌───────────────┐
        │   │                │    paused     │  pause_event.clear()，块级暂停
        │   │                └───────┬───────┘
        │   │                        │ /api/task/{id}/resume → pause_event.set()
        │   │                        └────────────── → downloading
        │   │
        │   └──────────────── FloodWaitError 触发
        │                             ▼
        │                    ┌────────────────┐
        │                    │   flood_wait   │  asyncio.sleep(e.seconds + backoff)
        │                    └────────┬───────┘
        │                             │ 等待结束（最多重试 FLOOD_RETRY_MAX 次）
        │                             └────────────── → downloading（重试）
        │
        │ 下载完成
        ▼
    ┌───────────────┐
    │     done      │  path / dir 填入，pct=100
    └───────────────┘

    异常路径：
    ├─ 用户取消       → error  (error_msg: "已手动取消")
    ├─ 超时无进度     → timeout (error_msg: "超过 Xs 无进度，已取消")
    ├─ FloodWait 耗尽重试 → error
    └─ 其他异常      → error  (error_msg: "ExceptionType: message")
```

取消中间态 `cancelling` 在前端显示，由 `/api/task/{id}/cancel` 设置后等待实际任务退出。

---

## 连接门控（asyncio.Condition）

全局最多 `MAX_TOTAL_CONNECTIONS`（默认 20）个并行 HTTP 连接。每个下载任务根据文件大小申请 `n_conns` 个槽位（见下节），超限时 `await`（不是 sleep，释放事件循环）直到有任务释放。

```python
# 申请
async with state._conn_gate:          # asyncio.Condition
    while state._total_connections + n > state.MAX_TOTAL_CONNECTIONS:
        await state._conn_gate.wait() # 等待通知
    state._total_connections += n

# 释放（finally 中）
async with state._conn_gate:
    state._total_connections -= n
    state._conn_gate.notify_all()     # 唤醒所有等待者
```

`/api/settings` 修改 `MAX_TOTAL_CONNECTIONS` 时会立即 `notify_all()`，让等待中的任务重新评估是否可以开始。

---

## 自适应分块策略

根据文件大小决定并行连接数（`n_conns`），从而决定是否使用分块下载引擎：

| 文件大小 | n_conns | 下载方式 |
|----------|---------|----------|
| < 50 MB，或大小未知 | 1 | `client.download_media()`（单连接） |
| 50–500 MB | 2 | `_chunked_download()`（分块并行） |
| 500 MB–2 GB | 4 | `_chunked_download()` |
| > 2 GB | 6 | `_chunked_download()` |

**单连接下载**：不支持暂停（无 `pause_event`），可以取消。

**分块下载引擎**（`chunker.py`）：
1. `_chunk_ranges(file_size, n)` 把文件按 `CHUNK_SIZE` 对齐划分成 n 块，每块 `(offset, size)`
2. 每块独立 `asyncio.Task`（`download_chunk(idx)`）调用 `client.iter_download(offset=...)`
3. 每个块内每个 block 前检查 `cancel_flag` 和 `pause_event`
4. 全部块完成后顺序合并（cat part0 + part1 + ... → 目标文件），合并失败时清理所有 `.partN`
5. 速度统计：每块独立计算，总速度 = 各块速度之和

---

## FloodWait 处理

Telegram 限速时抛出 `FloodWaitError(seconds)` 或 `FloodPremiumWaitError`。

```
最多重试 FLOOD_RETRY_MAX（默认 3）次
等待时间 = e.seconds + 退避（5s / 10s / 20s 指数）
重试时清理已下载的临时分块文件，重置进度
若超过最大重试次数，下载失败（status = error）
```

等待期间状态变为 `flood_wait`，WebSocket 推送 `flood_until` 时间戳，前端显示倒计时。等待期间若用户取消（CancelledError），立即清理并设 `error`。

---

## 分块下载数据流

```
download_one(task_id, message, file_path, label)
    │
    ├─ _acquire_connections(n_conns)      门控获取 n 个槽位
    │
    ├─ asyncio.create_task(_chunked_download)  or  client.download_media
    │       │
    │       ├─ download_chunk(0)  ──── iter_download(offset=0,       size=chunk0)
    │       ├─ download_chunk(1)  ──── iter_download(offset=chunk0,  size=chunk1)
    │       └─ download_chunk(n)  ──── iter_download(offset=chunk0+1,size=chunkN)
    │               │
    │               │ 每个 block 写入 file.partN
    │               │ 更新 state.active_downloads[task_id].chunks[idx]
    │               └─ 完成后 speed → 0
    │
    ├─ asyncio.gather(*chunk_tasks)       等待所有块完成
    │
    ├─ 顺序合并 part0..partN → file_path  cat 合并
    │
    └─ _finish(task_id, "done")           记录完成，移入 completed_downloads
```

---

## 消息聚合（grouped_id TTL 缓存）

Telegram 相册（多图/多视频消息）会发多条消息，但共享同一 `grouped_id`。

```python
state._group_dirs: dict[str, dict]
# key:   f"{chat_id}_{grouped_id}"
# value: {dir, ts, detail, count, max_views, max_fwds, no_text}
GROUP_DIR_TTL = 300  # 5 分钟后清理
```

**首条消息**：创建 save_dir，写 `消息详情.txt` header，建立缓存条目。

**后续消息**：复用缓存的 `save_dir`，追加媒体条目到 `消息详情.txt`，更新浏览数/转发数。

**过期清理**：每次收到新消息时清理超过 TTL 的缓存条目。

---

## 全局状态（`downloader/state.py`）

> ⚠️ **持久化分两种后端**（2026-08-19 起）：
> 三个大字典（`pending_tasks` / `grouped_state` / `content_index`）走 **SQLite
> 增量写**（`state.db`，见 `downloader/kvstore.py`）——改一条写一行；
> 其余仍是 JSON 全量原子写 + 2 秒合并。
> 起因是原来 `pending_tasks.json`（17.7 MB）**每 2 秒被完整重写一次**，
> 详见 `downloader/docs/reliability.md` 的「落盘」一节。
> **读路径两者一样**：启动时整份读进内存，业务代码操作普通 dict。


| 字段 | 类型 | 说明 | 持久化 |
|------|------|------|--------|
| `watched` | `dict[str, str]` | 监听列表，key=chat_id，value=名称 | 是（`watched_chats.json`） |
| `active_downloads` | `dict[str, dict]` | 正在进行的任务，key=task_id | 否（内存） |
| `completed_downloads` | `list[dict]` | 已完成/失败记录（最多 `MAX_HISTORY` 条） | 是（`completed.json`） |
| `pending_tasks` | `dict[str, dict]` | 未完成任务，key=task_id | 是（**`state.db`** 表 `pending_tasks`）|
| `grouped_state` | `dict[str, dict]` | 媒体组下载状态，key=group_key | 是（**`state.db`** 表 `grouped_state`）|
| `content_index` | `dict` | MD5 去重索引 `{"md5": {...}, "fuid": {...}}` | 是（**`state.db`** 表 `content_md5` / `content_fuid`）|
| `duplicate_queue` | `list[dict]` | 待确认的重复下载 | 是（`duplicate_queue.json`）|
| `history_jobs` | `dict[str, dict]` | 历史消息拉取 job | 是（`history_jobs.json`）|
| `ws_clients` | `set` | 当前连接的 WebSocket 客户端 | 否（内存） |
| `bot_start_time` | `datetime` | 启动时间，用于过滤启动前的历史消息 | 否（内存） |
| `_conn_gate` | `asyncio.Condition` | 连接门控，在 `main()` 中初始化 | 否（内存） |
| `_total_connections` | `int` | 当前已申请的连接数 | 否（内存） |
| `_pending_tasks` | `set[Task]` | 持有 Task 引用，防止 GC | 否（内存） |
| `_group_dirs` | `dict[str, dict]` | grouped_id TTL 缓存（5 分钟） | 否（内存） |
| `_auth_step` | `str` | 当前 auth 阶段（idle/waiting_code/waiting_password） | 否（内存） |
| `_auth_future` | `Future \| None` | 等待网页输入的 Future | 否（内存） |
| `task_controls` | `dict[str, dict]` | 每任务的 pause_event / cancel_flag / dl_task | 否（内存） |
| `task_outer_tasks` | `dict[str, Task]` | 每任务的外层 download_one Task，用于取消 waiting/flood_wait 状态 | 否（内存） |
| `MAX_TOTAL_CONNECTIONS` | `int` | 运行时可变（初始值来自 config） | 是（`.env`） |
| `CHUNK_SIZE` | `int` | 运行时可变（初始值来自 config） | 是（`.env`） |

`active_downloads` 中每条记录的字段：

```json
{
  "task_id":    "chat_id_message_id",
  "label":      "源名称/目录名",
  "filename":   "video.mp4",
  "current":    52428800,
  "total":      104857600,
  "pct":        50,
  "current_mb": 50.0,
  "size_mb":    100.0,
  "status":     "downloading",
  "started_at": 1745000000.0,
  "finished_at": null,
  "error_msg":  "",
  "path":       "",
  "dir":        "",
  "speed":      2097152.0,
  "chat_id":    -1001234567890,
  "message_id": 12345,
  "chunks":     null,
  "flood_until": null,
  "n_conns":    1
}
```

`chunks` 字段仅分块下载时存在，每个元素为 `{"id": N, "current": bytes, "total": bytes, "pct": %, "speed": bytes/s}`。

---

## 登录流程（网页验证码）

`tg/handlers.py` 向 Telethon 注册 code/password 回调：

```python
await client.start(
    phone=config.PHONE,
    code_callback=_web_code_callback,
    password=_web_password_callback,
)
```

回调函数设置 `state._auth_step` 和 `state._auth_future`，WebSocket 推送触发前端弹出输入框，用户提交后 `POST /api/auth {"value": "..."}` 解析 Future，Telethon 完成登录。
