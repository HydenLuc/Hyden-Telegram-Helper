# Mover API 参考手册

## 基本信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://localhost:8092`（由 `MOVER_PORT` 配置） |
| 认证 | 无（本地服务，当前版本不需要 API Key） |
| 请求体格式 | `Content-Type: application/json` |
| 响应格式 | 操作类端点：`{"ok": true}` 或 `{"ok": false, "error": "..."}`；查询类端点直接返回数据 |

**重要**：`POST /api/move` 是**纯异步**接口，立即返回 `task_id`，**不等待搬运完成**。任务状态变化通过 WebSocket 推送，调用方应订阅 `/ws` 等待 `done`/`failed` 事件。

---

## GET /

返回 Mover Web 状态监控页面（HTML，只读视图）。

---

## GET /ws

WebSocket 连接端点。连接后立即推送完整状态快照，之后每 1 秒广播一次，任务状态变化时也立即推送。

### 推送数据结构

```json
{
  "tasks": {
    "msg_group_123": {
      "task_id":        "msg_group_123",
      "source":         "/downloads/telegram/频道名/20260423_video",
      "target":         "/watch/频道名/20260423_video",
      "status":         "copying",
      "created_at":     "2026-04-23T10:00:00.000000",
      "completed_at":   null,
      "error":          null,
      "files_attempted": 3,
      "files_completed": 1,
      "failed_at":      null,
      "error_source":   null,
      "is_cross_fs":    false,
      "total_size":     104857600
    }
  },
  "running":     1,
  "queue_depth": 0
}
```

> **字段说明（P2-10 修复）**：
> - `failed_at`：失败时刻的 ISO 时间戳（仅 `status=failed` 时非空）
> - `error_source`：失败时记录的源文件路径
> - 旧 `mover_state.json` 中 `failed_at` 误存路径的，启动时会自动迁移到 `error_source`

**`status` 枚举**：`pending` / `copying` / `done` / `failed`

---

## POST /api/move

发起搬运任务。立即返回，**不等待搬运完成**。

### 请求体

```json
{
  "source":  "/abs/path/to/source_dir_or_file",
  "target":  "/abs/path/to/target_parent_dir/",
  "task_id": "msg_group_123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 源路径（绝对路径，文件或目录） |
| `target` | string | 是 | 目标**父目录**（绝对路径，末尾 `/` 可选）；搬运后路径为 `target/<source 的 basename>` |
| `task_id` | string | 是 | 调用方提供的唯一任务 ID（downloader 用消息组 ID 或任务 ID） |

### 响应

**新任务，立即入队**：
```json
{"ok": true, "task_id": "msg_group_123"}
```

**同 task_id 已完成（幂等返回）**：
```json
{"ok": true, "already_moved": true, "target_path": "/watch/频道名/20260423_video"}
```

**同 task_id 正在搬运中**：
```json
{"ok": true, "in_progress": true, "task_id": "msg_group_123"}
```

**同 task_id 之前失败，覆盖重试**：
```json
{"ok": true, "task_id": "msg_group_123", "retrying": true}
```

### 错误

| 状态码 | error | 说明 |
|--------|-------|------|
| 400 | `"source, target, task_id are required"` | 缺少必填字段 |
| 400 | `"source must be an absolute path"` | source 非绝对路径 |
| 400 | `"target must be an absolute path"` | target 非绝对路径 |
| 404 | `"source path does not exist"` | source 路径不存在 |

> **异步失败场景**：以上错误均在请求阶段同步返回。target 路径冲突属于执行阶段失败——API 仍返回 `{"ok": true}`，任务进入 `failed` 状态，`error` 字段：
> ```
> "target path already exists: /watch/archive.zip"
> ```
> 调用方需自行解决冲突（更换 target、删除旧文件或放弃），然后重新提交。

### curl 示例

```bash
curl -X POST http://localhost:8092/api/move \
  -H "Content-Type: application/json" \
  -d '{
    "source":  "/downloads/telegram/频道名/20260423_video",
    "target":  "/watch/频道名/",
    "task_id": "msg_group_123"
  }'
```

---

## GET /api/tasks

查询搬运任务列表（按 `created_at` 倒序）。

### 请求

Query 参数（均可选）：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | string | — | 过滤状态：`pending` / `copying` / `done` / `failed` |
| `limit` | int | `20` | 返回条数上限，最大 100 |
| `offset` | int | `0` | 跳过条数（分页） |

### 响应

```json
{
  "ok":     true,
  "items":  [ ... ],
  "total":  42,
  "limit":  20,
  "offset": 0
}
```

每条 item 字段与 WebSocket `tasks` 里的单条记录相同。

### curl 示例

```bash
# 最新 20 条
curl http://localhost:8092/api/tasks

