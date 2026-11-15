# 架构文档

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                          bot.py                             │
│         (合并启动：downloader + unzipper 共享事件循环)        │
└──────────────────┬──────────────────────────┬───────────────┘
                   │                          │
     ┌─────────────▼──────────┐  ┌────────────▼─────────────┐
     │      downloader/       │  │        unzipper/         │
     │  ─────────────────     │  │  ──────────────────────  │
     │  Telethon userbot      │  │  watchdog + 解压引擎      │
     │  分块并发下载           │  │  REST API + WebSocket    │
     │  Web :8091             │  │  Web :8093               │
     └────────────────────────┘  └──────────────────────────┘

                   ┌──────────────────────┐
                   │       mover/         │  ← 独立进程
                   │  ─────────────────   │
                   │  原子文件搬运引擎     │
                   │  暂存目录隔离         │
                   │  Web :8092           │
                   └──────────────────────┘

                   ┌──────────────────────┐
                   │     dashboard/       │  ← 独立进程，监控聚合（只读）
                   │  ─────────────────   │
                   │  /api/overview        │
                   │  代理转发三模块状态    │
                   │  Web :8090            │
                   └──────────────────────┘

各模块独立运行：
  python -m downloader.main   →  仅下载
  python -m mover.main        →  仅搬运
  python -m unzipper.main     →  仅解压
  python -m dashboard.main    →  仅监控面板
```

### 端口分配规则

- 管理/监控类模块（如 dashboard）使用 `8090`
- 数据流模块按数据流先后顺序从 `8091` 起递增分配
- 数据流扩展从 `8094` 开始

| 端口 | 类别 | 模块 | 说明 |
|------|------|------|------|
| `8090` | 管理/监控 | dashboard | 统一监控面板 + 跳转入口 |
| `8091` | 数据流 | downloader | 数据入口，Telegram 下载 |
| `8092` | 数据流 | mover | 中间层，文件原子搬运 |
| `8093` | 数据流 | unzipper | 数据出口，解压处理 |
| `8094+` | 数据流扩展 | 未来 agent | 整理/归档/RAG 索引等 |

---

## Downloader 模块树

```
downloader/
├── main.py               # 独立入口
├── state.py              # 运行时状态（活跃/完成下载、连接计数、auth 状态）
├── storage.py            # 持久化门面：大状态走 SQLite，其余走 JSON 原子写 + .env
├── kvstore.py            # SQLite 键值存储（按 key 增量写，消灭 17.7MB/2s 的写放大）
├── utils.py              # 工具函数（文件名清理、唯一目录/文件名）
├── download/
│   ├── manager.py        # 任务调度、连接门控、FloodWait 重试
│   ├── chunker.py        # 并行分块下载引擎
│   └── progress.py       # 单连接下载进度回调
├── tg/
│   ├── client.py         # Telethon 客户端单例
│   ├── handlers.py       # Telegram 命令 + 媒体事件处理器
│   └── metadata.py       # 消息元信息格式化（消息详情.txt）
└── web/
    ├── server.py         # 16 个 /api/* 端点 + auth middleware
    ├── api.py            # 所有 API handler
    ├── websocket.py      # WebSocket 推送 + 状态构建
    └── templates.py      # 嵌入式前端（HTML/CSS/JS）
```

→ 详细内部机制见 [downloader/docs/internals.md](../downloader/docs/internals.md)

→ REST API 参考见 [downloader/docs/api.md](../downloader/docs/api.md)

---

## Unzipper 模块树

```
unzipper/
├── main.py               # 独立启动入口
├── manager.py            # 任务调度、并发控制、队列 worker
├── watcher.py            # watchdog 文件系统监听（在线程中运行）
├── extractor.py          # 解压引擎（zip/rar/7z/多卷），密码重试
├── utils.py              # 工具函数（命名冲突、扫描、错误分类）
├── storage.py            # 持久化（history JSON + .env 写入）
├── state.py              # 全局运行时状态（模块级变量）
└── web/
    ├── server.py         # 13 个 /api/* 端点
    ├── api.py            # 所有 API handler
    ├── websocket.py      # WebSocket 实时推送 + 1s 广播循环
    └── templates.py      # 嵌入式前端（HTML/CSS/JS）
```

→ 详细内部机制见 [unzipper/docs/internals.md](../unzipper/docs/internals.md)

→ REST API 参考见 [unzipper/docs/api.md](../unzipper/docs/api.md)

---

## Mover 模块树

```
mover/
├── main.py               # 独立启动入口
├── state.py              # 运行时状态（tasks dict、broadcast callback）
├── manager.py            # 任务调度、原子搬运、并发控制
├── storage.py            # JSON 持久化（mover_state.json，原子写）
├── utils.py              # 工具函数（staging 目录名、跨 FS 检测、唯一命名）
└── web/
    ├── server.py         # 9 个路由注册
    ├── api.py            # 所有 API handler
    ├── websocket.py      # WebSocket 推送 + 1s 广播循环
    └── templates.py      # 嵌入式前端（已实现，P1-9）
