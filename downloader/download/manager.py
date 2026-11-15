# SPDX-License-Identifier: AGPL-3.0-or-later
import time
import asyncio
from datetime import datetime
from pathlib import Path

from telethon.errors import FloodWaitError, FloodPremiumWaitError
from telethon.tl.types import MessageMediaDocument

import config
import downloader.state as state
import downloader.storage as storage
from downloader.tg.client import client
from downloader.download.chunker import _chunked_download
from downloader.download.progress import make_progress
from downloader.mover_client import _should_auto_move, auto_submit_to_mover
from common.logger import get_logger

_log = get_logger("downloader")


# ── P1-5b helpers ─────────────────────────────────────────────────────────────

def _recompute_group_status(group: dict) -> tuple[str, str | None]:
    """根据 files 状态重新计算整组 status + completed_at（详见 reliability.md）。

    返回 (status, completed_at)：
      - 全部 done → ("done", now_iso)
      - 至少一个 done，但有非 done → ("partial", None)
      - 无 done，至少一个 downloading/waiting → ("downloading", None)
      - 全部 error 且无进行中 → ("error", None)
      - 空 → ("downloading", None)
    """
    files = group.get("files", {})
    statuses = [f.get("status") for f in files.values()]
    if not statuses:
        return ("downloading", None)
    n_done = sum(1 for s in statuses if s == "done")
    n_active = sum(1 for s in statuses if s in ("downloading", "waiting"))
    n_error = sum(1 for s in statuses if s == "error")
    if n_done == len(statuses):
        return ("done", datetime.now().isoformat())
    if n_done > 0:
        return ("partial", None)
    if n_active > 0:
        return ("downloading", None)
    if n_error == len(statuses):
        return ("error", None)
    return ("downloading", None)


def _gs_key_for(rec: dict) -> str:
    """从 active_downloads 或 completed 记录提取 grouped_state 索引键。"""
    gid = rec.get("grouped_id")
    chat_id = rec.get("chat_id")
    task_id = rec.get("task_id")
    return f"{chat_id}_{gid}" if gid else task_id


# ── P1-5b: 启动恢复扫描 ──────────────────────────────────────────────────────

def _gs_key_from_pending(task_id: str, rec: dict) -> str:
    """从 pending_tasks 记录提取 grouped_state 索引键（pending rec 没 task_id 字段）。"""
    gid = rec.get("grouped_id")
    chat_id = rec["chat_id"]
    return f"{chat_id}_{gid}" if gid else task_id


def _mark_recovered_done(task_id: str, rec: dict) -> None:
    """分支 2：文件大小完全匹配 → 视为已完成，清理 pending + 更新 grouped_state。"""
    if task_id in state.pending_tasks:
        del state.pending_tasks[task_id]
        storage.save_pending_tasks(state.pending_tasks, key=task_id)

    gs_key = _gs_key_from_pending(task_id, rec)
    group = state.grouped_state.get(gs_key)
    if group and task_id in group.get("files", {}):
        group["files"][task_id]["status"] = "done"
        group["files"][task_id]["save_path"] = rec["save_path"]
        group["files"][task_id]["expected_size"] = rec.get("expected_size")
        new_status, completed_at = _recompute_group_status(group)
        group["status"] = new_status
        group["completed_at"] = completed_at
        group["done_files"] = sum(
            1 for f in group["files"].values() if f.get("status") == "done"
        )
        storage.save_grouped_state(state.grouped_state, key=gs_key)


