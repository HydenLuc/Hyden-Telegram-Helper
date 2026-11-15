# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
from datetime import datetime

import config
from downloader.storage import load_watched, load_completed

watched: dict                     = load_watched()
active_downloads: dict[str, dict] = {}
completed_downloads: list[dict]   = load_completed()

# P1-5b: 持久化未完成任务与媒体组状态
# 实际值由 main() 启动时调 storage.load_*() 注入；此处仅声明类型与默认值。
# 详见 downloader/docs/reliability.md
pending_tasks: dict[str, dict] = {}     # task_id → pending_task_record
grouped_state: dict[str, dict] = {}     # group_key → group_record

# F6: 待确认重复下载队列。详见 docs/duplicate-download-design.md
duplicate_queue: list[dict] = []

# MD5 内容去重：详见 docs/md5-dedup-design.md
content_index: dict = {"md5": {}, "fuid": {}}     # md5_hex → record；fuid_key → md5_hex
pending_toasts: list[dict] = []                    # 不持久化，重启即清

# 历史消息下载：详见 docs/history-pull-design.md
history_jobs: dict[str, dict] = {}                 # job_id → job record
ws_clients: set                   = set()
bot_start_time: datetime          = None
_conn_gate                        = None   # asyncio.Condition, initialized in main()
_total_connections: int           = 0      # connections currently reserved
_history_connections: int         = 0      # source="history" 占用连接数（用于子配额）
_pending_tasks: set[asyncio.Task] = set()
_group_dirs:    dict[str, dict]   = {}     # group_key → {dir,ts,detail,count,max_views,max_fwds,no_text}
GROUP_DIR_TTL = 300  # 5 分钟后清理缓存

# Auth state — bridges web input to Telethon's code/password callbacks
_auth_step:   str                    = "idle"   # idle | waiting_code | waiting_password
_auth_future: asyncio.Future | None  = None
_auth_info:   dict                   = {}       # 网页登录：验证码发到哪里 / 错误提示（见 tg/web_login.py）

# Runtime-mutable settings (mirrored from config, may be updated via /api/settings)
MAX_TOTAL_CONNECTIONS: int = config.MAX_TOTAL_CONNECTIONS
CHUNK_SIZE: int            = config.CHUNK_SIZE

# P1-5a Q4 软暂停：模块级标志，handle_media 入口检查
# 不持久化（重启回到 False）。详见 docs/pause-design.md
#
# 两个暂停开关互相独立，组合起来是一张真值表（2026-08-06 加 exempt_paused）：
#   全局暂停 关 + 例外暂停 关 → 全都收（默认）
#   全局暂停 开 + 例外暂停 关 → 只有例外频道收（例外的本意）
#   全局暂停 开 + 例外暂停 开 → 全都不收（要把队列排空时用）
#   全局暂停 关 + 例外暂停 开 → 例外频道反而不收，其余照收（少见但允许）
monitoring_paused: bool = False   # 全局暂停：对非例外频道生效
exempt_paused: bool = False       # 例外暂停：对例外频道生效

# 收藏开关（2026-11-10）：只管「我的收藏」，和上面两个开关、监听列表都无关。
# 与上面两个不同，它**持久化**在 downloader_settings.json 的 saved_paused 键，
# 重启后保持 hyden 上次的选择；设置里没有这个键时按「暂停」处理（bot.py 启动时读）。
account_name: str = ""          # 登录的 Telegram 账号名（控制网页标题用，2026-11-13）
saved_paused: bool = True         # 收藏暂停：True = 收藏里的媒体不下载

# 磁盘空间快照：由 downloader.disk_monitor 周期任务每 60s 刷新
# 前端通过 /api/status 与 WebSocket 读取，详见 docs/disk-space-design.md
disk_usage: dict = {
    "free": 0,
    "total": 0,
    "pct_free": 0.0,
    "checked_at": None,
    "error": None,
}

# Per-task pause/cancel controls
# task_id → {'pause_event': asyncio.Event|None, 'cancel_flag': bool, 'dl_task': asyncio.Task|None}
task_controls: dict[str, dict] = {}
# task_id → outer download_one asyncio.Task (used to cancel waiting/flood_wait tasks)
task_outer_tasks: dict[str, asyncio.Task] = {}
