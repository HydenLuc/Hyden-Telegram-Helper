# Unzipper 模块

文件系统监听 + 自动解压服务。watchdog 检测新文件，自动完成格式识别、密码重试、并发控制、失败处理，全程无需干预。

---

## 主要功能

- watchdog 监听 `WATCH_PATH`，新文件/文件夹写入完成后自动入队
- 支持 `.zip` / `.rar` / `.7z` / `.7z.001`（多卷）
- 密码自动重试（顺序尝试 `PASSWORDS` 列表，无密码优先尝试避免假阳性）
- `asyncio.Semaphore` 控制最大并发解压数（默认 3，运行时可调）
- 失败任务移入 `@任务失败/` 并写 `任务失败.txt`
- 历史记录持久化到 `unzipper_history.json`（最多 100 条）
- 完整 REST API（15 个端点）+ WebSocket 实时状态推送
- 密码和并发数可运行时修改并持久化到 `.env`

---

## 独立启动

```bash
# 仅运行 unzipper
python -m unzipper.main
```

Web 界面：`http://localhost:8093`（默认，可通过 `UNZIPPER_PORT` 配置）

必填 `.env` 变量：

| 变量 | 说明 |
|------|------|
| `WATCH_PATH` | watchdog 监听目录 |
| `OUTPUT_PATH` | 解压输出根目录 |

---

## 本模块文档

| 文档 | 说明 |
|------|------|
| [api.md](./api.md) | 所有 15 个 REST 端点的完整参考（请求/响应/curl 示例） |
| [internals.md](./internals.md) | 内部机制：数据流、并发模型、状态机、全局状态表 |
| [agent-integration.md](./agent-integration.md) | AI Agent 调用指南：工作流示例、WebSocket 订阅、错误处理 |
| [testing.md](./testing.md) | 测试覆盖矩阵和可复现测试脚本 |
