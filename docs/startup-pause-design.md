# 启动时默认暂停监听设计

> **状态**：✅ 已实现

## 目标

`bot.py` 启动完成后，`state.monitoring_paused = True`。用户必须在 Web UI 主动点「恢复监听」才会开始接受新的 Telegram 媒体消息。

## 动机

- 远程部署时不希望"系统刚启动就一股脑冲进来一堆未审视的消息"
- 软暂停语义已经成熟（`docs/pause-design.md` + `P1-5a Q4`），UI 与 API 都齐全
- 仅缺一个"启动默认值"的开关

## 改动范围

### 唯一改动文件：`bot.py`

⚠️ **2026-08-19 更正：赋值位置必须在 `client.start()` 之前，本文原来写的是之后，那是错的。**

```python
# ⚠️ 这三行必须在 client.start() 之前
state.bot_start_time = datetime.now(timezone.utc)
state.monitoring_paused = True
state.exempt_paused = True

await client.start(phone=config.PHONE)
me = await client.get_me()
print(f"Userbot 已启动：{me.first_name} (@{me.username})")
# ... 配置 banner ...
_log.info("启动默认全部暂停（全局 + 例外），请在 Web UI 点击恢复开始接收新媒体")

# P1-5b: 启动恢复扫描（不受暂停影响，照常恢复未完成任务）
from downloader.download.manager import recover_pending_tasks
await recover_pending_tasks()
```

#### 为什么位置这么要紧

`client.start()` 一返回，Telethon 就开始派发更新（**包括离线期间的积压**）。
按本文原来的写法，三个状态都在那之后才赋值，中间还夹着一次 `await client.get_me()`
网络往返 —— 那个窗口里：

- `bot_start_time` 还是 `None` → `handle_media` 里 `event.message.date < None`
  抛 `TypeError`。Telethon 只打一条「Unhandled exception on handle_media」就继续，
  **那条消息被静默丢掉**，不进队列也没有任何提示。2026-08-19 凌晨实际发生过一次
- 两个暂停开关还是 `False` → 积压媒体会被**真的开下**，
  「启动默认暂停」的保证就是空话（正是 2026-08-06 队列涨到 1800+ 的成因）

`handlers.py` 里另加了 `bot_start_time is None` 的兜底，防止将来有人再挪回去 ——
那种失败是静默丢消息，极难发现。

### `downloader/main.py`

它是开发用的独立入口，**不是日常使用入口**（`python bot.py` 才是），
且**缺「启动默认暂停」**——换过去会导致每次重启立刻开下。

2026-08-19 只把 `bot_start_time` 的位置同步修了（那是纯 bug，两个入口都有）；
两个暂停开关仍然只在 `bot.py` 里置位，维持原状。

## 关键边界确认

### 暂停只拦新消息，不影响其他流程

`state.monitoring_paused` 的语义现已固定，只在以下位置生效：

- `tg/handlers.py:142` `handle_media` 入口的 `if state.monitoring_paused: return`

**不影响**：
- `recover_pending_tasks()`（启动恢复扫描）— 照常跑，把进程崩溃前未完成的下载续起来
- 已经在 `active_downloads` 中的任务 — 继续跑完
- 用户主动调 `/api/download` — 仍可以手动触发下载某条消息（绕过监听门）
- mover、unzipper 模块 — 完全独立，不受影响

这一行为符合用户决策（5.2: "recover 照跑，暂停只拦新消息"）。

### 暂停期间 Telegram 推送的消息会被丢弃

`handle_media` 在 `monitoring_paused = True` 时直接 return，**不入队、不持久化**。等用户点恢复后，这些消息已被永久跳过。

这是 P1-5a Q4 设计的预期行为（"暂停期间消息丢弃"，详见 `docs/pause-design.md`）。如未来要改成"暂停期间排队等恢复"，是另一个 spec 范畴。

### 恢复后的 bot_start_time 语义

`bot_start_time` 在 `client.start()` 之后立即设为当前时间（`bot.py:51`）。`handle_media` 用它过滤掉历史消息（`handlers.py:145`）。

启动 → 默认暂停 → 用户 1 小时后才点恢复，期间 Telegram 收到的消息：

- Telethon 在连接后会通过 `getDifference` 推送积压的入站消息
- `handle_media` 检查 `event.message.date < state.bot_start_time` → True（消息时间在 bot 启动之前？不，消息是 bot 启动后到达的）→ 不被这条 gate 拦
- 但被 `monitoring_paused` 拦下 → return

恢复后 Telethon 不会回放已经"消费"过的消息，所以暂停期间消息确实丢失。**这是已知行为，不是 bug**。

## 前端无改动

UI 已有：
- `<button id="pause-btn">⏸ 暂停监听 / ▶ 恢复监听</button>`（`templates.py:222`）
- `paused` 字段在 WS payload 与 `/api/status` 都返回（`websocket.py:20` / `api.py:278`）
- bot 状态条会显示「⏸ 监听暂停中」（`templates.py:364-368`）

启动后页面打开 → 按钮自动显示「▶ 恢复监听」+ 黄色高亮，符合预期。

## API 无改动

`POST /api/pause` / `POST /api/resume` 已存在（`api.py` 中 `_api_pause` / `_api_resume`）。用户点恢复按钮即调 `/api/resume`，把 `state.monitoring_paused = False`。

## 验收

- `python bot.py` 启动 → 终端日志看到「启动默认暂停监听...」
- 打开 `http://localhost:8091` → 顶部状态条显示「⏸ 监听暂停中」
- 点「▶ 恢复监听」→ 状态条变绿/黄正常状态
- 监听的频道发新消息 → 暂停期间不下载，恢复后才会下载
- 重启 bot → 又默认暂停（不持久化恢复状态）
- 启动时如有 `pending_tasks.json` 中未完成任务 → 仍自动恢复并下载（不受暂停影响）
