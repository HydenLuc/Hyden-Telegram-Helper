# takeout 会话对比实验（#2013）

> 最后更新 2026-11-17 11:30:00
> **状态**：✅ 已做成功能（hyden 2026-11-17 定）：设置项 `HISTORY_TAKEOUT`，默认关，代码 `downloader/history/takeout.py`。实验脚本 `tools/experiments/takeout_compare.py`。

## 结论

| 场景 | takeout 有没有用 | 数据 |
|---|---|---|
| **拉历史消息列表**（`messages.getHistory`，历史下载的扫描阶段） | ✅ **明显有用** | 300 次请求：普通 ≈ 300 秒、限流 9–11 次；takeout ≈ 65 秒、**0 次限流**。快 4.6 倍 |
| **下载文件**（`upload.getFile`） | ❌ **没用** | 2.5 GB：普通 11.5 / 14.7 MB/s，takeout 9.7 / 12.5 MB/s，差距在网络波动以内；两边都在第 155–170 秒开始撞 1–3 秒的小限流，次数差不多 |
| 申请 takeout | 很顺 | 第一次申请就成功，**没遇到 `TakeoutInitDelayError`**，Telegram 也没发「数据导出请求」的服务通知（测试号登录约 3 天）|

**一句话**：takeout 只对「扫历史」有用，对「下文件」没用。TGhelper 的时间大头在下文件上，所以整体收益有限，只有扫大频道（几万条消息）、或者重扫时大部分已经下过要跳过的情况下才明显。

## 对 TGhelper 意味着什么

- 历史下载（`downloader/history/runner.py`）现在用 `client.iter_messages`。Telethon 遇到 ≤`FLOOD_SLEEP_THRESHOLD` 秒的限流会**自己默默等**，所以用户看到的是「扫描慢」，日志里看不出原因。按本次数据，扫 3 万条消息大约 5 分钟 → 1 分钟。
- 下载器不需要改，下载用 takeout 没好处。
- 实时监听（新消息）跟 takeout 无关，不受影响。

### 做成的样子（2026-11-17）

- 只管历史下载的**扫描**：`runner.run_job` 改调 `takeout.scan_messages()`。开关关着时它原样转给 `client.iter_messages()`，参数一个不改（有单测）。
- 没按下面第 1 条自己翻页：借用 Telethon `client.takeout()` 同样的代理思路（client 的方法以代理为 `self` 调用，里面的 `self(request)` 都套上 `InvokeWithTakeoutRequest`），这样 `iter_messages` 的 reverse / min_id / offset_date 语义原样保留。代理是自己写的小类，不继承 Telethon 的私有 `_TakeoutClient`（继承会让它的 `__setattr__` 名字判断失灵、无限递归）。
- **不写 `client.session.takeout_id`**（Telethon 会把它存进 session 文件），id 另记 `STATE_DIR/takeout.json`；下次申请前先关掉上次留下的。实测：另开一个 takeout 会话会让旧的立刻失效（`TakeoutInvalidError: … invalidated by another data export session`），所以全进程只开一个、多个扫描 job 引用计数共用。
- 申请失败 → 冷却 10 分钟（`TakeoutInitDelayError` 按它给的时间）再试，期间直接走普通会话；用到一半失败 → 从最后一条已交出去的消息接着用普通会话扫（reverse 用 `min_id`，否则 `offset_id`），不重不漏。FloodWait 不算 takeout 坏了，照旧抛给 runner 暂停 job。
- takeout 模式下 `iter_messages(wait_time=0)`（普通模式 Telethon 默认每页睡 1 秒）。
- job 完成日志带上会话类型、用时、期间限流次数（数 Telethon「Sleeping for … flood wait」日志）。

**开发环境验收**（测试号，公开频道 Telegram Beta 全量扫描，场景 C 只扫不下，2826 条媒体）：

