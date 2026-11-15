# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import random
import shutil
import traceback
from datetime import datetime
import pathlib
from pathlib import Path
from typing import Awaitable, Callable, Optional

import config
from unzipper.extractor import (
    extract, ExtractError, archive_stem, find_multipart_parts,
    warn_if_names_too_long,
)
from common.pathlimits import fix_long_names, looks_like_mojibake
from unzipper.utils import unique_dir_name, scan_archives, find_residuals
from unzipper.storage import save_history, save_setting_to_env
from unzipper.watcher import start_watcher
import unzipper.state as _state
from common.logger import get_logger

_log = get_logger("unzipper")

# ── Internal state ─────────────────────────────────────────────────────────────

_queue: asyncio.Queue = asyncio.Queue()
_broadcast_cb: Optional[Callable[[], Awaitable[None]]] = None
_task_semaphore: Optional[asyncio.Semaphore] = None
_task_counter: int = 0


def set_broadcast_callback(cb: Callable[[], Awaitable[None]]) -> None:
    global _broadcast_cb
    _broadcast_cb = cb


def _gen_id() -> str:
    """Generate a 4-digit ID for pending tasks."""
    while True:
        id_ = f"{random.randint(0, 9999):04d}"
        if id_ not in _state.pending_multipart:
            return id_


def _gen_task_id() -> str:
    """Generate a sequential ID for running tasks (separate pool from pending IDs)."""
    global _task_counter
    _task_counter += 1
    return str(_task_counter)


def _ensure_semaphore():
    """Lazily create semaphore inside the running event loop."""
    global _task_semaphore
    if _task_semaphore is None:
        _task_semaphore = asyncio.Semaphore(_state.max_concurrent_tasks)


async def _try_broadcast():
    if _broadcast_cb is not None:
        try:
            await _broadcast_cb()
        except Exception:
            pass


# ── Failure helpers ────────────────────────────────────────────────────────────

def _move_to_failed(out_dir: Path) -> Path:
    """Move out_dir into OUTPUT_PATH/@任务失败/, return new path."""
    failed_base = config.OUTPUT_PATH / "@任务失败"
    failed_base.mkdir(parents=True, exist_ok=True)
    dest = failed_base / unique_dir_name(failed_base, out_dir.name)
    shutil.move(str(out_dir), str(dest))
    return dest


def _move_to_cancelled(task_root: Path) -> Path:
    """Move task_root into OUTPUT_PATH/@已取消/, return new path.

    取消文件夹任务时 task_root 里可能已含成功解压的产物（连同被消费掉的原始
    压缩包一起被 extract() 移了进去），不能直接 rmtree——那会把已完成的工作
    也删掉。挪进 @已取消 保留证据，交给人工判断要不要保留/重新处理。
    """
    cancelled_base = config.OUTPUT_PATH / "@已取消"
    cancelled_base.mkdir(parents=True, exist_ok=True)
    dest = cancelled_base / unique_dir_name(cancelled_base, task_root.name)
    shutil.move(str(task_root), str(dest))
    return dest


def _write_failure_file(dir_: Path, reason: str, detail: str, filename: str = ""):
    lines = []
    if filename:
        lines.append(f"文件名：{filename}")
    lines += [f"失败原因：{reason}", f"详情：{detail}", ""]
    (dir_ / "任务失败.txt").write_text("\n".join(lines), encoding="utf-8")


def _make_on_attempt(name: str, task_id: str):
    async def on_attempt(pwd):
        label = pwd if pwd else "(无密码)"
        _log.info(f"[unzipper] 尝试密码：{label}  ({name})")
        if task_id in _state.current_tasks:
            _state.current_tasks[task_id]["trying_password"] = label
            # 新一轮密码尝试：进度归零（避免显示上次失败时的进度）
            _state.current_tasks[task_id]["progress_pct"] = -1
        await _try_broadcast()
    return on_attempt


