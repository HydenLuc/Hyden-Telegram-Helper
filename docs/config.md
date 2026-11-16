# 配置参考

所有配置通过项目根目录的 `.env` 文件设置。

```bash
cp .env.example .env
# 编辑 .env，填入必填项
```

启动时 `config.py` 调用 `load_dotenv()` 自动加载。

---

## Downloader 相关

| 变量名 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `API_ID` | — | **是** | Telegram API ID，从 [my.telegram.org/apps](https://my.telegram.org/apps) 获取 |
| `API_HASH` | — | **是** | Telegram API Hash，同上 |
| `PHONE` | — | **是** | 登录手机号，含国际区号，如 `+8613800138000` |
| `DOWNLOAD_DIR` | `./downloads` | 否 | 媒体文件下载根目录 |
| `WEB_PORT` | `8091` | 否 | Downloader Web 界面端口 |
| `API_KEY` | `""` | 否 | Downloader API 认证密钥（为空则不验证） |
| `DOWNLOAD_TIMEOUT` | `180` | 否 | 连续多少秒零进度就判卡死、取消。🔴 **别设回 60**：Telethon 的 `flood_sleep_threshold` 默认也是 60，它遇到 ≤60s 的 FloodWait 会自己 sleep 重试（零进度），两个 60 撞车 → 大文件被限流就误杀（2026-09-17 查明，363 次超时几乎全是 2.5~3.5GB 文件）。必须 ≥ 2×`FLOOD_SLEEP_THRESHOLD` |
| `FLOOD_SLEEP_THRESHOLD` | `60` | 否 | 交给 Telethon 内部 sleep 重试的 FloodWait 上限（秒）。超过就抛给我们自己处理（会设 `flood_until` 让看门狗豁免）。⚠️ 必须**明显小于** `DOWNLOAD_TIMEOUT` |
| `DOWNLOAD_START_INTERVAL` | `0` | 否 | 防封号：全局两次「开始下载一个新文件」之间至少间隔多少秒（浮点，0 = 关闭，负数按 0）。实时下载和历史下载共用；断点续传 / 重试同一任务也走它。等待发生在拿连接**之前**，不占连接预算，也不会被卡死看门狗误判 |
| `DOWNLOAD_START_JITTER` | `0` | 否 | 在上面的间隔上再随机加 0~N 秒（浮点，负数按 0）。`DOWNLOAD_START_INTERVAL=0` 时整个节流关闭，本项不起作用 |
| `MAX_TOTAL_CONNECTIONS` | `20` | 否 | 全局最大并发 HTTP 连接数 |
| `CHUNK_SIZE` | `1048576` | 否 | 分块下载每块大小（字节），必须是 4096 的倍数，上限 1048576（1 MB） |
| `SMALL_FILE_THRESHOLD_MB` | `5` | 否 | 低于此 MB 阈值的文件视为"小文件"，可用全部连接（连接分级调度）|
| `SMALL_FILE_RESERVED_CONNECTIONS` | `3` | 否 | 始终为小文件硬预留的连接数；大文件最多用 `MAX_TOTAL_CONNECTIONS - 此值` |
| `RECOVER_WORKERS` | `8` | 否 | 启动恢复扫描的并发度。⚠️ **别去掉这个池子**：原来是给每个待恢复任务各建一个协程，数万个协程堵在同一个 `asyncio.Condition` 上，`notify_all()` 的代价是 O(等待者)，光调度就吃满 CPU |
| `DISABLE_CHUNKED` | `0` | 否 | 设 `1` 退回单连接下载。**排查用的应急开关**，怀疑分块逻辑有问题时一键对照，平时别开（会明显变慢）|
| `STALLED_RETRY_INTERVAL` | `1800` | 否 | 搁置任务（在 pending 但没人在下）多久重试一轮（秒）。恢复扫描只在启动跑一次，没这个循环失败任务就永远躺着（2026-09-17）。退避 = 间隔×2^重试次数，封顶 24h |
| `STALLED_RETRY_BATCH` | `3` | 否 | 每轮最多重新发起几个搁置任务。别调太大，失败任务会占连接预算挤掉正常下载 |

---

## Unzipper 相关

| 变量名 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `WATCH_PATH` | — | **是**（unzipper）| watchdog 监听目录，新文件/文件夹会被自动检测 |
| `OUTPUT_PATH` | — | **是**（unzipper）| 解压输出根目录 |
| `PASSWORDS` | `""` | 否 | 解压密码列表，逗号分隔，如 `pw1,pw2,pw3`；列表顺序即尝试顺序；如果有无密码包，会优先尝试无密码以避免假阳性 |
| `UNZIPPER_PORT` | `8093` | 否 | Unzipper Web 界面及 API 端口 |
| `MAX_CONCURRENT_TASKS` | `3` | 否 | 最大并发解压任务数（`asyncio.Semaphore` 大小） |

---

## ⚠️ 路径必须互不重叠（重要）

`DOWNLOAD_DIR` / `WATCH_PATH` / `OUTPUT_PATH` 三个目录**必须互不重叠**，包括"父子嵌套"也算重叠。否则会触发以下问题：

- 下载中的临时文件被 unzipper watchdog 误检测，触发不完整文件的解压
- 解压输出落到 watch 目录，引发递归解压
- mover 搬运后立即又被 unzipper 处理，绕过 mover 的原子隔离

推荐配置示例：

```dotenv
DOWNLOAD_DIR=./downloads
WATCH_PATH=./watch
OUTPUT_PATH=./extracted
```

---

## ⚠️ 网络监听与认证（公网部署必读）

| 变量名 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `LISTEN_HOST` | `127.0.0.1` | 否 | 三模块 Web/API 监听地址；默认仅本机访问；**公网部署必须改为 `0.0.0.0`，且必须先设 `API_KEY`** |
| `API_KEY` | `""` | 否（公网部署强烈建议） | 三模块共享的鉴权密钥；为空时禁用鉴权（向下兼容）；非空时所有 `/api/*` 请求需带 `X-API-Key` header |

**安全行为**：

- `API_KEY=""`（默认）→ middleware 放行所有请求（仅适合本机使用）
- `API_KEY` 非空 → `/api/*` 路径要求 `X-API-Key` header 与之匹配，不匹配返回 `401 Unauthorized`
- `/`（HTML 页面）和 `/ws`（WebSocket）**不受 API_KEY 保护**，但 HTML 页内的 fetch 调用会自动注入 key
- `LISTEN_HOST=0.0.0.0` 但 `API_KEY=""` = mover/unzipper 暴露任意文件读写能力给所有网络访问者，**严重不安全**

**公网部署建议清单**：见 `docs/deployment.md` 的"公网部署安全清单"章节。

---

## Mover 相关

| 变量名 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `MOVER_PORT` | `8092` | 否 | Mover Web 界面及 API 端口 |
| `MOVER_MAX_CONCURRENT` | `3` | 否 | 最大并发搬运任务数（`asyncio.Semaphore` 大小） |
| `AUTO_MOVE` | `true` | 否 | 下载完成后是否自动通过 mover 触发搬运，`true`/`false` |
| `MOVER_MAX_HISTORY` | `500` | 否 | mover_state.json 中 `done`/`failed` 任务的保留上限（按 `completed_at` 倒序）；`pending`/`copying` 永不裁剪 |

---

## 运行时可变配置

以下配置可在服务**运行时**通过 API 修改，修改立即生效并回写到 `.env`，重启后仍然有效。

| 变量 | 修改 API | 查询 API | 模块 |
|------|----------|----------|------|
| `PASSWORDS` | `POST /api/passwords`（添加）<br>`DELETE /api/passwords`（删除） | `GET /api/passwords` | unzipper |
| `MAX_CONCURRENT_TASKS` | `POST /api/concurrency` `{"max": N}` | `GET /api/concurrency` | unzipper |
| `max_total_connections` | `POST /api/settings` `{"max_total_connections": N}`，范围 1–64 | `GET /api/settings` | downloader |
| `chunk_size` | `POST /api/settings` `{"chunk_size": N}`，自动向下对齐 4096 倍数，范围 4096–1048576 | `GET /api/settings` | downloader |

运行时状态分别保存在各模块的 `state.py` 模块级变量中，启动时从 `config` 读取初始值；修改后立即生效并回写 `.env`。

---

## 完整 `.env` 示例

```dotenv
# ── Telegram (Downloader) ───────────────────────────────────────
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
PHONE=+8613800138000
DOWNLOAD_DIR=/home/user/downloads
WEB_PORT=8091
API_KEY=your_secret_key_here

# 下载行为（可选）
DOWNLOAD_TIMEOUT=180
MAX_TOTAL_CONNECTIONS=20
CHUNK_SIZE=1048576

# ── Mover ───────────────────────────────────────────────────────
MOVER_PORT=8092
MOVER_MAX_CONCURRENT=3
AUTO_MOVE=true

# ── Unzipper ────────────────────────────────────────────────────
WATCH_PATH=/home/user/watch
OUTPUT_PATH=/home/user/extracted
PASSWORDS=password1,password2,mysecret
UNZIPPER_PORT=8093
MAX_CONCURRENT_TASKS=3
```

### 字段格式说明

- **`PASSWORDS`**：逗号分隔，每个密码不含逗号，前后空格会被自动去除；顺序即尝试顺序；无密码包始终优先尝试无密码（空字符串）以避免假阳性
- **`CHUNK_SIZE`**：自动向下对齐到 4096 的倍数，上限 1048576；例如填 `524288`（512 KB）
- **`WATCH_PATH` / `OUTPUT_PATH`**：建议使用绝对路径；目录不存在时服务启动会自动创建
