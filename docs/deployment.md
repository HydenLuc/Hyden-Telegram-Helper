# 部署指南（进阶）

> 最后更新 2026-11-13 17:00:00
>
> 快速安装看根目录 [README.zh-CN.md](../README.zh-CN.md)。本文补充 README 里没展开的：
> 系统要求、两种部署方式的细节、局域网访问、升级、备份、常见问题、公网安全清单。
> 配置项逐个说明见 [config.md](config.md)。

## 1. 系统要求

| 项 | 要求 |
|---|---|
| 运行方式 | **Docker（任何系统，Windows 只支持这种）**，或原生 Linux / macOS |
| Python（原生） | 3.10+，推荐 3.12 |
| 解压工具（原生） | 7-Zip（`7z` / `7zz`）+ 能解 rar 的程序（`unrar` / `unar` / `bsdtar` 任一）。Docker 镜像里已装好 |
| 磁盘 | 解压输出所在分区建议留出文件总量 2 倍以上的空间（原包和解压结果会同时存在） |
| 网络 | 能连上 Telegram（不能直连的地区需要代理） |
| ⚠️ 状态目录 | **必须在本地盘**，不能放 NFS / SMB 网络盘：里面的 `userbot.session`、`state.db` 是 SQLite，网络文件系统上的锁不可靠。下载数据可以放网络盘 |

## 2. Docker 部署

```bash
cp .env.example .env        # 填 API_ID、API_HASH、PHONE、HOST_DATA_ROOT
docker compose up -d --build
docker compose ps           # 五个容器都应该是 healthy
```

- 五个容器：dashboard / downloader / mover / unzipper + control（网页上的服务启停、卡死自动重启都靠它，只有它能访问 Docker）。
- **只改了网页**：`docker compose up -d --build --no-deps dashboard`，下载不会中断。
- **单独重启一个**：`docker compose restart unzipper`。
- **卡死自动重启**：容器活着但健康检查连续失败时，control 会自动重启它（10 分钟内不重复，1 小时超过 3 次就停手并发通知）。`.env` 里 `AUTOHEAL=false` 关闭。
- **数据盘守卫**：数据放外接盘 / 网络盘时，在数据盘根目录 `touch .tgdrive_ok`，并在 `.env` 里设 `DATA_MARKER=/data/.tgdrive_ok`。盘没挂上时容器拒绝启动，不会把下载写进系统盘。
- **Linux**：`.env` 设 `PUID` / `PGID`（`id -u` / `id -g`），下载的文件归你而不是 root；`TZ` 设时区。
- **Docker Desktop（Windows / macOS）**：把 `deploy/docker-desktop/docker-compose.desktop.yml` 复制成项目根目录的 `docker-compose.override.yml`，状态放进 Docker 命名卷。
- **macOS + 网络盘**：Docker Desktop 读 NFS / SMB 挂载有时会因为系统隐私权限卡住或报错。数据放网络盘时，先在 Docker Desktop 的文件共享设置里确认那个路径可用；不行就改用原生部署。

### 局域网 / 其他机器访问

默认所有端口只绑 `127.0.0.1`，只有本机能打开。要让局域网访问：

1. `.env` 里先设 `API_KEY=<一串随机字符>`（`openssl rand -hex 32`）。
2. 在项目根目录建 `docker-compose.override.yml`，把 dashboard 的端口绑到本机的局域网 IP：

```yaml
services:
  dashboard:
    ports:
      - "192.168.1.10:8090:8090"   # 换成这台机器的局域网 IP
```

3. `docker compose up -d --force-recreate dashboard`（端口改动要重建容器，`restart` 不生效）。

⚠️ **别写成 `0.0.0.0` 或只写端口**：Docker 的端口映射会绕过 ufw 等防火墙，等于对所有网卡开放。

## 3. 原生部署（Linux / macOS）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
./start.sh                  # 后台启动四个服务；日志在 state/logs/（按天切分），启动输出在 logs/
./stop.sh
```

- 数据目录：只填 `DATA_ROOT`，自动建 `telegramDMZ/{download,move,unzip}`；不填就是 `~/TGhelperFileSystem`。
- 开机自启：`python -m tools.autostart on`（macOS LaunchAgent / Linux systemd 用户服务）。Linux 要开机不登录也启动，执行一次 `sudo loginctl enable-linger <用户名>`。
- 首次登录：打开 http://localhost:8091 ，按页面提示填验证码，或改用手机扫码。
- ⚠️ 手动单独启动下载器用 `python bot.py`，**别用** `python -m downloader.main`（那个入口不读取重启前的暂停状态）。

## 4. 升级

```bash
git pull
# Docker：
docker compose up -d --build
# 原生：
.venv/bin/pip install -r requirements.txt && ./stop.sh && ./start.sh
```

登录状态、任务队列都在状态目录里，升级不用重新登录。暂停开关会恢复成升级前的样子。

## 5. 备份

```bash
python tools/backup.py              # 打包状态目录 + .env（可加密）
python tools/restore.py <备份文件>   # 还原
```

| 内容 | 重要性 | 说明 |
|---|---|---|
| `.env` + `userbot.session` | 🔴 | 合在一起 = 账号完整控制权。备份文件要加密、目录 700 / 文件 600，别传到网盘公开位置 |
| `state.db` | 高 | 下载队列、去重索引。工具用 SQLite 在线备份，服务在跑也能备 |
| 密码库、监听列表、暂停状态、页面标题设置 | 中 | 丢了要手动重新设 |
| 完成记录、解压历史 | 低 | 只影响历史显示 |

## 6. 常见问题

**Q：启动报 `database is locked`**
另一个进程还拿着 `userbot.session`。先 `./stop.sh`（或 `docker compose down`）再启动。⚠️ 同一个登录文件不能在两台机器上同时用，会被 Telegram 判为异常登录。

**Q：多卷 `.7z.001` 解不开 / `.rar` 解不开**
解压器启动日志里会提示缺哪个工具。多卷 7z 必须装 7-Zip；rar 要装 `unrar` / `unar` / `bsdtar` 之一。

**Q：放进搬运目录的文件没被解压**
解压器每 10 秒扫一次 `WATCH_PATH`（`UNZIPPER_SCAN_INTERVAL` 可调），文件大小稳定后才开始。检查目录对不对、有没有读权限、解压是不是被暂停了。

**Q：解压慢**
压缩包和解压输出在同一块机械硬盘上时，磁盘是瓶颈。分到两块盘，或者调低「解压并发上限」。

**Q：密码都试过了还是解不开**
在控制台 → 解压密码库确认密码在列表里（以前 `.env` 的 `PASSWORDS` 用逗号分隔，含逗号的密码会被拆开，请改在网页上加）。

**Q：重启后没开始下载**
关机前就是暂停状态（会恢复成关机前的样子），或者设了 `RESTART_MODE=PAUSED`。在下载器页面关掉暂停即可。

## 7. 公网部署安全清单

把服务暴露到公网之前，**每一项都要做**：

- [ ] 设强随机 `API_KEY`（至少 32 字符）。没设 `API_KEY` 时，原生部署监听非本机地址会直接拒绝启动
- [ ] 前面加反向代理 + HTTPS（Caddy / nginx），只开放 443，`8090-8093` 不对外
- [ ] `.env`、`userbot.session` 权限 600（登录文件程序会自动设）
- [ ] `API_KEY` 别出现在 git 提交、日志、截图里

⚠️ 缺任何一项，别人就可能调用搬运 / 解压接口在你的机器上任意搬文件、解压到任意位置。
