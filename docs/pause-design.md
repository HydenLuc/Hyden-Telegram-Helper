# 软暂停设计

> **状态**：✅ 已实现。本文档定义三模块的"软暂停"语义、API 规范、前端规范和 dashboard 状态显示。

## 概述

每个模块支持**独立软暂停**：

- 暂停后**停止接收新任务**
- 当前正在执行的任务**继续跑完**
- 队列中已排队的任务**继续执行**
- 恢复后正常接收新任务

**控制入口**：在各模块自己的前端页面（v1：downloader 和 unzipper 实现；mover 暂只实现 API，前端按钮留待未来）。

**Dashboard 只读**：dashboard 不提供暂停/恢复操作，只读取每个模块的 `paused` 状态在卡片上显示。

---

## API 规范

### 统一端点（三模块）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/pause` | POST | 设置 `state.paused = True` |
| `/api/resume` | POST | 设置 `state.paused = False` |

均走已有的 `auth_middleware`，需要 `X-API-Key` header。

### `paused` 字段载体

为最小化对 dashboard 的改动，`paused` 字段同时加到两个层面：

| 模块 | 加 `paused` 字段的端点 | 备注 |
|---|---|---|
| downloader | `/api/health`（**新增**端点）+ `/api/status` | dashboard 当前轮询 `/api/status` |
| mover | `/api/health`（已有结构，加字段） | dashboard 当前轮询 `/api/health` |
| unzipper | `/api/health`（已有，加字段）+ `/api/state` | dashboard 当前轮询 `/api/state` |

dashboard 不需要改 polling 逻辑，只需在前端 render 时读 `data.{module}.data.paused`。

### 模块级 vs 单任务级 pause（命名澄清）

downloader 已有**单任务级**暂停 API，新增的是**模块级**暂停。两者并存，不冲突：

| 路径 | 粒度 | 行为 |
|---|---|---|
| `POST /api/pause` | **模块级**（新增）| 不再接受新媒体；已有任务继续 |
| `POST /api/resume` | **模块级**（新增）| 恢复接受新媒体 |
| `POST /api/task/{id}/pause` | 单任务级（已有）| `pause_event` clear，下载块循环阻塞 |
| `POST /api/task/{id}/resume` | 单任务级（已有）| `pause_event` set，恢复块下载 |
| `POST /api/task/{id}/cancel` | 单任务级（已有）| 取消单个任务 |

mover 和 unzipper 没有单任务级 pause（它们的任务是搬一次/解一次，无中间暂停语义），只有模块级。

---

## 各模块暂停语义

### Downloader（`:8091`）

#### 暂停效果

- `tg/handlers.py:handle_media` 入口添加：`if state.paused: return`
- **仅拦截媒体自动接收**（`@client.on(events.NewMessage(incoming=True))` 注册的 handler）
- **不影响**用户在 Telegram 中发送的命令：
  - `/ID`、`/搜索 X`、`/监听 X`、`/取消监听 X`、`/监听列表` 等仍然照常工作（这些是 `outgoing=True` 命令，由 `cmd_*` handler 处理，与媒体接收解耦）
- 当前正在下载的任务（`download_one` 协程）继续运行
- 已排队（`active_downloads` 中等待连接）的任务继续执行

#### 暂停期间消息处理

暂停期间收到的新媒体消息**不会被记录**，恢复后**不会补下**。

如需补救，依赖 P1-5b 实现 `pending_tasks.json` 后通过"用户手动触发重扫"补下——**不在本次（P1-5a）范围内**。

---

### Mover（`:8092`）

#### 暂停效果

`POST /api/move` 收到请求时，如果 `state.paused == True`：

1. 任务**仍然创建**（写入 `mover_state.json`），状态为 `pending`（**新增 status**）
2. **不立即分配执行**（不调用 `asyncio.create_task(_do_move)`）
3. 立即返回：
   ```json
   {
     "ok": true,
     "task_id": "...",
     "queued": true,
     "reason": "mover paused"
   }
   ```

幂等性不受影响：相同 `task_id` 重复提交仍然正常去重（`done` → `already_moved`，`failed` → `retrying`）。

#### 恢复后

按 `created_at` 升序触发所有 `pending` 状态的任务：

```python
on_resume:
    pending = [t for t in mover_state.values() if t.status == "pending"]
    pending.sort(key=lambda t: t.created_at)
    for task in pending:
        asyncio.create_task(_do_move(task.task_id))
```

#### 崩溃重启时的 pending 任务

`paused` 状态 v1 不持久化，重启后默认为 `False`。`pending` 状态的任务在启动恢复扫描中处理：

```python
# mover/manager.py:start() 启动恢复扫描扩展
for task in mover_state.values():
    if task.status == "copying":
        # 已有逻辑：标 failed
        task.status = "failed"
        task.error = "interrupted by restart"
    elif task.status == "pending":
        # 新增：重启时 paused=False，立即执行（无需手动 resume）
        asyncio.create_task(_do_move(task.task_id))
```

#### v1 不做前端按钮

mover 当前的 `_index_handler` 只返回简单 `<h1>Mover Service</h1>` 页面，无 JS、无 apiFetch 包装。v1 暂不补全前端：

