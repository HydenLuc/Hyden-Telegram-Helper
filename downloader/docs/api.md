# Downloader API 参考手册

## 基本信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://localhost:8091`（由 `WEB_PORT` 配置） |
| 认证 | 可选 API Key（`X-API-Key: <key>` header，`API_KEY` 为空时不验证） |
| 请求体格式 | `Content-Type: application/json` |
| 响应格式 | 操作类端点：成功 `{"ok": true}`，失败 `{"ok": false, "error": "..."}`；查询类端点（`/api/search`、`/api/status`、`/api/state`、`GET /api/settings`）直接返回数据对象；认证失败统一返回 `{"error": "Unauthorized"}`（无 `ok` 字段），详见下方说明 |

**API Key 认证**：当 `.env` 中 `API_KEY` 非空时，所有 `/api/*` 路径须携带 `X-API-Key: <key>` header；`/` 和 `/ws` 路径不受限制。认证失败返回 `HTTP 401`，响应体为 `{"error": "Unauthorized"}`（**不含** `ok` 字段，与其他端点的错误格式不同）。

---

## GET /

返回 Web 监控界面 HTML。

---

## GET /ws

WebSocket 连接端点。连接后立即推送完整状态，之后每 500ms 广播一次。

### 推送数据结构

```json
{
  "active": [
    {
      "task_id":    "1234567890_12345",
      "label":      "源频道/20260423_123456_文件名",
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
      "chunks":     [{"id":0,"current":26214400,"total":52428800,"pct":50,"speed":1048576.0}],
      "flood_until": null,
      "n_conns":    2
    }
  ],
  "completed":     [...],
  "watched":       {"chat_id": "源频道名"},
  "auth":          "idle | waiting_code | waiting_password",
  "total_speed":   2097152.0,
  "active_conns":  2,
  "waiting_count": 0,
  "settings": {
    "max_total_connections": 20,
    "chunk_size": 1048576
  }
}
```

**`status` 枚举**：`waiting` / `downloading` / `paused` / `flood_wait` / `cancelling` / `done` / `error` / `timeout`

---

## GET /api/state

返回当前完整状态（与 WebSocket 推送内容相同）。

### curl 示例

```bash
curl http://localhost:8091/api/state | jq
```

---

## GET /api/status

返回简化状态（当前活跃、已完成、监听列表、总速度）。

### 响应

```json
{
  "active":      [...],
  "completed":   [...],
  "watched":     {"chat_id": "名称"},
  "total_speed": 0.0
}
```

---

## GET /api/search

搜索已加入的 Telegram 聊天（需已登录）。

### 请求

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `q` | query | string | 是 | 关键词（不区分大小写，最多返回 30 条） |

### 响应

```json
[
  {"name": "频道名称", "id": -1001234567890}
]
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 403 | 未登录 |

### curl 示例

```bash
curl "http://localhost:8091/api/search?q=关键词"
```

---

## POST /api/watch

添加监听目标（持久化到 `watched_chats.json`）。

### 请求体

```json
{"id": -1001234567890, "name": "频道名称"}
```

### 响应

```json
{"ok": true}
```

### curl 示例

```bash
curl -X POST http://localhost:8091/api/watch \
  -H "Content-Type: application/json" \
  -d '{"id": -1001234567890, "name": "我的频道"}'
```

---

## DELETE /api/watch/{chat_id}

移除监听目标。

### 路径参数

| 参数 | 说明 |
|------|------|
| `chat_id` | 聊天 ID（字符串形式） |

### 响应

```json
{"ok": true}
```

### 错误

| 状态码 | 响应体 | 说明 |
|--------|--------|------|
| 404 | `{"ok": false}` | 未找到该 chat_id（**注意：无 `error` 字段**） |

### curl 示例

```bash
curl -X DELETE "http://localhost:8091/api/watch/-1001234567890"
```

---

## POST /api/auth

提交 Telegram 登录验证码或两步验证密码（由网页登录界面调用）。

### 请求体

```json
{"value": "12345"}
```

### 响应

```json
{"ok": true}
```

### 错误

| 状态码 | 响应体 | 说明 |
|--------|--------|------|
| 400 | `{"ok": false, "error": "no auth pending"}` | 当前无等待的 auth 请求 |

---

## POST /api/download

通过 chat_id + message_id 手动触发下载一条消息的媒体文件。

### 请求体

```json
{"chat_id": -1001234567890, "message_id": 12345}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chat_id` | int | 是 | 聊天 ID |
| `message_id` | int | 是 | 消息 ID |

### 响应

```json
{
  "ok":       true,
  "task_id":  "-1001234567890_12345_api1745000000",
  "filename": "video.mp4",
  "save_dir": "/downloads/频道名/20260423_123456_文件名"
}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 400 | 缺少 chat_id 或 message_id |
| 404 | 消息不存在或无媒体内容 |
| 500 | 获取消息失败 |

