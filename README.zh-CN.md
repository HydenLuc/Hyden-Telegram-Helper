<p align="right"><a href="README.md">English</a> | <b>简体中文</b></p>

# Hyden TGhelper

Telegram 下载助手：用你自己的 Telegram 账号自动监听频道 / 群组并下载媒体文件，下载完的压缩包自动搬运、自动解压，全程无需人工干预。自带网页控制台（手机也能看）。

基于 [Telethon](https://github.com/LonamiWebs/Telethon) + [aiohttp](https://github.com/aio-libs/aiohttp)。

> ⚠️ **使用前请先读下面的 [免责声明](#免责声明)。**

---

## 免责声明

- **这是「用户账号」自动化工具（userbot），不是 Telegram 官方机器人。** 它用你自己的 Telegram 账号登录、以你的身份收消息和下载文件。Telegram 对自动化的用户账号有风控：频繁、大量的操作可能导致账号被限制甚至封禁。**账号风险由使用者自行承担。**
- **下载内容的版权和合法性由使用者自己负责。** 只下载你有权保存的内容，遵守所在地法律和 [Telegram 服务条款](https://telegram.org/tos)。本项目作者不对使用者下载、保存、传播的任何内容负责。
- **每个人都要用自己申请的 API 凭证**（`api_id` / `api_hash`，见「快速开始」第 0 步）。不要使用别人分享的凭证，也不要把你的凭证分享出去。
- **登录文件 `userbot.session` 等于你账号的完整控制权。** 不要拷给别人、不要提交进任何仓库，也别在两台机器上同时用（会被 Telegram 判为异常登录）。
- 本软件按「原样」提供，不提供任何担保。详见 [许可证](#许可证)。

---

## 主要功能

### 下载与监听

- **自适应分块并发下载**：按文件大小自动选择 1/2/4/6 个连接，全局 `MAX_TOTAL_CONNECTIONS` 配额限流
- **断点续传**：崩溃恢复 / 网络重试时不重头下载（详见 [downloader/docs/reliability.md](downloader/docs/reliability.md)）
- **重复下载确认队列**：同一条消息再次到达不静默跳过，进入待确认队列让你决定
- **MD5 内容去重**：下载前预检 + 下载后异步 MD5 索引
- **历史消息下载**：整个频道 / 指定 ID 范围 / 指定日期范围 / 遗漏补下
- **全局暂停 / 例外频道 / 收藏**：三个开关分别控制普通频道、例外频道和「收藏（Saved Messages）」
- **监听列表**：排序、搜索、统计

### 解压与搬运

- **自动解压**：zip / rar / 7z / 多卷，实时进度，可随时取消
- **密码库**：网页上增删、拖拽排序，解压时按顺序尝试
- **原子搬运**：两步暂存隔离，跨文件系统兼容，同一任务重复提交不会重复搬；只能搬到数据目录之下

### 运维

- **重启 / 断电后回到上次的状态**：各个暂停开关恢复成关机前的样子，没下完的任务自动续传
- **开机自动启动**：设置页一键开关（macOS / Linux 原生；Docker 由 Docker 负责）
- **网页登录**：页面写明验证码发到了哪里，可重发；收不到验证码可以**用手机扫码登录**
- **磁盘空间监控**：多级阈值告警 + 页面横幅
- **崩溃通知**：可选，把崩溃信息发到你指定的 Telegram 对话
- **日志按天切分**，保留 14 天

完整 API 见 [docs/api.md](docs/api.md)；文档目录见 [docs/INDEX.md](docs/INDEX.md)。

---

## 四个独立模块

| 模块 | 说明 | 默认端口 |
|------|------|----------|
| **dashboard** | 网页控制台（推荐入口）：总览、频道、任务、设置 | `8090` |
| **downloader** | Telegram 下载：监听聊天、并发下载、实时进度；首次登录也在它的页面上 | `8091` |
| **mover** | 原子文件搬运 | `8092` |
| **unzipper** | 监听目录 + 自动解压 | `8093` |

四个模块各自独立运行，改一个不影响其他几个。

---

## 快速开始

### 0. 申请你自己的 Telegram API 凭证（必做）

1. 打开 [my.telegram.org](https://my.telegram.org)，用你的 Telegram 账号登录
2. 进入 **API development tools**，创建一个应用（名字随意）
3. 记下 **api_id** 和 **api_hash**，稍后填进 `.env` 的 `API_ID` / `API_HASH`

### 方式一：Docker Compose（推荐；Windows 只支持这种方式）

**前置要求**：安装 [Docker](https://docs.docker.com/get-docker/)（macOS / Windows 装 Docker Desktop）。

```bash
git clone https://github.com/HydenLuc/Hyden-Telegram-Helper.git
cd Hyden-Telegram-Helper
cp .env.example .env
# .env 里填：API_ID、API_HASH、PHONE（带国家码，如 +8613800000000）
# 再填 HOST_DATA_ROOT = 下载数据放哪，例如：
#   Windows:  HOST_DATA_ROOT=E:/
#   macOS:    HOST_DATA_ROOT=/Volumes/MyDisk
#   Linux:    HOST_DATA_ROOT=/media/usb1
docker compose up -d --build
```

- 程序会在 `HOST_DATA_ROOT` 下自动创建 `telegramDMZ/{download,move,unzip}`，下载 → 搬运 → 解压全自动联动。
- 打开 http://localhost:8091 完成首次登录（见第 4 步），之后用 http://localhost:8090 。
- 登录状态保存在 `./state/`，重建容器不丢。
- **Docker Desktop（Windows / macOS）**：建议把 `deploy/docker-desktop/docker-compose.desktop.yml` 复制成项目根目录的 `docker-compose.override.yml`，状态改放 Docker 命名卷（文件里写了原因）。
- **Linux**：建议在 `.env` 里设 `PUID` / `PGID`（你自己的 `id -u` / `id -g`），下载的文件就归你，不是 root。时区设 `TZ`。
- 端口默认只绑 `127.0.0.1`（只有本机能访问）。要让局域网访问，先在 `.env` 设 `API_KEY`，再改端口绑定。⚠️ Docker 的端口映射会绕过 ufw 等防火墙。

### 方式二：原生部署（Linux / macOS）

**前置要求**：Python **3.10+**（推荐 3.12）。

```bash
git clone https://github.com/HydenLuc/Hyden-Telegram-Helper.git
cd Hyden-Telegram-Helper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 解压用的系统工具：
sudo apt install p7zip-full unrar     # Debian / Ubuntu
brew install p7zip unar               # macOS（unar 用来解 rar）
cp .env.example .env                  # 至少填 API_ID、API_HASH、PHONE
```

数据目录：推荐只填 `DATA_ROOT`（自动在下面建 `telegramDMZ/{download,move,unzip}`）；不填就是 `~/TGhelperFileSystem`。详见 [docs/config.md](docs/config.md)。

> ⚠️ 安全：默认只监听 `127.0.0.1`。要监听其他地址必须先设 `API_KEY`，否则程序拒绝启动。公网使用请加反向代理 + HTTPS。

### 3. 启动 / 停止（原生部署）

```bash
./start.sh     # 后台启动四个模块，日志在 logs/
./stop.sh      # 全部停止
```

### 4. 首次登录 Telegram

- **前台运行**（终端里直接 `python bot.py`）：在终端按提示输入验证码。
- **后台运行**（`./start.sh`、Docker、开机自启）：打开下载器页面（默认 http://localhost:8091），页面会弹出登录框：
  - 写明这次验证码发到了哪里（Telegram App / 短信 / 邮箱 / 电话），收不到可以点「重新发送」；
  - **怎么都收不到验证码**：点「改用手机扫码登录」，在已经登录这个号的手机上打开 Telegram → 设置 → 设备（Devices）→ 扫描二维码（Scan QR）；
  - 账号开了两步验证的话，接着输密码。

登录成功后会生成 `userbot.session`（权限自动设为 600），之后启动不用再登录。

### 5. 开机自启 / 断电后恢复

- **开机自动启动**：控制台 ⚙️ 设置 →「开机自动启动」，或命令行 `python -m tools.autostart on`（`off` 关闭、`status` 查看）。macOS 用 LaunchAgent（登录后启动）；Linux 用 systemd 用户服务（要开机不登录也启动，执行一次 `sudo loginctl enable-linger <用户名>`）。Docker 不用设置（容器是 `restart: unless-stopped`）。
- **回到上次的状态**：全局 / 例外 / 收藏 / 搬运 / 解压这几个暂停开关，重启或断电来电后默认恢复成关机前的样子。不想这样就在设置里把「重启 / 断电来电后」改成「下载监听一律暂停」（`RESTART_MODE=PAUSED`）。

### 6. 控制台

打开 http://localhost:8090 。左上角显示「你的名字 + TGhelper」，名字默认取登录的 Telegram 账号名，可以在设置里改或隐藏。

想用独立窗口打开（没有地址栏，像桌面应用）：

```bash
./panel.sh          # macOS / Linux
panel.bat           # Windows
```

---

## 目录结构

```
├── bot.py              # 下载器入口
├── config.py           # 全局配置（从 .env 读取）
├── dashboard/          # 网页控制台
├── downloader/         # Telegram 下载
├── mover/              # 原子搬运
├── unzipper/           # 自动解压
├── control/            # Docker 版的服务启停（只在 compose 内部网络可见）
├── common/             # 公共代码
├── tools/              # 备份 / 还原 / 开机自启
├── docker/             # 容器入口、健康检查
├── deploy/             # 部署示例
└── docs/               # 设计与运维文档（目前是中文）
```

---

## 许可证

Copyright (C) 2026 HydenLuc

Hyden TGhelper 是自由软件，按 **GNU Affero 通用公共许可证（AGPL）第 3 版或（由你选择）任何更新的版本**发布（`AGPL-3.0-or-later`）。全文见 [LICENSE](LICENSE)（英文原文，以原文为准）。

简单说：你可以免费使用、修改、再发布；但如果你发布了修改过的版本，或者让别人通过网络使用它，就必须用同样的许可证公开你的源码。

**商业授权**：想在闭源产品里使用，请在 GitHub 上联系 HydenLuc 购买商业授权。

贡献代码前需要签署贡献者协议（CLA），见 [CONTRIBUTING.md](CONTRIBUTING.md)。更新日志见 [CHANGELOG.md](CHANGELOG.md)；安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