async def _recover_one(task_id: str, rec: dict, await_download: bool = False) -> None:
    """处理单个 pending 任务的恢复。按 reliability.md 4 分支逻辑判定。"""
    save_path = Path(rec["save_path"])
    expected = rec.get("expected_size", 0)
    chat_id = rec["chat_id"]
    message_id = rec["message_id"]

    # P1-5c: 续传判定（崩溃恢复也走续传路径）
    can_resume = (
        rec.get("downloaded_bytes", 0) > 0
        and not rec.get("last_resume_failed", False)
    )

    # 4 分支判定（按 reliability.md）
    if not save_path.exists():
        branch_label = "1（文件不存在）"
        # P1-5c：保留 .partN 续传可能；无 save_path 但 .partN 存在的场景由 chunker 内部决定
    elif expected > 0 and save_path.stat().st_size == expected:
        # 分支 2：完整文件 → 视为完成，无需重下
        _log.info(f"[recover] {task_id}: 分支 2（大小匹配 {expected} 字节）→ 标记完成")
        _mark_recovered_done(task_id, rec)
        return
    elif save_path.stat().st_size < expected:
        # P1-5c: 不再 unlink；让 chunker 续传逻辑接管（如果可以续传）
        branch_label = f"3（文件不完整 {save_path.stat().st_size}/{expected}{'，续传' if can_resume else '，重下'}）"
        if not can_resume:
            try: save_path.unlink()
            except OSError: pass
    else:  # > expected（异常）
        actual = save_path.stat().st_size
        _log.warning(f"[recover] ⚠ {task_id}: 文件大小 {actual} > expected {expected}（异常状态）")
        branch_label = f"4（大小超出预期）"
        try:
            save_path.unlink()
        except OSError:
            pass

    # 防并发：task_id 已在 active_downloads（用户手动重试已抢先接管）时跳过，
    # 否则两个 download_one 并发写同一批 .partN 会互相破坏。
    if task_id in state.active_downloads:
        _log.info(f"[recover] {task_id}: 已有并发下载在跑（重试已抢先），跳过恢复")
        return

    # 父目录可能不在：恢复时目录是原下载建的，换了存储介质（2026-08-12 从本地盘
    # 迁到 NAS 的 NFS）后目录还没同步过去，chunker 直接写 .partN 会 FileNotFoundError。
    # 建目录是幂等的，正常路径下这行什么也不做。
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log.warning(f"[recover] ⚠ {task_id}: 建目录失败 {save_path.parent}: {e}")

    # 重下：先 get_messages 重取 message（防 file_reference 过期），再启动 download_one
    _log.info(f"[recover] {task_id}: 分支 {branch_label} → 重新下载")
    try:
        message = await client.get_messages(chat_id, ids=message_id)
    except Exception as e:
        _log.warning(f"[recover] ⚠ 获取消息失败 {task_id}: {e}，从 pending 删除")
        if task_id in state.pending_tasks:
            del state.pending_tasks[task_id]
            storage.save_pending_tasks(state.pending_tasks, key=task_id)
        return

    if message is None or not message.media:
        _log.info(f"[recover] {task_id}: 消息已不存在或无媒体，从 pending 删除")
        if task_id in state.pending_tasks:
            del state.pending_tasks[task_id]
            storage.save_pending_tasks(state.pending_tasks, key=task_id)
        return

    # 启动新的 download_one（task_id 复用，save_path 沿用原路径）
    # P1-5c: 崩溃恢复带 can_resume 标志；source 沿用 pending 记录（默认 realtime）
    label = f"recover/{save_path.name}"
    t = asyncio.create_task(download_one(
        task_id, message, save_path, label,
        chat_id=chat_id, message_id=message_id,
        resume=can_resume,
        source=rec.get("source", "realtime"),
    ))
    state.task_outer_tasks[task_id] = t
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)

    # worker 池模式：占着这个 worker 直到下载结束，从而把「同时活着的下载协程数」
    # 限制在 RECOVER_WORKERS 个。仍然用 create_task 而不是直接 await 协程，
    # 是为了保留 task_outer_tasks 的可取消性（Web UI 的「终止」按钮依赖它）。
    if await_download:
        try:
            await t
        except asyncio.CancelledError:
            raise                      # 取消要往上传，别吞
        except Exception:
            pass                       # 单个下载失败不该弄死 worker，download_one 内部已记日志


def stalled_tasks(now: float | None = None) -> list[str]:
    """挑出「该重试的搁置任务」。

    搁置 = 在 pending_tasks 里、但**没有任何协程在管它**。
    2026-09-17 之前这类任务只有服务重启才会被再碰一次 —— 界面上它们混在
    「队列」里看着像在排队，实际躺了一个多月（hyden 报的「队列 18 但只有 1 个在下」）。

    退避规则：失败越多等越久（间隔 × 2^retry_count），封顶 24 小时。
    没有退避的话，一个永远下不成的任务会把连接预算吃光、正常任务排不进来。
    """
    now = time.time() if now is None else now
    base = max(60, config.STALLED_RETRY_INTERVAL)
    out = []
    for task_id, rec in list(state.pending_tasks.items()):
        # ⚠️ 已经有协程在下就别碰 —— 同一个 task_id 起两次会互相踩踏
        #    （run_id 守卫能防数据损坏，但白下一遍几个 GB 没人能防）
        if task_id in state.active_downloads:
            continue
        rc = rec.get("retry_count") or 0
        backoff = min(base * (2 ** min(rc, 5)), 24 * 3600)
        if now - (rec.get("last_attempt_at") or 0) < backoff:
            continue
        out.append(task_id)
    return out


