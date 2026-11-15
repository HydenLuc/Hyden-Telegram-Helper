# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys

from telethon import TelegramClient
import config

# session 文件固定在状态目录里：config.STATE_DIR / userbot.session（2026-11-11 起）。
#    以前传的是相对路径 "userbot"，跟着进程的当前工作目录找——工作目录一错，Telethon 就找不到
#    session → 要验证码 → 非交互环境下卡在 EOFError（2026-08-18 迁机器时踩过）。
#
# 🔴 flood_sleep_threshold 必须显式设，且**明显小于** config.DOWNLOAD_TIMEOUT。
#    Telethon 默认 60，而停滞看门狗以前也是 60 —— 两个数字一模一样：
#    Telethon 遇到 ≤60s 的 FloodWait 会自己静默 sleep 重试（这期间零进度），
#    看门狗同一时刻判定「卡死」并取消。大文件请求多、限流重，所以专挑它们死。
#    日志里 363 次「超过 60s 无进度」几乎全是 2.5~3.5 GB 的文件，
#    配合当时「超时就删光 .partN」的 bug，它们永远下不完（2026-09-17 查明）。
client = TelegramClient(
    str(config.STATE_DIR / "userbot"), config.API_ID, config.API_HASH,
    flood_sleep_threshold=config.FLOOD_SLEEP_THRESHOLD,
)

SESSION_FILE = config.STATE_DIR / "userbot.session"


def lock_down_session() -> None:
    """登录文件 = 账号的完整控制权，只给本人读写（600）。

    Telethon 建这个文件用的是默认权限（通常 644，同机别的用户能读）。以前只在启动时
    打一行「建议 chmod 600」的警告，新装的人第一次启动必看到、也基本不会去改（2026-11-12）。
    Windows 上 chmod 只管只读位，没意义，跳过。
    """
    if os.name == "nt":
        return
    for p in (SESSION_FILE, SESSION_FILE.with_name(SESSION_FILE.name + "-journal")):
        try:
            if p.exists() and p.stat().st_mode & 0o077:
                p.chmod(0o600)
        except OSError:
            pass


lock_down_session()   # TelegramClient(...) 一创建就建了文件，马上收紧


def login_mode() -> str:
    """要验证码时去哪儿输：有终端就在终端输，没有就在网页上输。

    没有终端的情况：start.sh 后台启动（nohup）、Docker、launchd / systemd。以前一律在终端等输入，
    这些情况下 stdin 是空的 → 直接 EOFError 崩掉，**新用户第一次启动必崩**；
    README 写着「也可以在网页输入」，其实那条路 2026-04-22 被断开了。
    2026-11-12 原生端到端测试用新测试号首次登录时撞上。
    """
    try:
        return "terminal" if sys.stdin is not None and sys.stdin.isatty() else "web"
    except (ValueError, OSError):    # stdin 已关闭
        return "web"


async def start_client() -> None:
    """登录并连上 Telegram。两个入口（bot.py、downloader/main.py）都用这一个。"""
    if login_mode() == "terminal":
        await client.start(phone=config.PHONE)
    else:
        # 网页登录不用 client.start：它不告诉用户验证码发到了哪、分不清「不对」和「过期」、
        # 也没有重发（2026-11-13 测试号因此登不上），详见 web_login.py 开头
        from downloader.tg.web_login import web_login
        await web_login(client, config.PHONE)
    lock_down_session()
