# SPDX-License-Identifier: AGPL-3.0-or-later
import time
import downloader.state as state
from common.logger import get_logger

_log = get_logger("downloader")


def make_progress(task_id: str, filename: str):
    last_print: list[float] = [0.0]
    last_bytes: list[int]   = [0]
    last_ts:    list[float] = [time.time()]

    async def _cb(current, total):
        pct        = int(current * 100 / total) if total else 0
        current_mb = round(current / 1048576, 1)
        total_mb   = round(total   / 1048576, 1) if total else 0
        now = time.time()
        dt  = now - last_ts[0]
        speed = (current - last_bytes[0]) / dt if dt > 0 else 0.0
        last_bytes[0] = current
        last_ts[0]    = now
        if task_id in state.active_downloads:
            state.active_downloads[task_id].update(
                current=current, total=total, pct=pct,
                current_mb=current_mb, size_mb=total_mb, status="downloading",
                speed=speed,
            )
        if now - last_print[0] >= 60:
            _log.info(f"  [{filename}] {pct}%  {current_mb}MB / {total_mb}MB")
            last_print[0] = now

    return _cb