def _make_on_pct(task_id: str):
    """P2-2: 解压进度回调；命中即更新 task[progress_pct] + 广播。"""
    async def on_pct(pct: int):
        t = _state.current_tasks.get(task_id)
        if t is None:
            return
        t["progress_pct"] = pct
        await _try_broadcast()
    return on_pct


def _make_register_proc(task_id: str):
    """P2-4: 把 7z 子进程 handle 暴露到 task 记录上，供 cancel_task 用。"""
    def register_proc(proc):
        t = _state.current_tasks.get(task_id)
        if t is None:
            return
        t["proc"] = proc   # proc=None 表示该 archive 已结束
    return register_proc


# ── P2-4 取消解压任务 ──────────────────────────────────────────────────────

async def cancel_task(task_id: str) -> bool:
    """请求取消正在解压的任务。

    流程：
    1. 设 cancel_flag=True
    2. terminate proc（如果在跑），等其退出
    3. _process_* 在 except 分支识别 cancel_flag，走"已取消"清理（删 target_dir + 写 history）
    4. 等 _process_* 完成（cancel_event.wait）
    返回 True=已请求；False=task 不存在。
    """
    t = _state.current_tasks.get(task_id)
    if t is None:
        return False
    if t.get("cancel_flag"):
        return True   # 已经在取消中
    t["cancel_flag"] = True
    if "cancel_event" not in t:
        t["cancel_event"] = asyncio.Event()
    proc = t.get("proc")
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
    # 等 _process_* 完成清理；超时 10s 容忍
    try:
        await asyncio.wait_for(t["cancel_event"].wait(), timeout=10)
    except asyncio.TimeoutError:
        pass
    return True


# ── Single-archive processing (single + multipart) ────────────────────────────

