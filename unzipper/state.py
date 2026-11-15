# SPDX-License-Identifier: AGPL-3.0-or-later
import config
from unzipper.storage import load_history, load_passwords

current_tasks: dict[str, dict] = {}
pending_multipart: dict[str, dict] = {}
history: list[dict] = load_history()
ws_clients: set = set()
# P1-pwd: 启动时从 passwords.json 加载（首次启动会从 .env PASSWORDS= 迁移）
passwords: list[str] = load_passwords()
max_concurrent_tasks: int = config.MAX_CONCURRENT_TASKS

# P1-5a Q4 软暂停：watcher.on_created 入口检查
# 不持久化（重启回到 False）。resume 时扫描 WATCH_PATH 补处理
paused: bool = False
