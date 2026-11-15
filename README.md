<p align="right"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# Hyden TGhelper

A Telegram download assistant: it signs in with **your own Telegram account**, watches the channels and groups you choose, downloads their media, then automatically moves and extracts archives — no manual steps. Comes with a web dashboard that also works on your phone.

Built on [Telethon](https://github.com/LonamiWebs/Telethon) + [aiohttp](https://github.com/aio-libs/aiohttp).

> ⚠️ **Please read the [Disclaimer](#disclaimer) before using it.**
>
> ℹ️ The web interface is currently **Chinese only**; an English interface is planned.

---

## Disclaimer

- **This is a user-account automation tool (a "userbot"), not an official Telegram bot.** It signs in as you and receives messages and downloads files on your behalf. Telegram monitors automated user accounts: heavy or frequent activity can get an account limited or banned. **You use it at your own risk.**
- **You are responsible for what you download.** Only save content you have the right to keep, and follow your local laws and the [Telegram Terms of Service](https://telegram.org/tos). The authors are not responsible for any content you download, store or share.
- **Use your own API credentials** (`api_id` / `api_hash`, see step 0 below). Never use credentials shared by someone else, and never share yours.
- **The login file `userbot.session` gives full control of your account.** Don't give it to anyone, don't commit it to any repository, and don't use the same file on two machines at once (Telegram treats that as a suspicious login).
- The software is provided "as is", without warranty of any kind. See [License](#license).

---

## Features

### Downloading

- **Adaptive parallel downloads**: 1/2/4/6 connections per file depending on size, capped globally by `MAX_TOTAL_CONNECTIONS`
- **Resumable downloads**: crashes and network retries don't restart from zero
- **Duplicate confirmation queue**: a message that arrives again isn't silently skipped — you decide
- **MD5 de-duplication**: pre-check before downloading + async MD5 index afterwards
- **History downloads**: a whole channel, an ID range, a date range, or "fill the gaps"
- **Global pause / exempt channels / Saved Messages**: three switches for normal channels, exempt channels and your Saved Messages
- **Watch list** with sorting, search and statistics

### Extracting and moving

- **Automatic extraction**: zip / rar / 7z / multi-volume, live progress, cancellable
- **Password list**: add, remove and reorder in the browser; tried in order
- **Atomic moves**: staged two-step moves, works across file systems, idempotent; only allowed inside your data folders

### Operations

- **Back to where you left off after a restart or power loss**: every pause switch returns to its state before shutdown; unfinished downloads resume
- **Start on boot**: one switch in Settings (native macOS / Linux; Docker handles it itself)
- **Web login**: shows where Telegram sent the code, lets you resend it, and offers **QR-code login from your phone** when the code never arrives
- **Disk space monitoring** with multi-level alerts
- **Crash notifications** (optional) to a Telegram chat of your choice
- **Daily log rotation**, kept for 14 days

---

## Four independent services

| Service | What it does | Default port |
|---------|--------------|--------------|
| **dashboard** | Web dashboard (start here): overview, channels, tasks, settings | `8090` |
| **downloader** | Telegram downloads, live progress; first-time login happens on its page | `8091` |
| **mover** | Atomic file moves | `8092` |
| **unzipper** | Watches a folder and extracts archives | `8093` |

Each service runs on its own, so restarting one doesn't interrupt the others.

---

## Quick start

### 0. Get your own Telegram API credentials (required)

1. Open [my.telegram.org](https://my.telegram.org) and sign in with your Telegram account
2. Go to **API development tools** and create an app (any name)
3. Note the **api_id** and **api_hash** — they go into `API_ID` / `API_HASH` in `.env`

### Option 1: Docker Compose (recommended; the only supported way on Windows)

**Requires** [Docker](https://docs.docker.com/get-docker/) (Docker Desktop on macOS / Windows).

```bash
git clone https://github.com/HydenLuc/Hyden-Telegram-Helper.git
cd Hyden-Telegram-Helper
cp .env.example .env
# In .env, fill in API_ID, API_HASH and PHONE (with country code, e.g. +15551234567)
# and HOST_DATA_ROOT = where downloads should go, e.g.:
#   Windows:  HOST_DATA_ROOT=E:/
#   macOS:    HOST_DATA_ROOT=/Volumes/MyDisk
#   Linux:    HOST_DATA_ROOT=/media/usb1
docker compose up -d --build
```

- `telegramDMZ/{download,move,unzip}` is created under `HOST_DATA_ROOT`; download → move → extract runs on its own.
- Open http://localhost:8091 for the first login (step 4), then use http://localhost:8090 .
- Login state lives in `./state/` and survives container rebuilds.
- **Docker Desktop (Windows / macOS)**: copy `deploy/docker-desktop/docker-compose.desktop.yml` to `docker-compose.override.yml` in the project root to keep state in a Docker named volume (the file explains why).
- **Linux**: set `PUID` / `PGID` in `.env` (your `id -u` / `id -g`) so downloaded files belong to you instead of root. Set `TZ` for your time zone.
- Ports are bound to `127.0.0.1` only. To open them to your LAN, set `API_KEY` in `.env` first, then change the port bindings. ⚠️ Docker port mappings bypass firewalls such as ufw.

### Option 2: Native install (Linux / macOS)

**Requires** Python **3.10+** (3.12 recommended).

```bash
git clone https://github.com/HydenLuc/Hyden-Telegram-Helper.git
cd Hyden-Telegram-Helper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# System tools for extraction:
sudo apt install p7zip-full unrar     # Debian / Ubuntu
brew install p7zip unar               # macOS (unar handles rar)
cp .env.example .env                  # fill in at least API_ID, API_HASH, PHONE
```

Data folders: set just `DATA_ROOT` (it creates `telegramDMZ/{download,move,unzip}` under it). If you leave it empty, `~/TGhelperFileSystem` is used. See [docs/config.md](docs/config.md) (Chinese).

> ⚠️ Security: services listen on `127.0.0.1` by default. Listening on any other address requires `API_KEY`, otherwise the program refuses to start. Put a reverse proxy with HTTPS in front of it if you expose it to the internet.

### 3. Start / stop (native)

```bash
./start.sh     # start all four services in the background; logs go to logs/
./stop.sh      # stop everything
```

### 4. First Telegram login

- **Running in a terminal** (`python bot.py` in the foreground): enter the code in the terminal.
- **Running in the background** (`./start.sh`, Docker, start on boot): open the downloader page (http://localhost:8091 by default) and a login box appears:
  - it tells you where Telegram sent the code (Telegram app / SMS / email / phone call), and you can resend it;
  - **if the code never arrives**, click the QR-login button (改用手机扫码登录) and scan the code with a phone that is already signed in to this account: Telegram → Settings → Devices → Scan QR;
  - if the account has two-step verification, enter the password next.

After a successful login, `userbot.session` is created (permissions set to 600 automatically), and later starts don't need a login.

### 5. Start on boot / recover after a power loss

- **Start on boot**: Dashboard → ⚙️ Settings → "Start on boot", or `python -m tools.autostart on` (`off` to disable, `status` to check). macOS uses a LaunchAgent (starts after you log in); Linux uses a systemd user service (run `sudo loginctl enable-linger <user>` once to start without logging in). Docker needs nothing (containers are `restart: unless-stopped`).
- **Back to where you left off**: the global / exempt / Saved Messages / mover / unzipper pause switches return to their state before shutdown. Prefer everything paused after a restart? Set "After restart / power loss" to "Always pause downloads" in Settings (`RESTART_MODE=PAUSED`).

### 6. Dashboard

Open http://localhost:8090 . The top-left shows "your name + TGhelper"; the name defaults to the signed-in Telegram account and can be changed or hidden in Settings.

To open it in its own window (no address bar, like a desktop app):

```bash
./panel.sh          # macOS / Linux
panel.bat           # Windows
```

---

## Project layout

```
├── bot.py              # downloader entry point
├── config.py           # global configuration (read from .env)
├── dashboard/          # web dashboard
├── downloader/         # Telegram downloads
├── mover/              # atomic moves
├── unzipper/           # automatic extraction
├── control/            # start/stop services in Docker (only reachable inside the compose network)
├── common/             # shared code
├── tools/              # backup / restore / start on boot
├── docker/             # container entry point, health check
├── deploy/             # deployment examples
└── docs/               # design and operations docs (currently in Chinese)
```

---

## License

Copyright (C) 2026 HydenLuc

Hyden TGhelper is free software: you can redistribute it and/or modify it under the terms of the **GNU Affero General Public License** as published by the Free Software Foundation, either **version 3 of the License, or (at your option) any later version** (`AGPL-3.0-or-later`). See [LICENSE](LICENSE).

In short: you may use, modify and share it freely, but if you distribute a modified version — or let others use it over a network — you must publish your source code under the same license.

**Commercial license**: if you want to use it in a closed-source product, contact HydenLuc on GitHub for a commercial license.

Contributions require signing a Contributor License Agreement; see [CONTRIBUTING.md](CONTRIBUTING.md). Release notes: [CHANGELOG.md](CHANGELOG.md). Security issues: [SECURITY.md](SECURITY.md).
