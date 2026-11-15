# SPDX-License-Identifier: AGPL-3.0-or-later
"""磁盘空间告警通知（Telegram）。

复用 crash_notify 的传输逻辑，但语义为「警告」而非「崩溃」。
失败静默写日志，不阻塞主流程。

调用：
    from common.disk_notify import notify_disk_warning
    await notify_disk_warning(pct_free, free_bytes, total_bytes, threshold=20)
"""
from datetime import datetime
from typing import Optional

import aiohttp

import config
from common.logger import get_logger

_log = get_logger("disk_notify")


def _fmt_bytes(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f}GB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.1f}MB"
    return f"{b}B"


def _build_message(pct_free: float, free: int, total: int, threshold: int) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"⚠️ 磁盘空间不足 {pct_free:.1f}%\n"
        f"剩余 {_fmt_bytes(free)} / {_fmt_bytes(total)}\n"
        f"路径：{config.DOWNLOAD_DIR}\n"
        f"阈值：{threshold}%\n"
        f"{timestamp}"
    )


async def _send_via_bot_api(bot_token: str, chat_id: int, text: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(url, json={"chat_id": chat_id, "text": text}) as resp:
                if resp.status == 200:
                    return True
                body = await resp.text()
                _log.error(f"Bot API 响应 {resp.status}: {body[:200]}")
    except Exception as e:
        _log.error(f"Bot API 发送异常: {e}")
    return False


async def notify_disk_warning(
    pct_free: float,
    free: int,
    total: int,
    threshold: int,
    *,
    telethon_client: Optional[object] = None,
) -> None:
    """异步告警通知。失败不抛异常。"""
    chat_id_raw = config.ADMIN_CHAT_ID
    if not chat_id_raw:
        return
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        _log.warning(f"ADMIN_CHAT_ID 必须是整数：{chat_id_raw!r}")
        return

    text = _build_message(pct_free, free, total, threshold)

    bot_token = getattr(config, "BOT_TOKEN", "") or ""
    if bot_token:
        if await _send_via_bot_api(bot_token, chat_id, text):
            _log.info(f"磁盘告警已发送到 {chat_id}（阈值 {threshold}%，via Bot API）")
            return

    if telethon_client is not None:
        try:
            await telethon_client.send_message(chat_id, text)
            _log.info(f"磁盘告警已发送到 {chat_id}（阈值 {threshold}%，via Telethon）")
            return
        except Exception as e:
            _log.error(f"Telethon 发送磁盘告警失败: {e}")

    _log.warning(f"磁盘告警阈值 {threshold}% 触发但未能发送（未配置 BOT_TOKEN 且无 Telethon client）")
