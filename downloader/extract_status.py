# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-8 Phase 2: 解压状态周期同步。

每 5 秒并发查询 mover 和 unzipper，将结果写回 state.completed_downloads
对应记录的 extract_status / extract_output_path 字段。

8 个状态值：
- not_archive: 不是压缩包（本地判断，无需查询）
- ready: 是压缩包但未提交 mover（如 AUTO_MOVE=false）
- moving: mover 任务 status=copying/pending
- move_failed: mover 任务 status=failed
- pending_extract: mover done 但 unzipper 还没看到 / 在 unzipper 队列等待
- extracting: unzipper current_tasks 里
- extracted: unzipper history 中 status=done
- extract_failed: unzipper history 中 status=failed
"""
import asyncio
import re
from pathlib import Path
from typing import Iterable

import aiohttp

import config
import downloader.state as state
import downloader.storage as storage
from common.constants import ARCHIVE_EXTS
from common.logger import get_logger

_log = get_logger("downloader")

REFRESH_INTERVAL = 5.0
# 多卷 7z（.7z.001 / .7z.002 / ...）：所有 part 都视为压缩包。
# 注意只有 .001 会被 unzipper 当首卷解压触发，其他 part 仅走 mover 流程
# （状态停留在 ready/moving，不会推进到 extracting/extracted）。
_MULTIPART_RE = re.compile(r'\.7z\.\d{3}$', re.IGNORECASE)


def _is_archive(filename: str) -> bool:
    if not filename:
        return False
    name = filename.lower()
    if _MULTIPART_RE.search(name):
        return True
    return Path(name).suffix in ARCHIVE_EXTS


async def _fetch_one_mover(session: aiohttp.ClientSession, task_id: str) -> dict | None:
    url = f"http://{config.MOVER_HOST}:{config.MOVER_PORT}/api/tasks/{task_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
            if resp.status == 200:
                return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass
    return None


def _likely_in_mover(task_id: str) -> bool:
    """task_id 是否可能存在于 mover 任务表里。

    `_hist_*` 后缀的历史下载任务**不会**经过 mover（mover 仅在下载完成时由
    auto_submit_to_mover 触发，且历史下载的 archive 多数还在排队/下载中），
    跳过这些避免每 5s 上千次 404 请求把 mover 的 access log 撑爆。
    """
    if not task_id:
        return False
    if "_hist_" in task_id:
        return False
    return True


async def _fetch_mover_states(task_ids: Iterable[str]) -> dict:
    # 过滤掉确定不在 mover 的 task_id
    task_ids = [tid for tid in task_ids if _likely_in_mover(tid)]
    if not task_ids:
        return {}
    headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
    async with aiohttp.ClientSession(headers=headers) as session:
        coros = [_fetch_one_mover(session, tid) for tid in task_ids]
        results = await asyncio.gather(*coros, return_exceptions=True)
    return {tid: r for tid, r in zip(task_ids, results) if isinstance(r, dict)}


async def _fetch_unzipper_states(filenames: Iterable[str]) -> dict:
    url = f"http://{config.UNZIPPER_HOST}:{config.UNZIPPER_PORT}/api/extract-status"
    headers = {"X-API-Key": config.API_KEY, "Content-Type": "application/json"} if config.API_KEY else {"Content-Type": "application/json"}
    payload = {"filenames": list(filenames)}
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
    return {}


def _compute_status(record: dict, mover_state: dict | None, unzipper_state: dict | None) -> tuple[str, str | None]:
    if not _is_archive(record.get("filename") or ""):
        return ("not_archive", None)

    # 优先看 unzipper（终态）
    if unzipper_state:
        s = unzipper_state.get("status")
        if s == "extracted":
            return ("extracted", unzipper_state.get("output_path"))
        if s == "extract_failed":
            return ("extract_failed", None)
        if s == "extracting":
            return ("extracting", None)
        if s == "pending_extract":
            return ("pending_extract", None)

    # 再看 mover
    if mover_state:
        ms = mover_state.get("status")
        if ms in ("copying", "pending"):
            return ("moving", None)
        if ms == "failed":
            return ("move_failed", None)
        if ms == "done":
            # mover done 但 unzipper 还没看到 → 在 unzipper 队列里 / 还未触发
            return ("pending_extract", None)

    # 不在 mover（如 AUTO_MOVE=false）也不在 unzipper
    return ("ready", None)


async def refresh_extract_statuses() -> None:
    """对 completed_downloads 里所有压缩包记录刷新 extract_status / extract_output_path。

    非压缩包记录直接标 not_archive 并返回。
    """
    archive_records = []
    for r in state.completed_downloads:
        fname = r.get("filename") or ""
        if not _is_archive(fname):
            r["extract_status"] = "not_archive"
            r["extract_output_path"] = None
        else:
            archive_records.append(r)

    if not archive_records:
        return

    task_ids = [r.get("task_id") for r in archive_records if r.get("task_id")]
    filenames = [Path(r["filename"]).name for r in archive_records]

    mover_states, unzipper_states = await asyncio.gather(
        _fetch_mover_states(task_ids),
        _fetch_unzipper_states(filenames),
    )

    changed = False
    for r in archive_records:
        old_status = r.get("extract_status")
        old_path = r.get("extract_output_path")
        new_status, new_path = _compute_status(
            r,
            mover_states.get(r.get("task_id")),
            unzipper_states.get(Path(r.get("filename") or "").name),
        )
        if new_status != old_status or new_path != old_path:
            r["extract_status"] = new_status
            r["extract_output_path"] = new_path
            changed = True

    if changed:
        # 持久化（已经在内存里更新；写盘以便重启后保留状态）
        try:
            storage.save_completed(state.completed_downloads)
        except Exception as e:
            _log.error(f"[extract_status] 保存 completed.json 失败: {e}")


async def refresh_loop() -> None:
    """周期任务：每 REFRESH_INTERVAL 秒刷新一次。"""
    while True:
        try:
            await refresh_extract_statuses()
        except Exception as e:
            _log.error(f"[extract_status] 刷新异常: {e}")
        await asyncio.sleep(REFRESH_INTERVAL)