async def _process_single(path: Path, kind: str):
    _ensure_semaphore()
    async with _task_semaphore:
        task_id     = _gen_task_id()
        output_base = config.OUTPUT_PATH or path.parent
        # Reserve output dir synchronously before any await to avoid naming races
        target_dir  = output_base / unique_dir_name(output_base, archive_stem(path))
        target_dir.mkdir(parents=True, exist_ok=True)
        is_multi    = kind == "multipart"

        started_at = datetime.now().isoformat()
        _state.current_tasks[task_id] = {
            "name": path.name, "kind": kind, "status": "extracting",
            "started_at": started_at, "trying_password": None,
            "progress_pct": -1,    # P2-2: 解压进度（-1=未知，0~100=百分比）
            "cancel_flag": False,  # P2-4: 取消标志
            "cancel_event": asyncio.Event(),
            "proc": None,          # P2-4: 当前 7z 子进程 handle
        }
        await _try_broadcast()
        _log.info(f"[unzipper] ⏳ 开始解压{'多卷包' if is_multi else ''}：{path.name}")

        try:
            # 解压前先扫一遍条目名：超长的会在 ZFS/APFS 上 ENAMETOOLONG，
            # 而 7z 的报错里看不出「是名字太长」，先告警免得后面成谜。
            await warn_if_names_too_long(path)

            out_dir, pwd = await extract(
                path, output_base, _state.passwords,
                on_attempt=_make_on_attempt(path.name, task_id),
                on_pct=_make_on_pct(task_id),
                register_proc=_make_register_proc(task_id),
                explicit_out_dir=target_dir,
            )
            _log.info(f"[unzipper] ✓ {'multipart ' if is_multi else ''}{path.name} → {out_dir}")

            # 解压产出的名字来自**压缩包内部**，不经过 downloader 的任何清洗，
            # 超过 255 字节的分量在 ZFS/APFS 上会让下游（rsync/备份/再解压）静默跳过。
            # 2026-08-13 就这么丢过 23 个文件，详见 common/pathlimits.py 的注释。
            # ⚠️ 只能事后修：`7z x` 没有「解压时改名」的选项。
            loop = asyncio.get_running_loop()
            renamed = await loop.run_in_executor(
                None, lambda: fix_long_names(out_dir, log=_log.warning))
            if renamed:
                _log.warning(
                    f"[unzipper] {path.name}: 改短了 {len(renamed)} 个超长名字。"
                    f"⚠️ 其中若有乱码名（GBK 被当 CP437 解），改短只是让文件系统收下它，"
                    f"**名字本身还是乱的**，需要人工确认")
                for old_p, new_p in renamed[:5]:
                    if looks_like_mojibake(pathlib.Path(new_p).name):
                        _log.warning(f"[unzipper]   疑似乱码：{pathlib.Path(new_p).name!r}")

            _state.history.append({
                "name": path.name, "kind": kind, "status": "done",
                "out_dir": str(out_dir), "password": pwd,
                "error": None, "error_detail": None,
                "archives": None, "residuals": None,
                "started_at": started_at, "finished_at": datetime.now().isoformat(),
            })
            save_history(_state.history)
        except Exception as e:
            t = _state.current_tasks.get(task_id, {})
            if t.get("cancel_flag"):
                # P2-4: 用户取消 → 删除 target_dir，写 cancelled history
                _log.info(f"[unzipper] ⊘ 已取消：{path.name}")
                try:
                    if target_dir.exists():
                        shutil.rmtree(str(target_dir))
                except Exception as ex:
                    _log.warning(f"[unzipper] 删除 target_dir 失败: {ex}")
                _state.history.append({
                    "name": path.name, "kind": kind, "status": "cancelled",
                    "out_dir": None, "password": None,
                    "error": "用户取消", "error_detail": str(e),
                    "archives": None, "residuals": None,
                    "started_at": started_at, "finished_at": datetime.now().isoformat(),
                })
                save_history(_state.history)
            else:
                traceback.print_exc()
                reason = e.reason if isinstance(e, ExtractError) else f"其他: {e}"
                _log.error(f"[unzipper] ✗ {'multipart ' if is_multi else ''}{path.name}: {reason}")
                try:
                    if is_multi and path.name.lower().endswith('.7z.001'):
                        for part in find_multipart_parts(path):
                            if part.exists():
                                shutil.move(str(part), str(target_dir / part.name))
                    elif path.exists():
                        shutil.move(str(path), str(target_dir / path.name))
                except Exception:
                    pass
                _write_failure_file(target_dir, reason, str(e), path.name)
                final_dir = _move_to_failed(target_dir)
                _state.history.append({
                    "name": path.name, "kind": kind, "status": "failed",
                    "out_dir": str(final_dir), "password": None,
                    "error": reason, "error_detail": str(e),
                    "archives": None, "residuals": None,
                    "started_at": started_at, "finished_at": datetime.now().isoformat(),
                })
                save_history(_state.history)
        finally:
            t = _state.current_tasks.pop(task_id, None)
            if t and t.get("cancel_event"):
                t["cancel_event"].set()
            await _try_broadcast()


# ── Folder processing ──────────────────────────────────────────────────────────

