# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unzipper 监听：轮询扫描 WATCH_PATH。

改用轮询（scandir）而非 watchdog/inotify —— inotify 在 9p/drvfs（WSL 挂 Windows 盘、
E: 等）、部分网络/远程文件系统上**不产生事件**，导致 unzipper 对这些盘完全失明。
轮询 scandir 在任何文件系统都可靠，代价是最多 ~一个扫描间隔的延迟（对大压缩包无感）。

保持原接口 `start_watcher(queue)`；仍只处理 WATCH_PATH 的**直接子项**（不递归）。
分类与旧 watchdog 版一致：单包→'auto' 自动解压；.7z.001→'multipart' 待确认；目录→'folder' 待确认。
"""
import asyncio
import os
from pathlib import Path

import config
import unzipper.state as _ustate
from unzipper.extractor import find_multipart_parts
from unzipper.utils import (
    ARCHIVE_EXTS, dir_total_size, has_inprogress_files,
    is_ignored, is_multipart_part,
)
from common.logger import get_logger

_log = get_logger("unzipper")

# 扫描间隔（秒）。可用环境变量 UNZIPPER_SCAN_INTERVAL 覆盖，最低 2s。
_SCAN_INTERVAL = max(2.0, float(os.getenv("UNZIPPER_SCAN_INTERVAL", "10")))

_handled: set[str] = set()        # 本会话已入队路径，防重复入队
_last_size: dict[str, int] = {}   # 上一轮各候选大小，跨轮相等 => 稳定


def _classify(path: Path) -> str | None:
    """返回 'auto' / 'multipart' / 'folder'；不该处理返回 None。"""
    if is_ignored(path):
        return None
    try:
        if path.is_dir():
            return 'folder'
    except OSError:
        return None
    if is_multipart_part(path):                 # .7z.002+ 由 .001 带出，跳过
        return None
    low = path.name.lower()
    if low.endswith('.7z.001'):
        return 'multipart'
    if path.suffix.lower() in ARCHIVE_EXTS:
        return 'auto'
    return None


def _already_queued(path: Path) -> bool:
    """已在本会话入队 / 已在待确认队列里 => 不重复处理。"""
    sp = str(path)
    if sp in _handled:
        return True
    for rec in _ustate.pending_multipart.values():
        if str(rec.get('path')) == sp:
            return True
    return False


async def _scan_once(queue: asyncio.Queue):
    if _ustate.paused:                          # 软暂停：不扫描入队
        return
    wp = config.WATCH_PATH
    loop = asyncio.get_event_loop()
    try:
        entries = await loop.run_in_executor(None, lambda: list(os.scandir(wp)))
    except OSError:
        return

    seen: set[str] = set()
    for e in entries:
        path = Path(e.path)
        if path.name.startswith('.'):           # 隐藏项 / .mover_staging_*
            continue
        kind = _classify(path)
        if kind is None:
            continue
        sp = str(path)
        seen.add(sp)
        if _already_queued(path):
            continue
        # 稳定性判断（避免搬运/下载途中就入队）
        try:
            if kind == 'folder':
                if await loop.run_in_executor(None, has_inprogress_files, path):
                    _last_size[sp] = -1
                    continue
                size = await loop.run_in_executor(None, dir_total_size, path)
            elif kind == 'multipart':
                # 多卷包不能只看 .001 自身大小——.002/.003... 可能还在陆续到达。
                # 用"当前已到卷数 + 总字节数"做签名，尾卷还在到达时签名会持续变化，
                # 避免尾卷未到就被判定"稳定"从而过早开放确认（find_missing_volume
                # 只查中间缺号，查不出"后面还有卷没到"）。
                parts = await loop.run_in_executor(None, find_multipart_parts, path)
                size = (len(parts), sum(p.stat().st_size for p in parts))
            else:
                size = e.stat().st_size
        except OSError:
            continue
        prev = _last_size.get(sp)
        _last_size[sp] = size
        if prev is None or prev != size:
            continue                            # 与上一轮不一致 => 还在变，等下一轮
        _handled.add(sp)
        label = '多卷包' if kind == 'multipart' else ('文件夹' if kind == 'folder' else '压缩包')
        _log.info(f"[unzipper] 扫描发现{label}：{path.name}")
        await queue.put((kind, path))

    # 清理已消失路径的记录（解压后源被移出 / 被删）
    for gone in set(_last_size) - seen:
        _last_size.pop(gone, None)
        _handled.discard(gone)


async def start_watcher(queue: asyncio.Queue):
    if not config.WATCH_PATH:
        return
    config.WATCH_PATH.mkdir(parents=True, exist_ok=True)
    _log.info(
        f"Unzipper 轮询扫描已启动：{config.WATCH_PATH}"
        f"（每 {int(_SCAN_INTERVAL)}s；兼容 9p/drvfs/网络盘）"
    )
    while True:
        try:
            await _scan_once(queue)
        except Exception as ex:
            _log.error(f"[unzipper] 扫描异常：{ex}")
        await asyncio.sleep(_SCAN_INTERVAL)