async def retry_stalled_once() -> int:
    """重试一批搁置任务，返回本次真正发起的条数。"""
    cands = stalled_tasks()
    if not cands:
        return 0
    batch = cands[:max(1, config.STALLED_RETRY_BATCH)]
    _log.info(f"[stalled] 搁置任务 {len(cands)} 个，本轮重试 {len(batch)} 个")
    started = 0
    for task_id in batch:
        rec = state.pending_tasks.get(task_id)
        if rec is None or task_id in state.active_downloads:
            continue
        # 先记时间戳再发起：就算下面抛异常，退避也已经生效，
        # 不会因为反复抛错而变成紧循环。
        rec["last_attempt_at"] = time.time()
        storage.save_pending_tasks(state.pending_tasks, key=task_id)
        try:
            await _recover_one(task_id, rec)
            started += 1
        except Exception as e:
            _log.warning(f"[stalled] {task_id} 重试发起失败: {type(e).__name__}: {e}")
    return started


async def stalled_retry_loop() -> None:
    """周期性把搁置任务捞起来重试。

    为什么需要：`recover_pending_tasks` **只在启动时跑一次**，跑完还失败的
    就永远躺在 pending 里。配上 2026-09-17 修好的 .partN 保留，
    每次重试都能从上次断点接着下，大文件才有跑完的一天。
    """
    while True:
        await asyncio.sleep(max(60, config.STALLED_RETRY_INTERVAL))
        try:
            await retry_stalled_once()
        except Exception as e:
            # 这个循环挂了就再也没人管搁置任务了，任何异常都得吞掉continue
            _log.error(f"[stalled] 重试循环出错（已继续）: {type(e).__name__}: {e}")