async def _process_folder(source: Path):
    _ensure_semaphore()
    async with _task_semaphore:
        task_id     = _gen_task_id()
        output_base = config.OUTPUT_PATH or source.parent
        task_name   = unique_dir_name(output_base, source.name)
        task_root   = output_base / task_name
        task_root.mkdir(parents=True, exist_ok=True)

        archives, non_archives = scan_archives(source)

        started_at = datetime.now().isoformat()
        _state.current_tasks[task_id] = {
            "name": source.name, "kind": "folder", "status": "extracting",
            "started_at": started_at, "trying_password": None,
            "total_archives": len(archives), "current_archive_idx": 0,
            "current_archive": None,
            "progress_pct": -1,    # P2-2: 当前 archive 的解压进度
            "cancel_flag": False,  # P2-4
            "cancel_event": asyncio.Event(),
            "proc": None,
        }
        await _try_broadcast()
        _log.info(f"[unzipper] 📁 开始处理文件夹：{source.name}  ({len(archives)} 个压缩包，{len(non_archives)} 个普通文件)")

        # ── Step 1: move non-archives, maintain relative structure ─────────────
        # 记下 (task_root 内新位置 → source 内原位置)，供取消时把这些「只是搬了个
        # 家、从未被任何解压流程处理过」的原始文件挪回去，不能让它们跟着 task_root
        # 一起被删掉。
        moved_non_archives: list[tuple[Path, Path]] = []
        for file_path in non_archives:
            try:
                rel  = file_path.relative_to(source)
                dest = task_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(file_path), str(dest))
                moved_non_archives.append((dest, file_path))
            except Exception as ex:
                _log.warning(f"[unzipper] 警告：移动文件失败 {file_path.name}: {ex}")

        # ── Step 2: process each archive ──────────────────────────────────────
        archives_result: list[dict] = []
        any_failed = False

        for idx, archive_path in enumerate(archives):
            t = _state.current_tasks.get(task_id)
            # P2-4: 每个 archive 开始前检查取消
            if t and t.get("cancel_flag"):
                break
            if t:
                t["current_archive_idx"] = idx + 1
                t["current_archive"]     = archive_path.name
                t["trying_password"]     = None
                t["progress_pct"]        = -1   # 切换到下一个 archive 时进度归零
            await _try_broadcast()

            rel_parent    = archive_path.parent.relative_to(source)
            target_parent = task_root / rel_parent
            target_parent.mkdir(parents=True, exist_ok=True)
            subdir_name   = unique_dir_name(target_parent, archive_stem(archive_path))
            explicit_out  = target_parent / subdir_name

            _log.info(f"[unzipper] [{idx+1}/{len(archives)}] 解压：{archive_path.name}")

            try:
                out_subdir, pwd = await extract(
                    archive_path,
                    output_base=target_parent,
                    passwords=_state.passwords,
                    on_attempt=_make_on_attempt(archive_path.name, task_id),
                    on_pct=_make_on_pct(task_id),
                    register_proc=_make_register_proc(task_id),
                    explicit_out_dir=explicit_out,
                )
                _log.info(f"[unzipper] ✓ {archive_path.name} → {out_subdir.relative_to(task_root)}")
                archives_result.append({
                    "name":       archive_path.name,
                    "status":     "done",
                    "password":   pwd,
                    "error":      None,
                    "out_subdir": str(out_subdir.relative_to(task_root)),
                })
            except Exception as e:
                t = _state.current_tasks.get(task_id, {})
                if t.get("cancel_flag"):
                    # P2-4: 用户取消 → 跳出循环，由下方 cancel 分支统一清理
                    break
                traceback.print_exc()
                reason = e.reason if isinstance(e, ExtractError) else f"其他: {e}"
                _log.error(f"[unzipper] ✗ {archive_path.name}: {reason}")
                any_failed = True
                explicit_out.mkdir(parents=True, exist_ok=True)
                try:
                    if archive_path.name.lower().endswith('.7z.001'):
                        for part in find_multipart_parts(archive_path):
                            if part.exists():
                                shutil.move(str(part), str(explicit_out / part.name))
                    elif archive_path.exists():
                        shutil.move(str(archive_path), str(explicit_out / archive_path.name))
                except Exception:
                    pass
                _write_failure_file(explicit_out, reason, str(e), archive_path.name)
                archives_result.append({
                    "name":       archive_path.name,
                    "status":     "failed",
                    "password":   None,
                    "error":      reason,
                    "out_subdir": str(explicit_out.relative_to(task_root)),
                })

        # ── P2-4 取消：先移回未处理原件，task_root 剩余部分（已完成的解压产物）
        # 归档到 @已取消 而不是直接删掉，写 cancelled history，跳过后续步骤 ─────
        t = _state.current_tasks.get(task_id, {})
        if t.get("cancel_flag"):
            _log.info(f"[unzipper] ⊘ 已取消文件夹任务：{source.name}")
            restored = 0
            for dest, back in moved_non_archives:
                try:
                    if dest.exists():
                        back.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(dest), str(back))
                        restored += 1
                except Exception as ex:
                    _log.warning(f"[unzipper] 取消时移回原件失败 {dest}: {ex}")
            if restored:
                _log.info(f"[unzipper] 取消：已移回 {restored} 个原始文件到 {source}")
            final_dir: Optional[Path] = None
            try:
                if task_root.exists():
                    if any(task_root.iterdir()):
                        final_dir = _move_to_cancelled(task_root)
                    else:
                        task_root.rmdir()
            except Exception as ex:
                _log.warning(f"[unzipper] 归档 task_root 失败: {ex}")
                final_dir = task_root if task_root.exists() else None
            _state.history.append({
                "name": source.name, "kind": "folder", "status": "cancelled",
                "out_dir": str(final_dir) if final_dir else None, "password": None,
                "error": "用户取消", "error_detail": None,
                "archives": archives_result, "residuals": None,
                "started_at": started_at, "finished_at": datetime.now().isoformat(),
            })
            save_history(_state.history)
            tt = _state.current_tasks.pop(task_id, None)
            if tt and tt.get("cancel_event"):
                tt["cancel_event"].set()
            await _try_broadcast()
            return

        # ── Step 3: residual detection ─────────────────────────────────────────
        residuals = find_residuals(source)
        if not residuals:
            try:
                shutil.rmtree(str(source))
                _log.info(f"[unzipper] 原文件夹已清理：{source.name}")
            except Exception as ex:
                _log.error(f"[unzipper] 清理文件夹失败：{ex}")
        else:
            _log.info(f"[unzipper] 残留 {len(residuals)} 个文件，原文件夹保留：{source}")

        # ── Step 4: move to @任务失败 if any archive failed ───────────────────
        final_dir = task_root
        if any_failed:
            final_dir = _move_to_failed(task_root)
            _log.error(f"[unzipper] 任务移入失败目录：{final_dir}")

        if any_failed:
            ok_count = sum(1 for r in archives_result if r["status"] == "done")
            overall  = "partial" if ok_count > 0 else "failed"
        else:
            overall = "done"

        _state.history.append({
            "name":         source.name,
            "kind":         "folder",
            "status":       overall,
            "out_dir":      str(final_dir),
            "password":     None,
            "error":        None,
            "error_detail": None,
            "archives":     archives_result,
            "residuals":    residuals,
            "started_at":   started_at,
            "finished_at":  datetime.now().isoformat(),
        })
        save_history(_state.history)
        tt = _state.current_tasks.pop(task_id, None)
        if tt and tt.get("cancel_event"):
            tt["cancel_event"].set()
        await _try_broadcast()


