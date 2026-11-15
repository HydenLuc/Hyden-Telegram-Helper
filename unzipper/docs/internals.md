# Unzipper 内部机制

## 核心数据流

### a. 自动触发流程（watchdog）

```
文件系统事件
    │  watchdog.Observer（线程）
    ▼
_ArchiveHandler.on_created()
    │  _wait_stable() / _wait_stable_dir()  等待文件写入完成
    │  asyncio.run_coroutine_threadsafe()   桥接线程→事件循环
    ▼
asyncio.Queue  ← put(('auto'|'multipart'|'folder', path))
    │
    ▼  N 个 _queue_worker 并行消费
_queue_worker()
    │  'auto'      → _process_single(path, "single")  直接处理
    │  'multipart' → pending_multipart[id] = ...       等待确认
    │  'folder'    → pending_multipart[id] = ...       等待确认
    ▼
_process_single() / _process_folder()
    │  async with _task_semaphore  最多 MAX_CONCURRENT_TASKS 个并发
    ▼
extractor.extract()
    │  loop.run_in_executor()  解压在线程池中执行（不阻塞事件循环）
    ▼
state.history.append()  +  save_history()
    ▼
_try_broadcast()  →  websocket._broadcast()  →  前端 UI 更新
```

### b. API 触发流程

```
HTTP POST /api/submit  {"path": "/abs/path/to/x.zip"}
    │
    ▼
api._api_submit()
    │  路径安全校验：绝对路径、存在、不在 OUTPUT_PATH 内
    ▼
manager.submit(path)
    │  is_dir()  → pending（等确认）
    │  .7z.001   → pending（等确认）
    │  其他      → asyncio.create_task(_process_single(...))
    ▼
（同自动触发流程的 _process_single 分支）
```

### c. 确认流程

```
前端点击"确认解压" / HTTP POST /api/confirm/{id}
    │
    ▼
api._api_confirm()  →  manager.confirm_pending(id)
    │  从 pending_multipart 弹出记录
    ▼
asyncio.create_task(_process_folder / _process_single(..., "multipart"))
    │
    ▼
（同上，受信号量控制）
```

---

## 并发模型

```
                asyncio.Semaphore(MAX_CONCURRENT_TASKS)
                       │ 最多 N 个槽位
      ┌────────────────┼────────────────┐
      │                │                │
_process_single    _process_single   _process_folder
(task_id="1")      (task_id="2")     (task_id="3")
      │                │                │
run_in_executor   run_in_executor   run_in_executor
（线程池，真并发）  （线程池，真并发）  （线程池，真并发）
```

- **asyncio 事件循环**：单线程，调度所有协程
- **线程池**（`run_in_executor`）：实际解压操作在此并发执行，不阻塞事件循环
- **信号量**：精确控制同时持有槽位的任务数，与 worker 数量解耦
- **N 个 queue worker**：`start()` 时启动 `MAX_CONCURRENT_TASKS` 个，增大并发时自动补充
- **运行时变更**：`set_max_concurrent(n)` 替换信号量对象，旧任务持有旧信号量直至完成

---

## 全局状态（`unzipper/state.py`）

| 字段 | 类型 | 说明 | 持久化 |
|------|------|------|--------|
| `current_tasks` | `dict[str, dict]` | 正在运行的任务，key 为顺序整数字符串 | 否（内存） |
| `pending_multipart` | `dict[str, dict]` | 等待确认的任务，key 为 4 位随机数字字符串 | 否（内存） |
| `history` | `list[dict]` | 已完成/失败的任务记录（最多 100 条） | 是（`unzipper_history.json`） |
| `ws_clients` | `set` | 当前连接的 WebSocket 客户端 | 否（内存） |
| `passwords` | `list[str]` | 解压密码列表（初始值来自 `config.PASSWORDS`）| 是（`.env` `PASSWORDS=`） |
| `max_concurrent_tasks` | `int` | 最大并发解压数（初始值来自 `config.MAX_CONCURRENT_TASKS`）| 是（`.env`） |

`current_tasks` 中每条记录的字段：

```json
{
  "name":                "example.zip",
  "kind":                "single | multipart | folder",
  "status":              "extracting",
  "started_at":          "2026-04-23T10:00:00.123456",
  "trying_password":     "password123 | (无密码) | null",
  "total_archives":      5,
  "current_archive_idx": 2,
  "current_archive":     "part2.zip"
}
```

（`total_archives`、`current_archive_idx`、`current_archive` 仅 `kind=folder` 时存在）

---

## 任务生命周期（状态机）

```
              watcher / API submit
                      │
                      ▼
               ┌─────────────┐
               │   queued    │  在 asyncio.Queue 中等待
               └──────┬──────┘
                      │ _queue_worker 取出
                      ▼
          ┌───────────────────────┐
          │     需要确认？         │
          │  (multipart / folder) │
          └────┬────────┬─────────┘
            是 │        │ 否（auto / API submit）
               ▼        ▼
          ┌─────────┐  ┌──────────────────┐
          │ pending │  │ acquire semaphore │
          └────┬────┘  └────────┬─────────┘
    用户确认 ──┘                │ 获得槽位
                                ▼
                        ┌───────────────┐
                        │  extracting   │  state.current_tasks 中可见
                        └───────┬───────┘
                    ┌───────────┼───────────┐
                    │           │           │
                    ▼           ▼           ▼
                ┌──────┐  ┌─────────┐  ┌─────────┐
                │ done │  │ partial │  │ failed  │
                └──────┘  └─────────┘  └─────────┘
                                │           │
                           部分失败      全部失败
                                └─────┬─────┘
                                      ▼
                              移入 @任务失败/
                                      │
                                      ▼
                        release semaphore，广播状态
                        写入 state.history，持久化
```

**`partial`**：仅文件夹任务会出现，表示部分压缩包成功、部分失败。

**`done`**：单包解压成功 / 文件夹所有包均成功。

---

## 输出目录结构约定

### 单压缩包 / 多卷包

```
OUTPUT_PATH/
└── {archive_stem}/
    ├── 解压内容/
    ├── {original_archive}
    └── password.txt          # "此压缩包没有密码" 或 "解压密码：xxx"
```

### 文件夹任务

```
OUTPUT_PATH/
└── {folder_name}/
    ├── {non_archive_files}   # 非压缩包文件（保留相对目录结构）
    └── {archive_stem}/
        ├── 解压内容/
        ├── {original_archive}
        └── password.txt
```

### 失败任务

```
OUTPUT_PATH/
└── @任务失败/
    └── {task_name}/
        ├── 任务失败.txt       # 文件名、失败原因、详情
        ├── {original_archive}
        └── ...
```

**命名冲突规则**：目标目录名已存在时，依次尝试 `{name}_000`、`{name}_001`……

---

## 广播回调注入（循环依赖解法）

`manager.py` 需要触发 WebSocket 广播，但直接 import `websocket.py` 会造成循环依赖。解法：

```python
# manager.py
_broadcast_cb = None

def set_broadcast_callback(cb):
    global _broadcast_cb
    _broadcast_cb = cb

async def _try_broadcast():
    if _broadcast_cb:
        await _broadcast_cb()
```

```python
# main.py / bot.py（启动时注入）
from unzipper.web.websocket import _broadcast
unzipper.manager.set_broadcast_callback(_broadcast)
await unzipper.manager.start()
```
