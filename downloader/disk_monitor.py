# SPDX-License-Identifier: AGPL-3.0-or-later
"""磁盘空间周期监测（60s）。

设计文档：docs/disk-space-design.md

- 写入 state.disk_usage（前端通过 /api/status 与 WebSocket 读取）
- 阈值跨过即发 Telegram 告警；标志位持久化到 downloader_settings.json
- pct_free > 20 自动 reset 所有标志位
- 不在 HTTP 请求处理器里做副作用，单一周期任务避免并发竞争
"""
import asyncio
import shutil
from datetime import datetime

import config
import downloader.state as state
import downloader.storage as storage
from common.disk_notify import notify_disk_warning
from common.logger import get_logger

_log = get_logger("disk_monitor")

CHECK_INTERVAL = 60  # 秒
THRESHOLDS = [20, 10, 5, 0]  # 百分比，从高到低
RESET_THRESHOLD = 20  # pct_free > 此值则清空所有 flag


def _default_alert_flags() -> dict:
    return {str(t): False for t in THRESHOLDS}


async def _check_once() -> None:
    """单次检测：刷新 state.disk_usage + 阈值判定。"""
    try:
        usage = shutil.disk_usage(config.DOWNLOAD_DIR)
        free, total = usage.free, usage.total
        pct = (free / total * 100) if total else 0.0
        state.disk_usage = {
            "free": free,
            "total": total,
            "pct_free": round(pct, 2),
            "checked_at": datetime.now().isoformat(),
            "error": None,
        }
        await _maybe_notify(pct, free, total)
    except Exception as e:
        state.disk_usage = {
            "free": 0,
            "total": 0,
            "pct_free": 0.0,
            "checked_at": datetime.now().isoformat(),
            "error": f"{type(e).__name__}: {e}",
        }
        _log.warning(f"磁盘检测失败：{type(e).__name__}: {e}")


async def _maybe_notify(pct: float, free: int, total: int) -> None:
    """阈值判定 + flag 维护。flag 持久化到 downloader_settings.json。"""
    settings = storage.load_settings()
    flags = settings.get("disk_alert_sent")
    if not isinstance(flags, dict):
        flags = _default_alert_flags()
        settings["disk_alert_sent"] = flags
    # 补齐缺失的键（升级时可能旧 settings 缺新阈值）
    for t in THRESHOLDS:
        flags.setdefault(str(t), False)

    # reset：恢复到 20% 以上 → 全清
    if pct > RESET_THRESHOLD:
        if any(flags.get(str(t)) for t in THRESHOLDS):
            for t in THRESHOLDS:
                flags[str(t)] = False
            settings["disk_alert_sent"] = flags
            storage.save_settings(settings)
            _log.info(f"磁盘恢复到 {pct:.1f}%（>{RESET_THRESHOLD}%），告警标志位已重置")
        return

    # 命中：每个未发过的阈值各发一次
    fired_any = False
    for t in THRESHOLDS:
        if pct <= t and not flags.get(str(t)):
            await notify_disk_warning(pct, free, total, threshold=t)
            flags[str(t)] = True
            fired_any = True
    if fired_any:
        settings["disk_alert_sent"] = flags
        storage.save_settings(settings)


async def disk_check_loop() -> None:
    """周期任务入口。被 main 调度为后台 task。"""
    _log.info(f"磁盘空间监测启动（每 {CHECK_INTERVAL}s 检测 {config.DOWNLOAD_DIR}）")
    # 启动后立即跑一次（不等 60s）
    await _check_once()
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)
            await _check_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.error(f"磁盘检测循环异常：{type(e).__name__}: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