- 暂停/恢复操作走 **curl + API_KEY**：
  ```bash
  KEY=$(grep '^API_KEY=' .env | cut -d= -f2)
  curl -X POST -H "X-API-Key: $KEY" http://localhost:8092/api/pause
  curl -X POST -H "X-API-Key: $KEY" http://localhost:8092/api/resume
  ```
- 状态显示通过 dashboard 卡片（黄点 + "⏸ 已暂停"）
- 真正的前端按钮可留给未来"mover 前端补齐"任务

---

### Unzipper（`:8093`）

#### 暂停效果

- `unzipper/watcher.py:on_created` 入口添加：`if state.paused: return`（同已有的 `.` 前缀过滤后面）
- watchdog 本身**继续运行**（继续监听文件系统事件，只是不入队）
- 当前正在解压的任务（`current_tasks`）**继续运行**
- 已排队（pending queue）的任务**继续执行**

#### 恢复后扫描

恢复时扫描 `WATCH_PATH` 下的文件，把符合条件的重新提交到队列。**dedup 规则**（避免重复提交）：

跳过以下文件：

| 跳过条件 | 原因 |
|---|---|
| 路径在 `state.current_tasks` 里 | 正在解压，已知 |
| 路径在 pending_queue 里 | 已排队，已知 |
| 路径以 `.` 开头 | `.mover_staging_*` 等隐藏文件，与 P1-3 过滤一致 |
| 不是支持的压缩包格式 | 非 `ARCHIVE_EXTS` 中的扩展名（`.zip` / `.rar` / `.7z` / `.7z.NNN` 多卷） |

伪代码：

```python
on_resume:
    in_progress_or_queued = (
        {t["path"] for t in state.current_tasks.values()}
        | {item["path"] for item in pending_queue}
    )
    for f in WATCH_PATH.iterdir():
        if str(f) in in_progress_or_queued:
            continue
        if any(p.startswith('.') for p in Path(f).parts):
            continue
        if not is_supported_archive(f):
            continue
        submit(f)
```

---

## 状态机

```
正常运行 (paused=False)
    │
    │  POST /api/pause
    ▼
已暂停 (paused=True)
    │  - 不接受新任务（mover 例外：仍创建但 status=pending）
    │  - 当前任务继续
    │  - 队列中任务继续
    │
    │  POST /api/resume
    ▼
正常运行 (paused=False)
    │  - mover：扫描 status=pending 任务，按 created_at 升序触发
    │  - unzipper：扫描 WATCH_PATH，dedup 后补提交
    │  - downloader：恢复 handle_media 接收新媒体（不补下暂停期间的）
    ▼
正常运行 (...)
```

崩溃重启额外语义：

- `paused` 状态不持久化 → 重启后默认 `False`
- mover：`pending` 任务在启动恢复扫描中立即执行
- unzipper：watchdog 重启后正常监听新文件（暂停期间落地的旧文件不会自动补处理，需要手动重启或调 `/api/submit`）
- downloader：暂停期间收到的消息已丢失，无法补下

---

## Dashboard 状态显示

### 数据流

```
浏览器 → http://localhost:8090/api/overview
            │
            ▼
        dashboard 后端 fetch 三模块（带 X-API-Key）
            │  downloader /api/status  (含 paused 字段)
            │  mover     /api/health   (含 paused 字段)
            │  unzipper  /api/state    (含 paused 字段)
            ▼
        透传聚合 → 浏览器
```

dashboard 后端**不做特殊聚合**，前端在 render 时读取 `data.{module}.data.paused`。

### 卡片颜色规则

| 模块状态 | 圆点 | 边框 | 标签 |
|---|---|---|---|
| online + paused=false | 🟢 绿色 | 默认（灰）| 无 |
| online + paused=true | 🟡 黄色 | 默认（灰）| ⏸ 已暂停 |
| offline | 🔴 红色 | 红色 | 状态：离线 |

注意：暂停的"黄色"和现有"mover failed > 0"的"黄色边框"在视觉上有区别——暂停是**圆点**变黄，failed 是**边框**变黄。两者可叠加显示。

---

## 前端按钮规范

### Downloader 和 Unzipper

**位置**：参考现有「设置」区域风格，加在导航栏或页面顶部独立区。

**外观**：

| 状态 | 按钮文案 | 颜色 |
|---|---|---|
| `paused = false` | `⏸ 暂停` | 灰色 / 次要按钮 |
| `paused = true` | `▶ 恢复` | 橙色 / 警示按钮 |

**交互**：点击调 `apiFetch('/api/pause', {method:'POST'})` 或 `/api/resume`，成功后立即 UI 反馈（不等下次轮询）。

WebSocket 推送时也同步更新（如果 broadcast payload 含 `paused` 字段）。

### Mover（v1 跳过）

mover v1 不做前端按钮——通过 dashboard 显示状态 + 用户用 curl 操作（见上文 Mover 章节）。

---

## 不在本次范围

- **硬停止/启动进程**（`kill` / `nohup` 等系统级操作，由 `start.sh` / `stop.sh` 负责）
- **暂停状态持久化**（重启后默认 `paused=False`；持久化留待未来）
- **Downloader 暂停期间消息的补下**（依赖 P1-5b `pending_tasks` 实现 + 手动重扫机制）
- **Mover v1 前端按钮**（v1 仅 API；前端按钮留给未来"mover 前端补齐"任务）
- **优雅等待所有任务完成后再标记暂停**（当前是"立即停止接收新任务，已有任务自然完成"，不阻塞响应）
