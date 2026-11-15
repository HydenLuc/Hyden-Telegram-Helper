# Mover 模块


搬运协调层。接收 downloader 的指令，将已完成下载的文件原子性搬运到 unzipper 的监听目录，解决下载写入过程中触发提前解压的竞态问题。

---

## 解决的核心问题

**没有 mover 时的问题**：

downloader 下载文件时，unzipper 的 watchdog 可能在文件写入完成之前就检测到并尝试解压，导致解压残缺文件或失败。即便加上 watchdog 的稳定性等待，多文件消息组（相册/打包系列）也无法保证"全部到位再触发"。

**用 mover 后的流程**：

```
Telegram 消息 → downloader 下载到隔离目录
                       ↓（整组消息全部完成）
               POST /api/move  →  mover
                       ↓ 原子搬运
             .mover_staging_<uuid>/  （隐藏，watchdog 不触发）
                       ↓ 全部成功后 rename
               unzipper WATCH_PATH/正式目录名
                       ↓
          unzipper watchdog 检测到完整文件 → 触发解压
```

watchdog 永远只看到 rename 后的完整文件，不会看到写入中间态。

---

## 主要功能

- 接收 HTTP `POST /api/move` 指令，异步执行搬运，**立即返回** `task_id`
- 两步原子移动：先复制到隐藏 `.mover_staging_<uuid>/`，全部成功后一次 `rename` 到正式目录名
- 跨文件系统自动切换为 `shutil.copytree` + 验证 + 删源文件
- 基于 `task_id` 的**幂等性**：同一 `task_id` 在 `done` 状态下不重复搬运
- **全部或无**（All-or-nothing）：任何子文件失败 → 回滚整个 staging 目录 → 任务标记 `failed`
- `asyncio.Semaphore` 控制并发搬运数（`MOVER_MAX_CONCURRENT`，默认 3）
- 任务状态持久化到 `mover_state.json`，重启后自动恢复
- 启动时扫描并清理孤儿 `.mover_staging_*` 临时目录
- WebSocket 实时推送任务状态变化（`pending` / `copying` / `done` / `failed`）
- 极简 Web 状态页（只读，最近任务列表 + 失败任务重试按钮）
- **要求 unzipper 侧配合**：过滤 `.` 开头的隐藏目录，避免监听到 staging 临时目录

---

## 独立启动

```bash
python -m mover.main
```

Web 界面：`http://localhost:8092`（默认，可通过 `MOVER_PORT` 配置）

mover 不依赖 Telegram，所有路径由调用方传入，可完全独立运行。

**可选 `.env` 变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MOVER_PORT` | `8092` | Web 界面及 API 端口 |
| `MOVER_MAX_CONCURRENT` | `3` | 最大并发搬运任务数（`asyncio.Semaphore` 大小） |

---

## 与其他模块的交互

```
                     POST /api/move
downloader ──────────────────────────▶ mover
     ◀── WebSocket event (done/failed) ──┘
                                         │  shutil.move / os.rename
                                         ▼
                                    文件系统
                                    (WATCH_PATH)
                                         │
                                    watchdog 检测
                                         ▼
                                      unzipper
```

- mover **不调用** unzipper 的 API，只通过文件系统移动间接触发 watchdog
- downloader 调用 `POST /api/move` 后，订阅 WebSocket 等待对应 `task_id` 的 `done`/`failed` 事件
- 消息组聚合（多条消息归属同一 `task_id`）是 **downloader 的职责**，mover 只接受搬运指令

---

## 本模块文档

| 文档 | 说明 |
|------|------|
| [api.md](./api.md) | 所有 9 个 REST 端点完整参考（请求/响应/curl 示例） |
| [internals.md](./internals.md) | 状态机、原子移动原理、幂等性、持久化 schema、失败恢复 |
| [testing.md](./testing.md) | 测试场景清单 |