# 仅失败任务
curl "http://localhost:8092/api/tasks?status=failed"

# 分页
curl "http://localhost:8092/api/tasks?limit=10&offset=10"
```

---

## GET /api/tasks/{task_id}

查询单个任务的完整状态。

### 路径参数

| 参数 | 说明 |
|------|------|
| `task_id` | 任务 ID |

### 响应

```json
{
  "ok":             true,
  "task_id":        "msg_group_123",
  "source":         "/downloads/telegram/频道名/20260423_video",
  "target":         "/watch/频道名/20260423_video",
  "status":         "done",
  "created_at":     "2026-04-23T10:00:00.000000",
  "completed_at":   "2026-04-23T10:00:00.250000",
  "error":          null,
  "files_attempted": 3,
  "files_completed": 3,
  "failed_at":      null,
  "error_source":   null,
  "is_cross_fs":    false,
  "total_size":     104857600
}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 404 | 任务不存在 |

### curl 示例

```bash
curl http://localhost:8092/api/tasks/msg_group_123
```

---

## DELETE /api/tasks/{task_id}

从历史记录中删除一条任务（**不影响文件**）。

### 路径参数

| 参数 | 说明 |
|------|------|
| `task_id` | 任务 ID |

### 响应

```json
{"ok": true}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 404 | 任务不存在 |

### curl 示例

```bash
curl -X DELETE http://localhost:8092/api/tasks/msg_group_123
```

---

## POST /api/tasks/{task_id}/retry

重试一个失败的任务。source 路径必须仍然存在。

### 路径参数

| 参数 | 说明 |
|------|------|
| `task_id` | 失败任务的 ID |

### 响应

```json
{"ok": true, "task_id": "msg_group_123"}
```

### 错误

| 状态码 | error | 说明 |
|--------|-------|------|
| 404 | `"task not found"` | 任务不存在 |
| 400 | `"task is not in failed status"` | 任务状态非 `failed` |
| 404 | `"source path no longer exists"` | 源路径已不存在 |

### curl 示例

```bash
curl -X POST http://localhost:8092/api/tasks/msg_group_123/retry
```

---

## POST /api/tasks/clear

清空**所有**历史记录（**不影响文件**）。

### 响应

```json
{"ok": true, "deleted": 42}
```

### curl 示例

```bash
curl -X POST http://localhost:8092/api/tasks/clear
```

---

## GET /api/health

服务健康检查，返回当前运行状态摘要。

### 响应

```json
{
  "ok":           true,
  "status":       "busy",
  "running_tasks": 1,
  "queue_depth":   2,
  "total_tasks":   15,
  "failed_tasks":  0,
  "mover_port":    8092,
  "max_concurrent": 3
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `"busy" \| "idle"` | 有正在搬运的任务则为 `busy` |
| `running_tasks` | int | 当前并发搬运数 |
| `queue_depth` | int | 等待 Semaphore 的任务数 |
| `total_tasks` | int | 历史记录总条数 |
| `failed_tasks` | int | 状态为 `failed` 的任务数 |
| `max_concurrent` | int | `MOVER_MAX_CONCURRENT` 配置值 |

### curl 示例

```bash
curl http://localhost:8092/api/health
```

---

## POST /api/open

**用途**：在文件管理器中打开活跃任务的目标父目录。

### 请求

```http
POST /api/open
Content-Type: application/json
X-API-Key: <key>
```

```json
{ "path": "/abs/parent/dir" }
```

### 响应

成功（200）：
```json
{ "ok": true }
```

失败：

| 状态码 | error 字段 | 触发条件 |
|--------|------------|----------|
| 400 | `"path required"` | body 缺 path 或为空 |
| 403 | `"path not allowed"` | path 不是任何活跃任务（pending/copying）的 target 父目录 |
| 404 | `"not found"` | 路径白名单通过但目录不存在 |

### 说明

允许范围 = 当前 `state.tasks` 中所有 `status in ("pending", "copying")` 任务的 `target` 父目录的并集。无活跃任务时所有 path 都会被拒绝。

后端调用 `xdg-open` 异步打开，不等待子进程完成。
