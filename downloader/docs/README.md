# Downloader 模块

Telegram userbot 下载引擎。监听指定频道/群组，新媒体消息自动入队，自适应分块并发下载，支持暂停/继续/终止，全程 WebSocket 实时进度推送。

---

## 主要功能

- 监听任意频道/群组/私聊，新媒体消息自动入队下载
- 自适应分块并发：按文件大小自动选 1/2/4/6 并行连接（`< 50MB` 用 1 连接，最高 6）
- 全局连接池限流（`asyncio.Condition` 门控，`MAX_TOTAL_CONNECTIONS` 上限）
- FloodWait 指数退避自动重试（最多 3 次，退避 5/10/20s）
- 媒体组聚合（同一相册消息的多文件保存到同一目录）
- 每个下载目录生成 `消息详情.txt`（发送时间、来源、媒体属性等）
- 每个下载任务支持暂停 / 继续 / 终止
- 完整 REST API（16 个端点）+ WebSocket 实时进度推送
- 网页端完成 Telegram 验证码 / 两步验证登录（无需命令行）

---

## 独立启动

```bash
# 仅运行 downloader
python -m downloader.main
```

Web 界面：`http://localhost:8091`（默认，可通过 `WEB_PORT` 配置）

必填 `.env` 变量：

| 变量 | 说明 |
|------|------|
| `API_ID` | Telegram API ID（[my.telegram.org/apps](https://my.telegram.org/apps)） |
| `API_HASH` | Telegram API Hash |
| `PHONE` | 登录手机号（含国际区号，如 `+8613800138000`） |

---

## Telegram 命令

在 Telegram 中以自己的账号发送：

| 命令 | 说明 |
|------|------|
| `监听 <名称或ID>` | 添加监听目标 |
| `取消监听 <名称或ID>` | 移除监听目标 |
| `监听列表` | 列出所有监听目标 |
| `搜索 <关键词>` | 模糊搜索已加入的聊天 |
| `ID` | 查看当前聊天的 ID |

---

## 本模块文档

| 文档 | 说明 |
|------|------|
| [api.md](./api.md) | 所有 16 个 REST 端点的完整参考（请求/响应/curl 示例） |
| [internals.md](./internals.md) | 内部机制：任务状态机、连接门控、分块下载、FloodWait、消息聚合 |
