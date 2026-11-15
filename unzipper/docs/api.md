# Unzipper API 参考手册

## 基本信息

**Base URL**：`http://localhost:{UNZIPPER_PORT}`（默认端口 `8093`）

**统一响应格式**

成功：
```json
{"ok": true, ...data}
```

失败：
```json
{"ok": false, "error": "错误描述"}
```

**HTTP 状态码约定**

| 状态码 | 含义 |
|--------|------|
| `200` | 成功 |
| `400` | 请求参数错误（缺少字段、类型错误、路径非绝对路径等） |
| `403` | 权限不足（路径不在允许范围内） |
| `404` | 资源未找到（路径不存在、ID 不存在、密码不存在） |
| `409` | 冲突（如添加已存在的密码） |

---

## GET /

**简介**：返回 Unzipper Web 控制台页面（HTML）。

打开浏览器访问 `http://localhost:8093` 即可使用 Web 界面，包含实时任务状态、历史记录、待确认任务管理。

---

## GET /ws

**简介**：WebSocket 连接端点，服务端每秒推送一次完整状态，任务状态变化时也会立即推送。

连接成功后立即收到当前状态快照，后续持续接收状态更新。

**消息格式**（服务端 → 客户端，JSON 字符串）：

```json
{
  "current_tasks": {
    "1": {
      "name": "example.zip",
      "kind": "single",
      "status": "extracting",
      "started_at": "2026-04-23T10:00:00.123456",
      "trying_password": "(无密码)"
    }
  },
  "pending": [
    {"id": "0042", "name": "archive.7z.001", "kind": "multipart"}
  ],
  "history": [
    {
      "name": "done.zip",
      "kind": "single",
      "status": "done",
      "out_dir": "/output/done",
      "password": null,
      "error": null,
      "error_detail": null,
      "archives": null,
      "residuals": null,
      "started_at": "2026-04-23T09:58:00.000000",
      "finished_at": "2026-04-23T09:58:01.500000"
    }
  ]
}
```

`history` 最多包含最近 100 条记录（newest last）。

---

## GET /api/state

**简介**：返回与 WebSocket 推送格式完全相同的完整状态快照（一次性 HTTP 拉取）。

### 响应

与 `/ws` 消息格式相同，见上。

### curl 示例

```bash
curl http://localhost:8093/api/state
```

---

## POST /api/confirm/{id}

**简介**：确认一个等待确认的多卷包或文件夹任务，立即开始解压。

### 请求

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `id` | 路径参数 | string | 4 位数字字符串，来自 `/api/pending` 或 WebSocket 的 `pending[].id` |

无请求体。

### 响应

成功：
```json
{"ok": true}
```

失败（ID 不存在）：
```json
{"ok": false, "error": "ID 0042 not found"}
```
HTTP 404

### curl 示例

```bash
curl -X POST http://localhost:8093/api/confirm/0042
```

---

## POST /api/open

**简介**：在服务器桌面上用 `xdg-open` 打开指定路径（文件或目录）。路径必须在 `OUTPUT_PATH` 内。

### 请求体

```json
{"path": "/absolute/path/inside/output"}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 绝对路径，必须在 `OUTPUT_PATH` 内 |

### 响应

成功：
```json
{"ok": true}
```

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| 未提供 path | 400 | `"path required"` |
| 路径不在 OUTPUT_PATH 内 | 403 | `"path not allowed"` |
| 路径不存在 | 404 | `"not found"` |

### curl 示例

```bash
curl -X POST http://localhost:8093/api/open \
  -H "Content-Type: application/json" \
  -d '{"path": "/home/user/output/example"}'
