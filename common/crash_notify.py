# SPDX-License-Identifier: AGPL-3.0-or-later
"""崩溃通知（Telegram）。

支持两种发送方式（优先级从高到低）：
  1. BOT_TOKEN（推荐）→ 直接调 Telegram Bot HTTP API；不依赖 Telethon
  2. 复用调用方传入的 Telethon client（如 downloader 进程已登录）

ADMIN_CHAT_ID 为空时静默跳过（不报错），整个机制可选。

调用：
    from common.crash_notify import notify_crash
    await notify_crash("mover", "Connection refused")
"""
import asyncio
from datetime import datetime
from typing import Optional

import aiohttp

import config
from common.logger import get_logger

_log = get_logger("crash_notify")


def _build_message(module_name: str, error: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"⚠️ [{module_name}] 服务崩溃\n{error}\n{timestamp}"


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


async def notify_crash(module_name: str, error: str, *, telethon_client: Optional[object] = None) -> None:
    """异步崩溃通知。失败不抛异常。"""
    chat_id_raw = config.ADMIN_CHAT_ID
    if not chat_id_raw:
        return
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        _log.warning(f"ADMIN_CHAT_ID 必须是整数：{chat_id_raw!r}")
        return

    text = _build_message(module_name, error)

    bot_token = getattr(config, "BOT_TOKEN", "") or ""
    if bot_token:
        if await _send_via_bot_api(bot_token, chat_id, text):
            _log.info(f"崩溃通知已发送到 {chat_id} (via Bot API)")
            return

    if telethon_client is not None:
        try:
            await telethon_client.send_message(chat_id, text)
            _log.info(f"崩溃通知已发送到 {chat_id} (via Telethon)")
            return
        except Exception as e:
            _log.error(f"Telethon 发送崩溃通知失败: {e}")

    _log.warning(f"[{module_name}] 崩溃但未发送通知（未配置 BOT_TOKEN 且无 Telethon client）")


def notify_crash_sync(module_name: str, error: str) -> None:
    """同步包装：在没有 event loop 的环境（atexit/signal handler）里调用。"""
    if not config.ADMIN_CHAT_ID:
        return
    try:
        asyncio.run(notify_crash(module_name, error))
    except Exception as e:
        _log.error(f"sync notify_crash 失败: {e}")