```

→ 详细内部机制见 [mover/docs/internals.md](../mover/docs/internals.md)

→ REST API 参考见 [mover/docs/api.md](../mover/docs/api.md)

---

## Dashboard 模块树

```
dashboard/
├── __init__.py          # 空，使 dashboard 成为包
├── main.py              # 启动入口、GET / 和 GET /api/overview handler
└── templates.py         # 嵌入式前端（HTML/CSS/JS，单页面）
```

设计要点：

- 后端代理（`GET /api/overview`）并发拉取三模块 API，**浏览器只调 dashboard 同源接口**，避开 CORS
- 失败计数器：连续 2 次失败标 `online=false`，1 次成功立即恢复
- 不需要 API_KEY 认证（dashboard 自身不暴露敏感操作；后端代理调三模块时携带 `config.API_KEY`）
- 前端纯轮询（5s 间隔）+ `window.location.hostname` 派生跳转 URL（外网/手机访问 OK）
- 数据源：downloader `/api/status`、mover `/api/health`、unzipper `/api/state`
- 每模块超时独立 3 秒，单模块挂不影响其他卡片显示

---

## 模块依赖关系

```
bot.py / main.py
    │
    ├── config.py                     (所有模块都读)
    │
    ├── downloader/
    │       ├── state.py
    │       ├── storage.py
    │       ├── tg/client.py          (Telethon 单例)
    │       ├── tg/handlers.py        (注册事件处理器)
    │       ├── download/manager.py   (download_one 协程)
    │       └── web/server.py + api.py + websocket.py
    │
    ├── mover/                        (独立进程，不在 bot.py 内)
    │       ├── state.py
    │       ├── storage.py
    │       ├── manager.py            (submit / retry / list_tasks)
    │       └── web/server.py + api.py + websocket.py
    │
    ├── unzipper/
    │       ├── state.py
    │       ├── storage.py
    │       ├── manager.py            (start / submit / confirm_pending)
    │       │       ├── extractor.py
    │       │       ├── utils.py
    │       │       ├── storage.py
    │       │       └── watcher.py
    │       └── web/server.py + api.py + websocket.py
    │
    └── dashboard/                    (独立进程，只读聚合)
            └── main.py                (HTTP client → 三模块 /api/*，无内部状态)

广播回调注入（打破循环依赖）：
  unzipper: main.py 调用 manager.set_broadcast_callback(_broadcast)
  downloader: handlers.py 和 api.py 在函数体内延迟导入 download_one（暂时方案）
  mover: main.py 调用 state.set_broadcast_callback(_broadcast)
```

---

## 模块间交互

三个模块通过 HTTP API 协作（见 [docs/integration.md](integration.md)）：

```
downloader._finish()
    │  检测到压缩包扩展名
    │  POST http://localhost:{MOVER_PORT}/api/move
    │  {"source": "/downloads/x.zip", "target": "/watch/x.zip"}
    ▼
mover.manager.submit(source, target)
    │  两步原子搬运：
    │    1. 创建 .mover_staging_<uuid>/（watchdog 不可见）
    │    2. os.rename → /watch/x.zip（watchdog 仅看到完整文件的 rename 事件）
    ▼
文件系统（watchdog 检测到 /watch/x.zip）
    ▼
unzipper.manager.submit(path)
    ▼
解压流程（见 unzipper/docs/internals.md）
```

dashboard 不在数据流上，只做监控聚合：

```
浏览器 → http://localhost:8090/api/overview                      (同源调用)
            │
            ▼
        dashboard 后端
            │  asyncio.gather 并发拉取，每个超时独立 3s：
            ▼
        ┌── http://127.0.0.1:{WEB_PORT}/api/status        (X-API-Key)
        ├── http://127.0.0.1:{MOVER_PORT}/api/health      (X-API-Key)
        └── http://127.0.0.1:{UNZIPPER_PORT}/api/state    (X-API-Key)
            │
            ▼
        聚合 JSON 返回给浏览器
```

### ⚠️ 跨进程拉状态：别做「半吊子瘦身」（2026-08-13 事故）

上面那张图里 dashboard 拉 downloader 的 `/api/status` —— **那是全量状态**，含
`active` + `completed` 两个完整列表。队列达到数万条时序列化出 **4.9MB**（历史峰值 22MB），
downloader 事件循环忙的时候要几十秒。

当时给 dashboard 加了 `/api/overview?slim=1` 想解决这个，**但只裁剪了 dashboard
发给浏览器的那一段** —— 它向 downloader 拉的仍是全量。前端看着变小了，
**真正的瓶颈（上游那一跳）一点没动**。结果：

```
downloader 超时 → dashboard 返回 "data": null
   → 网页频道页 HTTP 504、空白
   → 客户端 App 崩溃（JsonNull 解析异常）
```

**正确做法：瘦身要下沉到数据产生的那一端**。`/api/status?slim=1` 让 downloader
在源头就不序列化大列表，实测 **4,912,486 → 18,611 字节（264 倍）**。

**通用教训**：优化「A 调 B 再返回给 C」的链路时，先确认瓶颈在 A→B 还是 B→C。
只优化能看见的那一段（B→C），很容易自我感觉良好而问题原封不动。

### ⚠️ 消费端：JSON 的 `null` 不等于宿主语言的 null

`_fetch_module` 拿不到模块时返回 `{"online": …, "data": None}` —— 这是**正常降级**，
不是异常。消费方必须能处理 `data` 为 null：

- **Kotlin（作者自用的安卓客户端，没有随本仓库发布；写第三方客户端时同样适用）**：`kotlinx.serialization` 把 JSON 的 null 解析成 **`JsonNull` 对象**，
  它**不是 Kotlin 的 null**，所以 `?.` 不会短路，`?.jsonObject` 直接抛
  `JsonNull is not a JsonObject` 把整页打崩。**一律用 `as? JsonObject`。**
- **JS（网页）**：`(s && s.watched) || {}` 这种写法天然安全。
- ⚠️ **但别在拿不到数据时编造默认值**：App 曾在 data 为 null 时返回空 ChannelState，
  界面显示成「0 个频道 · 全局暂停:关 · 全都在收」，而真实状态是两个暂停都开着。
  **显示错误状态比显示不出来更危险**——该抛异常走错误提示。