```

---

## GET /api/health

**简介**：服务健康检查，返回当前运行状态和配置摘要。

### 响应

```json
{
  "ok": true,
  "status": "idle",
  "running_tasks": 0,
  "queue_depth": 0,
  "pending_count": 0,
  "watch_path": "/path/to/watch",
  "output_path": "/path/to/output",
  "passwords_count": 2,
  "has_7z": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `"busy" \| "idle"` | 有任何正在运行的任务则为 `busy` |
| `running_tasks` | int | 当前正在运行的任务数 |
| `queue_depth` | int | asyncio.Queue 中等待处理的任务数 |
| `pending_count` | int | 等待用户确认的任务数 |
| `watch_path` | string \| null | 监听目录路径 |
| `output_path` | string \| null | 输出目录路径 |
| `passwords_count` | int | 当前密码列表长度（不暴露实际密码） |
| `has_7z` | bool | 系统是否安装了 `7z` 命令（`p7zip-full`） |

### curl 示例

```bash
curl http://localhost:8093/api/health
```

---

## POST /api/submit

**简介**：直接提交一个本地绝对路径作为解压任务，无需将文件放到 `WATCH_PATH`。适用于外部脚本或 agent 调用。

- **文件夹** 和 **`.7z.001`**（多卷包首卷）→ 进入 pending 等待确认，返回 `pending_id`
- **其他压缩包**（`.zip`、`.rar`、`.7z`）→ 立即开始，返回 `task_started: true`

### 请求体

```json
{"path": "/absolute/path/to/archive_or_folder"}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 绝对路径 |

### 响应

立即开始的任务：
```json
{"ok": true, "task_started": true, "name": "example.zip"}
```

需要确认的任务：
```json
{"ok": true, "pending_id": "0042", "kind": "folder"}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_started` | bool | `true` 表示任务已调度（仅单包） |
| `name` | string | 文件名（仅 task_started 时） |
| `pending_id` | string | 4 位数字，用于 `/api/confirm/{id}` |
| `kind` | `"folder" \| "multipart"` | pending 任务类型 |

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| 未提供 path | 400 | `"path required"` |
| 非绝对路径 | 400 | `"path must be absolute"` |
| 路径不存在 | 404 | `"path does not exist"` |
| 路径在 OUTPUT_PATH 内 | 400 | `"path is inside OUTPUT_PATH — refusing to process output directory"` |
| 无效 JSON | 400 | `"invalid JSON"` |

### curl 示例

```bash
# 提交单个压缩包（立即开始）
curl -X POST http://localhost:8093/api/submit \
  -H "Content-Type: application/json" \
  -d '{"path": "/downloads/archive.zip"}'

# 提交文件夹（需确认）
curl -X POST http://localhost:8093/api/submit \
  -H "Content-Type: application/json" \
  -d '{"path": "/downloads/my_folder"}'
```

---

## GET /api/pending

**简介**：返回当前所有等待用户确认的任务列表（比 `/api/state` 更轻量）。

### 响应

```json
{
  "ok": true,
  "items": [
    {
      "id": "0042",
      "name": "archive.7z.001",
      "kind": "multipart",
      "path": "/downloads/archive.7z.001"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 4 位数字，用于 `/api/confirm/{id}` |
| `name` | string | 文件/文件夹名 |
| `kind` | `"multipart" \| "folder"` | 任务类型 |
| `path` | string | 原始绝对路径 |

### curl 示例

```bash
curl http://localhost:8093/api/pending
```

---

## GET /api/history

**简介**：查询历史记录，支持分页和过滤。结果按时间倒序（最新在前）。

### 请求

Query 参数（均可选）：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | `20` | 返回条数上限，最大 `100` |
| `offset` | int | `0` | 跳过条数（分页用） |
| `status` | string | — | 过滤状态：`done` / `failed` / `partial` / `extracting` |
| `kind` | string | — | 过滤类型：`single` / `multipart` / `folder` |

### 响应

```json
{
  "ok": true,
  "items": [
    {
      "name": "example.zip",
      "kind": "single",
      "status": "done",
      "out_dir": "/output/example",
      "password": null,
      "error": null,
      "error_detail": null,
      "archives": null,
      "residuals": null,
      "started_at": "2026-04-23T10:00:00.000000",
      "finished_at": "2026-04-23T10:00:01.500000"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

文件夹任务的 `archives` 字段：
```json
"archives": [
  {
    "name": "part.zip",
    "status": "done",
    "password": null,
    "error": null,
    "out_subdir": "part"
  }
]
```

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| `limit`/`offset` 非整数 | 400 | `"limit and offset must be integers"` |

### curl 示例

```bash
# 最新 20 条
curl http://localhost:8093/api/history

# 过滤失败任务，第二页
curl "http://localhost:8093/api/history?status=failed&limit=10&offset=10"

# 仅文件夹任务
curl "http://localhost:8093/api/history?kind=folder"
```

---

## DELETE /api/history

**简介**：清理历史记录，立即持久化到 `unzipper_history.json`。

### 请求体（三选一）

**清空全部**：
```json
{"all": true}
```

**删除指定时间之前完成的记录**：
```json
{"before": "2026-04-01T00:00:00"}
```

**按原始数组下标删除**（下标 0 = 最早那条）：
```json
{"indexes": [0, 2, 5]}
```

### 响应

```json
{"ok": true, "deleted": 5}
```

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| 无效 JSON | 400 | `"invalid JSON"` |
| body 中没有已知字段 | 400 | `"body must contain 'all', 'before', or 'indexes'"` |
| `before` 格式不合法 | 400 | `"invalid ISO datetime for 'before'"` |

### curl 示例

```bash
# 清空全部
curl -X DELETE http://localhost:8093/api/history \
  -H "Content-Type: application/json" \
  -d '{"all": true}'

# 删除 2026-04-01 之前的记录
curl -X DELETE http://localhost:8093/api/history \
  -H "Content-Type: application/json" \
  -d '{"before": "2026-04-01T00:00:00"}'
```

---

## GET /api/passwords

**简介**：返回当前密码列表（明文，本地服务无需脱敏）。

### 响应

```json
{"ok": true, "passwords": ["pw1", "pw2"]}
```

### curl 示例

```bash
curl http://localhost:8093/api/passwords
```

---

## POST /api/passwords

**简介**：添加一个新密码到列表末尾，立即生效并持久化到 `.env`。

### 请求体

```json
{"password": "newpassword"}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `password` | string | 是 | 新密码，不能为空 |

### 响应

成功，返回更新后的完整列表：
```json
{"ok": true, "passwords": ["pw1", "pw2", "newpassword"]}
```

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| 未提供 password | 400 | `"password required"` |
| 密码已存在 | 409 | `"password already exists"` |
| 无效 JSON | 400 | `"invalid JSON"` |

### curl 示例

```bash
curl -X POST http://localhost:8093/api/passwords \
  -H "Content-Type: application/json" \
  -d '{"password": "mysecret"}'
```

---

## DELETE /api/passwords

**简介**：从列表中删除一个密码，立即生效并持久化到 `.env`。

### 请求体

```json
{"password": "pw1"}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `password` | string | 是 | 要删除的密码 |

### 响应

成功，返回更新后的完整列表：
```json
{"ok": true, "passwords": ["pw2"]}
```

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| 未提供 password | 400 | `"password required"` |
| 密码不存在 | 404 | `"password not found"` |
| 无效 JSON | 400 | `"invalid JSON"` |

### curl 示例

```bash
curl -X DELETE http://localhost:8093/api/passwords \
  -H "Content-Type: application/json" \
  -d '{"password": "mysecret"}'
```

---

## GET /api/concurrency

**简介**：查询当前并发设置和正在运行的任务数。

### 响应

```json
{
  "ok": true,
  "max_concurrent_tasks": 3,
  "running": 2
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_concurrent_tasks` | int | 当前信号量大小（最大并发数） |
| `running` | int | 当前正在运行的任务数 |

### curl 示例

```bash
curl http://localhost:8093/api/concurrency
```

---

## POST /api/concurrency

**简介**：运行时修改最大并发任务数，立即生效并持久化到 `.env`。已在运行的任务不受影响（持有旧信号量直至完成）。

### 请求体

```json
{"max": 5}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `max` | int | 是 | 新的最大并发数，必须 >= 1 |

### 响应

```json
{"ok": true, "max_concurrent_tasks": 5}
```

错误：

| 情况 | 状态码 | error |
|------|--------|-------|
| `max` 非正整数 | 400 | `"max must be a positive integer"` |
| 无效 JSON | 400 | `"invalid JSON"` |

### curl 示例

```bash
# 设置并发数为 5
curl -X POST http://localhost:8093/api/concurrency \
  -H "Content-Type: application/json" \
  -d '{"max": 5}'

# 降回 1（串行模式）
curl -X POST http://localhost:8093/api/concurrency \
  -H "Content-Type: application/json" \
  -d '{"max": 1}'
```