| 轮次 | 模式 | 每个 job 用时 | 期间限流 |
|---|---|---|---|
| 单跑 | 普通 | 45 秒 | 0 |
| 单跑 | takeout | 13 秒 | 0 |
| 2 轮 × 2 个并发 | takeout | 11–12 秒 | 0 |
| 2 轮 × 2 个并发 | 普通 | 93–94 秒 | 每轮 6 次、共 100 秒 |
| 2 轮 × 2 个并发（对照） | takeout | 13 秒 | 0 |

另实测：`takeout.json` 里放一个失效 id → 先关（报 `TakeoutInvalidError`，记 INFO）→ 正常开新会话扫完 → 记录文件删掉。

### 当初的建议做法（约 0.5–1 天）

1. 只改历史扫描：`iter_messages` 换成自己翻页的 `GetHistoryRequest`，外面包一层 `InvokeWithTakeoutRequest`。
2. 设置项「历史下载用导出通道（takeout）」，默认**关**，放进 #1803 的设置面板，卡片写清下面的注意事项。
3. 申请失败（`TakeoutInitDelayError` 等）或中途出错 → 自动退回普通模式，日志写一句原因。
4. 用完一定 `FinishTakeoutSession`；进程崩了留下的 takeout 会话下次启动时先结束掉。

### 注意事项

- **同一个登录同一时间只能有一个 takeout 会话**。多个历史任务要共用一个，不能各开各的。
- 第一次申请**可能**报 `TakeoutInitDelayError`（Telegram 要求等一段时间，或者在手机上的服务通知里点「允许」）。本次没遇到，但新登录的号很可能会遇到。
- takeout 本意是「导出自己的数据」。tdl 这类工具长期这么用，没见到封号报告，但 Telegram 没有公开承诺；默认关、让用户自己开比较稳。

## 实验方法

- 账号：开发环境测试号（非 Premium），实验期间开发环境停机，用 session **副本**跑，跑完删除副本、恢复开发环境。
- 频道：一个 Telegram 官方公开频道（约 4400 条消息、1300+ 个文件），没有加入，直接按用户名读。
- 所有 FloodWait 都关掉 Telethon 的自动等待（`flood_sleep_threshold=0`），由脚本自己记次数、秒数再等。
- 顺序 ABAB（普通 → takeout → 普通 → takeout），每轮之间冷却 2–3 分钟，避免「后跑的那个吃亏」。
- **历史**：每轮 300 次 `GetHistoryRequest`（每次 100 条，顺序发，到底了从头再翻，凑够 300 次 ≈ 2.9 万条）。
- **下载**：每轮同一批 13 个文件共 2.5 GB（分布在 DC 1/2/4/5，本号在 DC 1），1 MB 分块，16 路并发，只读进内存。takeout 包装在别的 DC 上也能用，没有报错。

## 原始数据

### 历史（300 次请求 / 29454 条）

| 轮 | 模式 | 耗时 | 限流次数 | 限流总等待 | 限流规律 |
|---|---|---|---|---|---|
| 1 | 普通 | 308.5 s | 11 | 210 s | 每 ~30 秒一次，每次 20–25 秒 |
| 2 | takeout | 65.1 s | 0 | 0 | — |
| 3 | 普通 | 297.1 s | 9 | 216 s | 同第 1 轮 |
| 4 | takeout | 66.2 s | 0 | 0 | — |

### 下载（13 个文件 / 2500 MB / 16 并发）

| 轮 | 模式 | 耗时 | 速度 | 限流次数 | 限流总等待 | 第一次限流 |
|---|---|---|---|---|---|---|
| 1 | 普通 | 217.3 s | 11.50 MB/s | 38 | 53 s | 第 171 秒 |
| 2 | takeout | 258.4 s | 9.67 MB/s | 62 | 76 s | 第 156 秒 |
| 3 | 普通 | 170.4 s | 14.67 MB/s | 89 | 110 s | 第 155 秒 |
| 4 | takeout | 200.2 s | 12.49 MB/s | 44 | 56 s | 第 155 秒 |

下载限流都是 1–3 秒的小等待，而且四轮都在开跑约 155 秒后才出现（像是按时间窗口算的流量额度），跟用不用 takeout 无关。
