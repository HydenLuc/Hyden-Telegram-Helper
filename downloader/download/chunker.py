# SPDX-License-Identifier: AGPL-3.0-or-later
import time
import asyncio
from pathlib import Path

from telethon.errors import FileMigrateError

import downloader.state as state
import downloader.storage as storage
from downloader.tg.client import client
from common.logger import get_logger

_log = get_logger("downloader")


def _chunk_ranges(file_size: int, n: int) -> list[tuple[int, int]]:
    """把 file_size 字节分成 n 块，每块 offset 对齐到 CHUNK_SIZE。返回 [(offset, size), ...]。"""
    raw        = (file_size + n - 1) // n
    chunk_size = max(state.CHUNK_SIZE, ((raw + state.CHUNK_SIZE - 1) // state.CHUNK_SIZE) * state.CHUNK_SIZE)
    ranges: list[tuple[int, int]] = []
    offset = 0
    while offset < file_size:
        ranges.append((offset, min(chunk_size, file_size - offset)))
        offset += chunk_size
    return ranges


async def _chunked_download(task_id: str, message, file_path: Path,
                             n_chunks: int, file_size: int,
                             resume: bool = False) -> str:
    """P1-5c: resume=True 时，每个 chunk 检查 .partN 已写字节数，从那里续传。"""
    ranges      = _chunk_ranges(file_size, n_chunks)
    chunks_info = [{"id": i, "current": 0, "total": sz, "pct": 0, "speed": 0.0}
                   for i, (_, sz) in enumerate(ranges)]
    tmp_paths   = [file_path.with_name(f"{file_path.name}.part{i}")
                   for i in range(len(ranges))]

    if task_id in state.active_downloads:
        state.active_downloads[task_id]["chunks"] = chunks_info

    async def download_chunk(idx: int):
        offset_b, limit_b = ranges[idx]
        info = chunks_info[idx]
        tmp  = tmp_paths[idx]

        # P1-5c: 续传 — 检查已存在 .partN 文件大小作为本 chunk 的起点
        resume_skip = 0
        open_mode = "wb"
        if resume and tmp.exists():
            try:
                existing = tmp.stat().st_size
            except OSError:
                existing = 0
            if 0 < existing < limit_b:
                resume_skip = existing
                open_mode = "ab"
            elif existing >= limit_b:
                # 该 chunk 已经下完整或超额（异常），直接重头
                try: tmp.unlink()
                except OSError: pass

        for _dc_try in range(3):
            info["current"] = resume_skip
            prev_b = resume_skip
            prev_t = time.time()
            written = resume_skip
            try:
                # ⚠️ open() 必须走 executor，别改回直接 open。
                # 2026-08-18 实测：macOS 原生跑时 `with tmp.open(mode)` 会**永久阻塞**，
                # py-spy 栈固定停在 pathlib open → __open(libsystem_kernel)，
                # 打点确认「准备 open」打印了、「open 完成」永远不打印。
                # 诡异之处：所有孤立复现全部 0.0x 秒通过——同路径单独 open、6 协程并发 open、
                # 数万任务满载、client.start 之后、甚至换成本地盘（非 NFS）——
                # 只有真实服务里卡。共同点是此时事件循环里还跑着 Telethon 的连接协商
                # （下载要另开媒体 DC 并 export auth），同步 open 把循环占死就互锁。
                # 项目约定早就是「阻塞 I/O 一律 run_in_executor」，
                # 本函数的 _merge 遵守了，唯独这里没有——就是这个疏漏。
                _loop = asyncio.get_running_loop()
                fh = await _loop.run_in_executor(None, lambda: tmp.open(open_mode))
                try:
                    # iter_download 的 limit 参数含义是迭代次数（chunk 数），不是字节数。
                    # 不传 limit，改为手动计数字节并在达到 limit_b 时 break，
                    # 这样无论 Telethon 内部如何计数都能精确控制每个 worker 写入的字节数。
                    async for block in client.iter_download(
                        message.media,
                        offset=offset_b + resume_skip,
                        request_size=state.CHUNK_SIZE,
                        file_size=file_size,
                    ):
                        # Check cancel/pause before processing each block
                        ctrl = state.task_controls.get(task_id)
                        if ctrl:
                            if ctrl['cancel_flag']:
                                raise asyncio.CancelledError()
                            pause_ev = ctrl.get('pause_event')
                            if pause_ev and not pause_ev.is_set():
                                await pause_ev.wait()
                                if ctrl.get('cancel_flag'):
                                    raise asyncio.CancelledError()

                        remaining = limit_b - written
                        if remaining <= 0:
                            break
                        if len(block) > remaining:
                            block = block[:remaining]
                        # 同理走 executor：NFS 上单块写入也可能阻塞事件循环
                        await _loop.run_in_executor(None, fh.write, block)
                        written += len(block)
                        info["current"] = written

                        now = time.time()
                        dt  = now - prev_t
                        if dt >= 0.5:
                            info["speed"] = (written - prev_b) / dt
                            prev_b        = written
                            prev_t        = now

                        info["pct"] = int(written * 100 / limit_b) if limit_b else 0

                        if task_id in state.active_downloads:
                            total_cur = sum(c["current"] for c in chunks_info)
                            state.active_downloads[task_id].update(
                                current=total_cur,
                                pct=int(total_cur * 100 / file_size),
                                current_mb=round(total_cur / 1048576, 1),
                                speed=sum(c["speed"] for c in chunks_info),
                                status="downloading",
                            )

                            # P1-5c: 周期持久化 downloaded_bytes
                            # 粒度 N = max(1MB, file_size/100)，最坏丢 1% 进度
                            persist_threshold = max(1048576, file_size // 100)
                            pending_rec = state.pending_tasks.get(task_id)
                            if pending_rec is not None:
                                last_persisted = pending_rec.get("downloaded_bytes", 0)
                                if total_cur - last_persisted >= persist_threshold:
                                    pending_rec["downloaded_bytes"] = total_cur
                                    storage.save_pending_tasks(state.pending_tasks, key=task_id)

                        if written >= limit_b:
                            break
                finally:
                    await _loop.run_in_executor(None, fh.close)
                break  # success
            except FileMigrateError:
                if _dc_try >= 2:
                    raise
                await asyncio.sleep(1)   # Telethon 会在下次请求时切换到正确 DC

        info["speed"] = 0.0  # 该块完成后速度归零

    def _wipe_parts():
        for tmp in tmp_paths:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    chunk_tasks = [asyncio.create_task(download_chunk(i)) for i in range(len(ranges))]
    try:
        await asyncio.gather(*chunk_tasks)
    except (Exception, asyncio.CancelledError):
        for t in chunk_tasks:
            t.cancel()
        await asyncio.gather(*chunk_tasks, return_exceptions=True)
        _wipe_parts()
        raise

    # 所有块下载完成，按顺序合并。大文件（>2GB 走 6 分块）在 USB/网络盘上同步
    # 读写会冻住整个事件循环几十秒——其它下载、Telethon 心跳全部停摆，扔到
    # executor 线程里做，符合项目"阻塞 I/O 一律 run_in_executor"的约定。
    def _merge():
        with file_path.open("wb") as out:
            for tmp in tmp_paths:
                with tmp.open("rb") as inp:
                    while True:
                        buf = inp.read(1 << 20)
                        if not buf:
                            break
                        out.write(buf)
                tmp.unlink()

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _merge)
    except Exception as exc:
        _wipe_parts()
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
        raise RuntimeError(f"合并分块失败: {exc}") from exc

    return str(file_path)