# ── Queue worker ───────────────────────────────────────────────────────────────

async def _queue_worker():
    while True:
        kind, path = await _queue.get()
        try:
            if kind == 'auto':
                await _process_single(path, "single")
            elif kind == 'multipart':
                id_ = _gen_id()
                _state.pending_multipart[id_] = {
                    'kind': 'multipart', 'path': path, 'name': path.name,
                }
                _log.info(f"[unzipper] 多卷包待确认：{path.name}  ID={id_}")
                await _try_broadcast()
            elif kind == 'folder':
                id_ = _gen_id()
                _state.pending_multipart[id_] = {
                    'kind': 'folder', 'path': path, 'name': path.name,
                }
                _log.info(f"[unzipper] 文件夹待确认：{path.name}  ID={id_}")
                await _try_broadcast()
        finally:
            _queue.task_done()


# ── Public API ─────────────────────────────────────────────────────────────────

async def confirm_pending(id_: str) -> bool:
    """Confirm a pending multipart or folder task by ID."""
    rec = _state.pending_multipart.pop(id_, None)
    if not rec:
        return False
    await _try_broadcast()
    if rec['kind'] == 'folder':
        asyncio.create_task(_process_folder(rec['path']))
    else:
        asyncio.create_task(_process_single(rec['path'], "multipart"))
    return True


