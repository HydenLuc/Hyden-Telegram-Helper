# Changelog / 更新日志

## Unreleased

- Optional "use takeout for history scans" switch (Settings → Advanced, off by default): listing a chat's history goes through Telegram's data-export session, about 3.5× faster and without rate-limit waits in tests; it falls back to the normal way automatically if takeout fails.
  新开关「扫历史用 takeout 通道」（设置 → 高级，默认关）：历史下载翻消息列表改走 Telegram 数据导出会话，实测快约 3.5 倍、不再被限流卡住；takeout 出问题时自动退回普通方式接着扫。
- The dashboard page itself no longer needs the API key (the data APIs still do): open it, paste the key once when asked. A yellow banner warns when the dashboard is reached from another device without an `API_KEY`.
  控制台页面本身不再需要钥匙（数据接口照样要）：打开后按提示粘贴一次钥匙即可。没设 `API_KEY` 又从别的设备打开时，顶部显示黄色提醒。
- Paste a Telegram message link (`t.me/<channel>/<id>`, `t.me/c/<id>/<id>`, topic links) into Saved Messages to download that message's media; albums are downloaded whole into one folder.
  在「我的收藏」里贴 Telegram 消息链接即可下载那条消息的媒体；相册整组下载、放进同一个文件夹。
- New `状态` (status) command: send it in any chat to get download / pause-switch / disk status.
  新命令「状态」：在任意聊天里发送，回复下载进度、三个暂停开关和磁盘剩余。
- Optional delay between starting downloads (`DOWNLOAD_START_INTERVAL` / `DOWNLOAD_START_JITTER`, off by default) to look less like a bot.
  可选的「下载开始间隔」（默认关闭），降低被判成机器人的风险。
- Media forwarded into Saved Messages is now filed under the original channel / sender name instead of your own name.
  转发进收藏的媒体，文件夹按原频道 / 原发送人命名，不再全放在自己名字下面。
- History downloads keep albums together in one folder.
  历史下载不再把同一相册拆进多个文件夹。
- `tools/backup.py` now also saves `docker-compose.override.yml` (machine-specific; `restore.py` only tells you where it is, it is not copied back automatically).
  备份也带上 `docker-compose.override.yml`（机器专属，还原时只提示位置，不自动复制回去）。
- Settings page: about 20 more options that used to need `.env` edits (download scheduling, extraction, record retention, move allow-list, crash/disk notifications with a test button, auto-heal), all five pause switches in one place, and a "?" next to every setting explaining what it does, what turning it up/down does, and when it takes effect. Leaving a field empty restores the default. Download timeout can no longer be set below 2× the flood-wait threshold; the connection limit is 64 everywhere and applies immediately.
  设置页：原来只能改 `.env` 的约 20 项搬进网页（下载调度、解压、记录保留、搬运白名单、出事通知 + 测试按钮、卡死自动重启），五个暂停开关集中一处，每项旁边有「?」说明卡片（是什么、调大 / 调小会怎样、什么时候生效）。留空 = 回到默认。下载超时不能再填得比限流等待的 2 倍还低；总连接数上限统一为 64，保存后立即生效。

## v1.0.0 — 2026-11-14

First public release. / 第一个公开版本。

**Downloading / 下载**
- Signs in with your own Telegram account and watches the channels / groups you choose; new media is downloaded automatically.
  用自己的 Telegram 账号登录，监听选定的频道 / 群组，新媒体自动下载。
- Adaptive parallel downloads (1–6 connections per file), resumable after crashes or network errors, global connection limit.
  按文件大小自动分 1–6 条连接并发下载；崩溃 / 断网后断点续传；全局连接数上限。
- History downloads (whole channel, ID range, date range, fill the gaps), duplicate confirmation queue, MD5 de-duplication.
  历史消息下载（整个频道 / ID 范围 / 日期范围 / 补漏）、重复文件确认队列、MD5 去重。
- Three pause switches (normal channels / exempt channels / Saved Messages).
  三个暂停开关（普通频道 / 例外频道 / 收藏）。

**Moving and extracting / 搬运与解压**
- Atomic two-step moves into the extraction folder; targets are restricted to your data folders.
  两步原子搬运；只能搬到数据目录之下。
- Automatic extraction of zip / rar / 7z / multi-volume archives with a password list.
  自动解压 zip / rar / 7z / 多卷包，按密码库依次尝试。

**Operations / 运维**
- Web dashboard (works on phones); web login with QR-code login when the code never arrives.
  网页控制台（手机可用）；网页登录，收不到验证码可以扫码登录。
- Restores every pause switch after a restart or power loss; optional start on boot (native macOS / Linux).
  重启 / 断电后恢复各个暂停开关；原生 macOS / Linux 可开机自启。
- Docker: five containers with health checks; hung containers are restarted automatically.
  Docker：五个容器带健康检查，卡死自动重启。
- Disk-space alerts, optional Telegram crash notifications, daily log rotation, backup / restore tools.
  磁盘空间告警、可选的 Telegram 崩溃通知、日志按天切分、备份 / 还原工具。

**Known limitations / 已知限制**
- The web interface is Chinese only for now. / 网页界面目前只有中文。
- Windows is supported through Docker Desktop only. / Windows 只支持 Docker Desktop。
- No Android app in this release. / 这一版没有安卓 App。