### curl 示例

```bash
curl -X POST http://localhost:8091/api/download \
  -H "Content-Type: application/json" \
  -d '{"chat_id": -1001234567890, "message_id": 12345}'
```

---

## POST /api/retry

重试一条已完成（失败）的下载记录。会从 `completed_downloads` 中移除原记录，重新创建下载任务。

### 请求体

```json
{"task_id": "1234567890_12345"}
```

### 响应

```json
{"ok": true, "task_id": "1234567890_12345_r1745000000"}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 400 | 缺少 task_id，或记录缺少 chat_id/message_id |
| 404 | 记录不存在，或消息已无媒体 |
| 500 | 获取消息失败 |

### curl 示例

```bash
curl -X POST http://localhost:8091/api/retry \
  -H "Content-Type: application/json" \
  -d '{"task_id": "1234567890_12345"}'
```

---

## POST /api/open

用 `xdg-open` 打开文件或目录（仅限 `DOWNLOAD_DIR` 内的路径）。

### 请求体

```json
{"path": "/downloads/频道名/20260423_123456_文件名"}
```

### 响应

```json
{"ok": true}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 400 | 未提供 path |
| 403 | 路径不在 DOWNLOAD_DIR 内 |
| 404 | 路径不存在 |

### curl 示例

```bash
curl -X POST http://localhost:8091/api/open \
  -H "Content-Type: application/json" \
  -d '{"path": "/downloads/频道名/20260423_123456_文件名"}'
```

---

## POST /api/completed/clear

清空所有已完成记录（不删除本地文件）。

### 响应

```json
{"ok": true}
```

### curl 示例

```bash
curl -X POST http://localhost:8091/api/completed/clear
```

---

## DELETE /api/completed/{task_id}

删除单条已完成记录（不删除本地文件）。

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
| 404 | 记录不存在 |

---

## GET /api/settings

获取当前运行时设置。

### 响应

```json
{
  "max_total_connections": 20,
  "chunk_size": 1048576
}
```

---

## POST /api/settings

修改运行时设置（立即生效并持久化到 `.env`）。

### 请求体

```json
{
  "max_total_connections": 20,
  "chunk_size": 524288
}
```

| 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|
| `max_total_connections` | int | 1–64 | 全局最大 HTTP 连接数 |
| `chunk_size` | int | 4096–1048576 | 分块大小（字节），自动向下对齐到 4096 的倍数 |

### 响应

```json
{"ok": true, "max_total_connections": 20, "chunk_size": 524288}
```

### curl 示例

```bash
# 调低并发连接数
curl -X POST http://localhost:8091/api/settings \
  -H "Content-Type: application/json" \
  -d '{"max_total_connections": 10}'

# 调小分块大小（弱网环境）
curl -X POST http://localhost:8091/api/settings \
  -H "Content-Type: application/json" \
  -d '{"chunk_size": 262144}'
```

---

## POST /api/task/{task_id}/pause

暂停正在下载的任务（仅分块下载任务支持，单连接小文件不支持）。

### 路径参数

| 参数 | 说明 |
|------|------|
| `task_id` | 活跃任务 ID |

### 响应

```json
{"ok": true}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 400 | 该任务不支持暂停（单连接小文件）|
| 404 | 任务不存在 |

### curl 示例

```bash
curl -X POST "http://localhost:8091/api/task/1234567890_12345/pause"
```

---

## POST /api/task/{task_id}/resume

恢复已暂停的任务。

### 响应

```json
{"ok": true}
```

### 错误

同 `/pause`。

### curl 示例

```bash
curl -X POST "http://localhost:8091/api/task/1234567890_12345/resume"
```

---

## POST /api/task/{task_id}/cancel

取消正在进行的任务（`waiting` / `downloading` / `paused` / `flood_wait` 均可）。

取消后任务移入 `completed_downloads`，`status` 为 `error`，`error_msg` 为 `"已手动取消"`。已下载的临时分块文件自动清理，原目录不删除。

### 响应

```json
{"ok": true}
```

### 错误

| 状态码 | 说明 |
|--------|------|
| 404 | 任务不存在或已完成 |

### curl 示例

```bash
curl -X POST "http://localhost:8091/api/task/1234567890_12345/cancel"
```