# Keep old name as alias so bot.py / api.py callers don't need updating.
confirm_multipart = confirm_pending


async def retry_failed(name: str) -> bool:
    """重试某个失败/部分失败/取消的解压任务。

    失败时归档被移进 OUTPUT_PATH/@任务失败/<stem>/（history.out_dir 记录该目录）。
    重试 = 从该目录找回归档，删掉旧失败记录，直接重新解压（用户主动重试，
    多卷不再走待确认，直接尝试；缺卷会被 extract 的缺卷预检拦下报"卷缺失"）。
    """
    rec = None
    for h in reversed(_state.history):
        if h.get("name") == name and h.get("status") in ("failed", "partial", "cancelled"):
            rec = h
            break
    if rec is None:
        return False
    out_dir = rec.get("out_dir")
    if not out_dir:
        return False
    archive = Path(out_dir) / name          # 归档文件仍在失败目录里
    if not archive.exists():
        return False
    try:
        _state.history.remove(rec)          # 移除旧失败记录，避免重复堆积
        save_history(_state.history)
    except ValueError:
        pass
    await _try_broadcast()
    kind = "multipart" if name.lower().endswith('.7z.001') else "single"
    asyncio.create_task(_process_single(archive, kind))
    _log.info(f"[unzipper] ↻ 重试解压：{name}")
    return True


def get_pending_list() -> list[tuple[str, str]]:
    return [(id_, rec['name']) for id_, rec in _state.pending_multipart.items()]


def queue_depth() -> int:
    return _queue.qsize()


async def submit(path: Path) -> dict:
    """Directly submit a path as a task.

    Returns {"pending_id": "0042", "kind": "folder"} for items needing confirmation,
    or {"task_started": True, "name": "x.zip"} for immediately started tasks.
    """
    name = path.name.lower()
    if path.is_dir():
        id_ = _gen_id()
        _state.pending_multipart[id_] = {'kind': 'folder', 'path': path, 'name': path.name}
        _log.info(f"[unzipper] 文件夹待确认（submit）：{path.name}  ID={id_}")
        await _try_broadcast()
        return {"pending_id": id_, "kind": "folder"}
    if name.endswith('.7z.001'):
        id_ = _gen_id()
        _state.pending_multipart[id_] = {'kind': 'multipart', 'path': path, 'name': path.name}
        _log.info(f"[unzipper] 多卷包待确认（submit）：{path.name}  ID={id_}")
        await _try_broadcast()
        return {"pending_id": id_, "kind": "multipart"}
    asyncio.create_task(_process_single(path, "single"))
    return {"task_started": True, "name": path.name}


async def set_max_concurrent(n: int):
    """Change the concurrency limit at runtime and persist to .env."""
    global _task_semaphore
    n = max(1, n)
    old = _state.max_concurrent_tasks
    _state.max_concurrent_tasks = n
    _task_semaphore = asyncio.Semaphore(n)
    # Start extra workers if increasing so the queue drains at the new rate
    for _ in range(max(0, n - old)):
        asyncio.create_task(_queue_worker())
    save_setting_to_env("MAX_CONCURRENT_TASKS", str(n))


# ── Startup ────────────────────────────────────────────────────────────────────

async def start():
    global _task_semaphore
    if not config.WATCH_PATH:
        _log.warning("WATCH_PATH 未配置，unzipper 未启动")
        return
    if not config.OUTPUT_PATH:
        _log.warning("OUTPUT_PATH 未配置，unzipper 未启动")
        return

    config.OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

    _task_semaphore = asyncio.Semaphore(_state.max_concurrent_tasks)
    for _ in range(_state.max_concurrent_tasks):
        asyncio.create_task(_queue_worker())
    asyncio.create_task(start_watcher(_queue))
    _log.info(f"Unzipper 已启动 | 监听：{config.WATCH_PATH} | 输出：{config.OUTPUT_PATH} | 并发：{_state.max_concurrent_tasks}")