async def recover_pending_tasks() -> None:
    """启动恢复扫描：处理 pending_tasks.json 中的所有未完成任务。

    必须在 client.start() 之后调用（需要 get_messages 重取 message 防 file_reference 过期）。
    详见 downloader/docs/reliability.md "crash 恢复扫描" 章节。
    """
    if not state.pending_tasks:
        return

    n_workers = max(1, config.RECOVER_WORKERS)
    _log.info(f"[recover] 启动恢复扫描：{len(state.pending_tasks)} 个 pending 任务"
              f"（{n_workers} 个 worker 并发）")

    # ⚠️ 别退回「给每个任务 create_task」的写法（2026-08-18 之前就是那样）：
    #    数万个活协程全部阻塞在连接预算的 Condition 上，而释放连接用的是
    #    notify_all —— 每次释放唤醒全部几万个。实测 downloader 78% CPU 只跑
    #    3MB/s；迁到一台 Mac 后一个 2.43GB(需 6 连接)的文件直接卡死不动。
    #    worker 池把活协程数钉在 RECOVER_WORKERS，惊群消失。
    q: asyncio.Queue = asyncio.Queue()
    # 拷贝 keys（处理过程中 state.pending_tasks 会被分支 2 修改）
    for task_id in list(state.pending_tasks.keys()):
        q.put_nowait(task_id)

    async def _worker(idx: int):
        while True:
            try:
                task_id = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                rec = state.pending_tasks.get(task_id)
                if rec is not None:      # 可能已被别的分支删掉
                    await _recover_one(task_id, rec, await_download=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _log.warning(f"[recover] ⚠ {task_id} 恢复异常 {type(e).__name__}: {e}")
            finally:
                q.task_done()

    workers = [asyncio.create_task(_worker(i)) for i in range(n_workers)]
    try:
        await asyncio.gather(*workers)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()
    _log.info(f"[recover] 启动恢复扫描完成")


def _adaptive_chunks(file_size) -> int:
    # 应急开关：见 config.DISABLE_CHUNKED 的说明（2026-08-18 定位 macOS 上的卡死用）
    if config.DISABLE_CHUNKED:
        return 1
    if file_size is None or file_size <   50 * 1024 * 1024:  return 1  # <50 MB
    if file_size              <  500 * 1024 * 1024:           return 2  # 50–500 MB
    if file_size              < 2048 * 1024 * 1024:           return 4  # 500 MB–2 GB
    return 6                                                             # >2 GB


async def _acquire_connections(n: int, is_small_file: bool = False, source: str = "realtime"):
    """硬预留模式：
    - 小文件可用全部连接；大文件只能用 (MAX - RESERVED)。
    - source="history" 任务额外受 floor(MAX * HISTORY_CONN_FRACTION) 子配额限制，
      避免历史回拉打满全部连接饿死实时下载。
    """
    async with state._conn_gate:
        total_cap = (
            state.MAX_TOTAL_CONNECTIONS
            if is_small_file
            else state.MAX_TOTAL_CONNECTIONS - config.SMALL_FILE_RESERVED_CONNECTIONS
        )
        history_cap = max(1, int(state.MAX_TOTAL_CONNECTIONS * config.HISTORY_CONN_FRACTION))
        while True:
            if state._total_connections + n > total_cap:
                pass   # 总配额满
            elif source == "history" and state._history_connections + n > history_cap:
                pass   # 历史子配额满
            else:
                break
            await state._conn_gate.wait()
        state._total_connections += n
        if source == "history":
            state._history_connections += n


async def _release_connections(n: int, source: str = "realtime"):
    async with state._conn_gate:
        state._total_connections = max(0, state._total_connections - n)
        if source == "history":
            state._history_connections = max(0, state._history_connections - n)
        # ⚠️ 必须是 notify_all()，别"优化"成 notify(n)：
        #    等待者的条件是**异构的**——有的要 1 条连接，有的要 6 条（大文件分块）。
        #    notify(n) 唤醒的若恰好是要 6 条的那个，它重判后继续睡，
        #    而只要 1 条、本可以立刻跑的那个没被叫醒 → 连接空着没人用，饿死。
        #    惊群的真正解法是**减少等待者数量**（见 recover_pending_tasks 的 worker 池），
        #    不是减少唤醒数量。等待者压到个位数后 notify_all 的开销可以忽略。
        state._conn_gate.notify_all()


# 下载结束的原因 → 要不要把 .partN 一起删掉。
#
# 🔴 这条规则 2026-09-17 之前散在 6 个 if 里，其中两个是错的，后果是大文件
#    永远下不完的永动机（见 _cleanup_parts 的说明）。提成具名函数是为了：
#    ① 每个调用点自己说清楚「我是因为什么结束的」
#    ② 规则能被测试钉住，不会再被谁顺手改回去
_PURGE_REASONS = frozenset({
    "manual_cancel",     # 用户点了取消——他不要这个文件了
    "resume_fallback",   # 续传确实失败，要回退重头下，旧分块可能是坏的
    "gave_up",           # 重试用尽/不可恢复错误，不再继续
})
_KEEP_REASONS = frozenset({
    "stall_timeout",     # 60s 无进度。**最需要续传的时刻**，删了就是永动机
    "flood_wait",        # 临时限流，等一会儿就能接着下
})


def _should_purge_parts(reason: str) -> bool:
    """按结束原因决定是否清掉 .partN。

    未知原因一律**保守保留** —— 宁可多占点盘，也别再把几个 GB 的进度丢掉。
    """
    return reason in _PURGE_REASONS


def _cleanup_parts(file_path: Path, n: int):
    """删掉所有 .partN，让下次从头开始。

    🔴 **只在「确实要从零重来」时调用**，就两种：
      ① 用户手动取消（他不要这个文件了）
      ② 续传确实失败、要回退重头下（fallback）

    ⚠️ **超时和 FloodWait 都不算**。2026-09-17 之前这两处也在删，后果是
    大文件永远下不完的永动机：下 3.5 GB → 尾部某个分块卡住 → 60s 无进度 →
    **删光所有分块** → 下次从 0 开始 → 再下 3.5 GB → 再卡 → 再删。
    11 个任务这么循环了一个多月，每轮烧 3.5 GB 带宽，一个都没成。
    而整套续传机制（chunker 读 .partN 已有字节接着下）是好的，
    只是永远没有 .partN 可读——被这一行清干净了。
    """

    for i in range(n):
        tmp = file_path.with_name(f"{file_path.name}.part{i}")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# 每次 download_one 调用发一个递增号。同一个 task_id 会被重试/恢复复用，
# 靠这个号区分「哪一次调用才是当家的那次」。见 _finish 的注释。
_RUN_SEQ = 0


def _next_run_id() -> int:
    global _RUN_SEQ
    _RUN_SEQ += 1
    return _RUN_SEQ


def _finish(task_id: str, status: str, error_msg: str = "", run_id: int | None = None):
    """收尾一个任务：从 active_downloads 摘下来并归档。

    ⚠️ `run_id` 不是可选的装饰——**同一个 task_id 可能同时有两个 download_one 在跑**
    （用户重试、启动恢复扫描都复用原 task_id）。老的那次被超时看门狗 cancel 之后，
    它的收尾逻辑会继续执行；如果不认 run_id，它就会把**新那次**刚建好的记录 pop 掉。
    后果见 2026-09-17：新那次接着写 `active_downloads[task_id][...]` 直接 KeyError，
    `download_one` 整个崩掉 → 收尾没跑完 → 任务**永久卡在 pending_tasks 里**，
    而且崩的形式是 asyncio 的「Task exception was never retrieved」，
    连错误计数都进不去，11 个任务就这么在队列里躺了一个多月。
    """
    rec = state.active_downloads.get(task_id)
    if rec is None:
        return
    if run_id is not None and rec.get("_run") != run_id:
        # 自己已经被新的一次顶替了，什么都别动
        return
    state.active_downloads.pop(task_id, None)
    rec.update(status=status, finished_at=time.time(), error_msg=error_msg)
    if status == "done":
        rec["pct"] = 100
        file_path = Path(rec.get("path", ""))
        if file_path.exists() and _should_auto_move(file_path):
            asyncio.create_task(
                auto_submit_to_mover(file_path, config.WATCH_PATH, rec["task_id"])
            )
        # MD5 dedup: 异步算 MD5 + 索引（fire-and-forget；与 mover race 由 worker 内部容错）
        if file_path.exists() and not rec.get("skip_md5_index"):
            from downloader.md5_worker import _compute_and_index, _resolve_source_label
            asyncio.create_task(_compute_and_index(
                task_id=rec["task_id"],
                file_path=file_path,
                fuid_key=rec.get("fuid_key"),
                filename=rec.get("filename", ""),
                size=rec.get("total", 0),
                chat_id=rec.get("chat_id"),
                message_id=rec.get("message_id"),
                source_label=_resolve_source_label(rec.get("chat_id")),
                finished_at_iso=datetime.now().isoformat(),
            ))
    state.completed_downloads.insert(0, rec)
    if len(state.completed_downloads) > config.MAX_HISTORY:
        state.completed_downloads.pop()
    storage.save_completed(state.completed_downloads)

    # ── P1-5b: 同步维护 pending_tasks + grouped_state ────────────────────
    gs_key = _gs_key_for(rec)
    pending_changed = False
    grouped_changed = False

    if status == "done":
        # 成功完成：从 pending 删除
        if task_id in state.pending_tasks:
            del state.pending_tasks[task_id]
            pending_changed = True
        # 更新 grouped_state：file status → done + 重算组 status
        group = state.grouped_state.get(gs_key)
        if group and task_id in group.get("files", {}):
            group["files"][task_id]["status"] = "done"
            group["files"][task_id]["save_path"] = rec.get("path") or None
            group["files"][task_id]["expected_size"] = rec.get("total") or None
            new_status, completed_at = _recompute_group_status(group)
            group["status"] = new_status
            group["completed_at"] = completed_at
            group["done_files"] = sum(
                1 for f in group["files"].values() if f.get("status") == "done"
            )
            grouped_changed = True
    else:
        # error / timeout / cancelled：保留 pending（用于重启恢复或手动重试）
        # 仅更新 grouped_state 该 file status → error，重算组 status
        group = state.grouped_state.get(gs_key)
        if group and task_id in group.get("files", {}):
            group["files"][task_id]["status"] = "error"
            new_status, completed_at = _recompute_group_status(group)
            group["status"] = new_status
            group["completed_at"] = completed_at
            grouped_changed = True

    if pending_changed:
        storage.save_pending_tasks(state.pending_tasks, key=task_id)
    if grouped_changed:
        storage.save_grouped_state(state.grouped_state, key=gs_key)


async def download_one(task_id: str, message, file_path: Path, label: str,
                       chat_id: int = 0, message_id: int = 0,
                       resume: bool = False,
                       source: str = "realtime"):
    """P1-5c: resume=True → 多 chunk 路径走续传（每 chunk 从已写字节数继续）。

    单连接（n_conns=1）路径不支持续传（client.download_media 不暴露 offset），
    resume=True 会被静默降级为 resume=False。

    source: "realtime" | "history"，标记任务来源（M7：v1 仅持久化不区分显示）。
    """
    from downloader.web.websocket import _broadcast

    file_size  = message.media.document.size if isinstance(message.media, MessageMediaDocument) else None
    n_conns    = _adaptive_chunks(file_size)
    use_chunks = n_conns > 1

    # P1-5c: 单连接路径不支持续传
    effective_resume = resume and use_chunks

    # Set up per-task pause/cancel controls
    pause_event = asyncio.Event() if use_chunks else None
    if pause_event:
        pause_event.set()   # start in running state
    state.task_controls[task_id] = {
        'pause_event': pause_event,
        'cancel_flag': False,
        'dl_task':     None,
    }

    # P1-5b: 提取 grouped_id 用于 active_downloads 字段 + pending_tasks 持久化
    gid = str(message.grouped_id) if getattr(message, "grouped_id", None) else None

    # MD5 dedup: 提取 fuid_key（document.id / photo.id）用于 _finish 后的 MD5 索引
    from downloader.md5_worker import _extract_fuid as _md5_extract_fuid
    fuid_key = _md5_extract_fuid(message)

    run_id = _next_run_id()

    def _own():
        """拿到**属于本次调用**的 active 记录；已被新的一次顶替就返回 None。

        所有对 active_downloads[task_id] 的写入都要过这里。直接硬索引的后果
        见 _finish 的注释（2026-09-17 的 KeyError + 任务永久卡死）。
        """
        rec = state.active_downloads.get(task_id)
        return rec if rec is not None and rec.get("_run") == run_id else None

    state.active_downloads[task_id] = dict(
        _run=run_id,
        task_id=task_id, label=label, filename=file_path.name,
        current=0, total=file_size or 0, pct=0, current_mb=0.0,
        size_mb=round((file_size or 0) / 1048576, 1),
        status="waiting", queued_at=time.time(), started_at=None, finished_at=None,
        error_msg="",
        path="", dir="", speed=0.0,
        chat_id=chat_id, message_id=message_id,
        grouped_id=gid,
        chunks=([] if use_chunks else None),
        flood_until=None,
        n_conns=n_conns,
        fuid_key=fuid_key,
        source=source,
    )

    # P1-5b/5c: pending_tasks 持久化（保留已有 retry_count / last_resume_failed / downloaded_bytes）
    existing_pending = state.pending_tasks.get(task_id, {})
    state.pending_tasks[task_id] = {
        "chat_id":            chat_id,
        "message_id":         message_id,
        "save_path":          str(file_path),
        "expected_size":      file_size or 0,
        "grouped_id":         gid,
        "queued_at":          existing_pending.get("queued_at") or datetime.now().isoformat(),
        "downloaded_bytes":   existing_pending.get("downloaded_bytes", 0) if effective_resume else 0,
        "retry_count":        existing_pending.get("retry_count", 0),
        "last_resume_failed": existing_pending.get("last_resume_failed", False),
        # 上次真正开下的时间戳，给「搁置任务周期性重试」做退避用（见 stalled_retry_loop）。
        # 不记的话重启后退避就归零，会在开机瞬间把所有失败任务一起重试。
        "last_attempt_at":    time.time(),
        "source":             source,
    }
    storage.save_pending_tasks(state.pending_tasks, key=task_id)

    await _broadcast()

    acquired = False
    try:
        # ── Phase 1: wait for connection budget ───────────────────────────────
        is_small_file = (file_size or 0) < config.SMALL_FILE_THRESHOLD_MB * 1024 * 1024
        try:
            await _acquire_connections(n_conns, is_small_file=is_small_file, source=source)
        except asyncio.CancelledError:
            _finish(task_id, "error", "已手动取消", run_id=run_id)
            if not state.active_downloads:
                _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
            return
        acquired = True

        # ── 排到位后刷新 message（防 file_reference 在排队期间过期）───────────────
        # 根因：file_reference 有时效，任务在队列里等太久，轮到下载时旧引用已失效 →
        # FileReferenceExpiredError。此处（真正开始下载前）用 chat_id/message_id 重取
        # 一次新鲜 message，拿到有效 file_reference 再下。
        if chat_id and message_id:
            try:
                fresh = await client.get_messages(chat_id, ids=message_id)
                if fresh is None:
                    _finish(task_id, "error", "消息已被删除或撤回，无法下载", run_id=run_id)
                    if not state.active_downloads:
                        _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
                    return
                if fresh.media:
                    message = fresh          # 用新鲜引用替换旧的
            except Exception as _e:
                # 刷新失败不致命：沿用原 message，下载阶段仍有异常/FloodRetry 兜底
                _log.warning(f"  [{label}] 刷新 file_reference 失败（{_e}），沿用原引用")

        size_str = f"{file_size // (1024*1024)}MB" if file_size else "未知大小"
        mode     = f"分块×{n_conns}" if use_chunks else "单连接"
        _log.info(f"  [开始] [{label}] {file_path.name}  ({size_str}  {mode}  超时: {config.DOWNLOAD_TIMEOUT}s)")

        # ── Phase 2: download attempts ────────────────────────────────────────
        # P1-5c: 续传一次失败后允许 fallback 重头（仅一次，避免死循环）
        resume_attempt = effective_resume
        fallback_used = False
        try:
            for attempt in range(config.FLOOD_RETRY_MAX + 1):
                if attempt > 0:
                    _rec = _own()
                    if _rec is None:
                        return          # 已被新的一次顶替，安静退出
                    _rec.update(
                        current=0, pct=0, current_mb=0.0, speed=0.0,
                        chunks=([] if use_chunks else None), flood_until=None,
                    )
                    # P1-5c: FloodWait 重试不应破坏续传进度（只清最终文件，留 .partN）
                    # 但 _cleanup_parts 是为 FloodWait/失败设计的——续传场景下保留 .partN
                    if use_chunks and not resume_attempt:
                        _cleanup_parts(file_path, n_conns)
                    if file_path.exists():
                        file_path.unlink()

                # P1-5a Q7：每次 attempt 开始下载流量时刷新 started_at
                # ⚠️ 这两行 2026-09-17 之前是硬索引，被顶替后直接 KeyError（见 _finish 注释）
                _rec = _own()
                if _rec is None:
                    return              # 已被新的一次顶替，安静退出
                _rec["started_at"] = time.time()
                _rec["status"] = "downloading"

                if use_chunks:
                    dl_task = asyncio.create_task(
                        _chunked_download(task_id, message, file_path, n_conns, file_size,
                                          resume=resume_attempt)
                    )
                else:
                    dl_task = asyncio.create_task(
                        client.download_media(
                            message, file=file_path,
                            progress_callback=make_progress(task_id, file_path.name),
                        )
                    )
                state.task_controls[task_id]['dl_task'] = dl_task

                async def _stall_watchdog(_dl=dl_task):
                    last_bytes   = -1
                    last_advance = time.time()
                    while not _dl.done():
                        await asyncio.sleep(10)
                        rec = state.active_downloads.get(task_id, {})
                        if rec.get("status") == "paused":
                            # 用户主动暂停：字节数本就不会推进，不能计入停滞超时，
                            # 否则暂停超过 DOWNLOAD_TIMEOUT 就会被误杀、.partN 被清掉。
                            last_advance = time.time()
                            continue
                        # ⚠️ FloodWait 同理（2026-09-17 补）：Telegram 限流期间所有分块
                        #    都在 sleep，进度当然是零 —— 那是**正常等待**不是卡死。
                        #    原来只豁免了 paused，`flood_until` 只喂给前端显示倒计时、
                        #    看门狗根本不看，于是大文件被限流几十秒就被误杀。
                        #    本轮日志里 FloodWait 上百次，退避 4~9 秒起，叠加起来很容易破 60 秒。
                        _fu = rec.get("flood_until")
                        if _fu and time.time() < _fu:
                            last_advance = time.time()
                            continue
                        cur = rec.get("current", 0)
                        if cur != last_bytes:
                            last_bytes   = cur
                            last_advance = time.time()
                        elif time.time() - last_advance >= config.DOWNLOAD_TIMEOUT:
                            _log.error(f"  ✗ [{label}] 超过 {config.DOWNLOAD_TIMEOUT}s 无进度，取消下载")
                            _dl.cancel()
                            return

                watchdog = asyncio.create_task(_stall_watchdog())
                try:
                    path = await dl_task
                    watchdog.cancel()
                    if path:
                        _rec = _own()
                        if _rec is None:
                            return
                        _rec["path"] = str(path)
                        _rec["dir"]  = str(Path(path).parent)
                        _finish(task_id, "done", run_id=run_id)
                        _log.info(f"  ✓ [{label}] 已保存: {path}")
                    else:
                        _finish(task_id, "error", "无法下载此媒体类型", run_id=run_id)
                        _log.warning(f"  ⚠ [{label}] 此媒体类型无法下载")
                    if not state.active_downloads:
                        _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
                    break

                except (FloodWaitError, FloodPremiumWaitError) as e:
                    watchdog.cancel()
                        # ⚠️ FloodWait 是**临时限流**，等一会儿就能接着下 ——
                        #    为它丢掉几个 GB 的分块进度毫无道理（本轮日志里 FloodWait
                        #    上百次，每次都清等于大文件永远下不完）。这里不再清 .partN；
                        #    真需要从零重来由下面的 fallback 分支负责。
                    if attempt >= config.FLOOD_RETRY_MAX:
                        if file_path.exists():
                            file_path.unlink()
                        _finish(task_id, "error", f"FloodWait 触发 {config.FLOOD_RETRY_MAX + 1} 次，已放弃", run_id=run_id)
                        _log.error(f"  ✗ [{label}] FloodWait 超过最大重试次数，放弃下载")
                        if not state.active_downloads:
                            _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
                        break
                    backoff   = 5 * (2 ** attempt)
                    wait_secs = e.seconds + backoff
                    kind      = "FloodPremiumWait" if isinstance(e, FloodPremiumWaitError) else "FloodWait"
                    _log.info(f"  ⏳ [{label}] {kind} {e.seconds}s + 退避 {backoff}s = 共等 {wait_secs}s，重试 {attempt + 1}/{config.FLOOD_RETRY_MAX}")
                    _rec = _own()
                    if _rec is None:
                        return
                    _rec.update(
                        status="flood_wait",
                        flood_until=time.time() + wait_secs,
                        speed=0.0,
                    )
                    await _broadcast()
                    try:
                        await asyncio.sleep(wait_secs)
                    except asyncio.CancelledError:
                        # 在 FloodWait 等待期间被取消。同上：只有手动取消才清分块，
                        # 停滞超时得把 .partN 留着给下次续传。
                        _ctrl = state.task_controls.get(task_id)
                        if use_chunks and _should_purge_parts(
                                "manual_cancel" if (_ctrl and _ctrl.get('cancel_flag')) else "stall_timeout"):
                            _cleanup_parts(file_path, n_conns)
                        if file_path.exists():
                            file_path.unlink()
                        _finish(task_id, "error", "已手动取消", run_id=run_id)
                        if not state.active_downloads:
                            _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
                        return

                except asyncio.CancelledError:
                    watchdog.cancel()
                    ctrl = state.task_controls.get(task_id)
                    manual_cancel = bool(ctrl and ctrl.get('cancel_flag'))
                    # 🔴 只有**手动取消**才清分块。停滞超时必须保留 .partN ——
                    #    那恰恰是最需要续传的时刻（见 _cleanup_parts 的说明）。
                    if use_chunks and _should_purge_parts(
                            "manual_cancel" if manual_cancel else "stall_timeout"):
                        _cleanup_parts(file_path, n_conns)
                    # 分块模式下 file_path 是最后才拼出来的，中途本就不该存在；
                    # 单连接模式不支持续传，留半截文件没意义 → 该删。
                    if file_path.exists() and (manual_cancel or not use_chunks):
                        file_path.unlink()
                    if manual_cancel:
                        _finish(task_id, "error", "已手动取消", run_id=run_id)
                    else:
                        _finish(task_id, "timeout", f"超过 {config.DOWNLOAD_TIMEOUT}s 无进度，已取消（.partN 保留，下次续传）", run_id=run_id)
                    if not state.active_downloads:
                        _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
                    break

                except Exception as e:
                    watchdog.cancel()
                    # P1-5c: 续传失败时允许一次 fallback 重头（只允许一次，避免死循环）
                    if resume_attempt and not fallback_used:
                        _log.warning(f"  ⚠ [{label}] 续传失败 ({type(e).__name__}: {e})，回退重头下载")
                        if use_chunks and _should_purge_parts("resume_fallback"):
                            _cleanup_parts(file_path, n_conns)
                        if file_path.exists():
                            try: file_path.unlink()
                            except OSError: pass
                        # 标记并清进度
                        if task_id in state.pending_tasks:
                            state.pending_tasks[task_id]["downloaded_bytes"] = 0
                            state.pending_tasks[task_id]["last_resume_failed"] = True
                            storage.save_pending_tasks(state.pending_tasks, key=task_id)
                        resume_attempt = False
                        fallback_used = True
                        continue   # retry attempt 不消耗 FloodWait quota（实际上仍会消耗，但 fallback 只一次，可接受）

                    if use_chunks:
                        _cleanup_parts(file_path, n_conns)
                    if file_path.exists():
                        file_path.unlink()
                    _finish(task_id, "error", f"{type(e).__name__}: {e}", run_id=run_id)
                    _log.error(f"  ✗ [{label}] 下载出错: {type(e).__name__}: {e}")
                    if not state.active_downloads:
                        _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")
                    break

        except asyncio.CancelledError:
            # CancelledError from flood_wait sleep or other unexpected await points
            # _finish may or may not have been called yet — it's idempotent
            _finish(task_id, "error", "已手动取消", run_id=run_id)
            if not state.active_downloads:
                _log.info("\n✅ 所有任务完成，当前没有任务进行中\n")

    finally:
        if acquired:
            await _release_connections(n_conns, source=source)
        state.task_controls.pop(task_id, None)
        state.task_outer_tasks.pop(task_id, None)

    await _broadcast()
