# SPDX-License-Identifier: AGPL-3.0-or-later
"""搬运任务管理器：任务调度、并发控制、原子移动、失败恢复。

状态机：pending → copying → done | failed
完整说明见 mover/docs/internals.md
"""
import asyncio
import errno
import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
import mover.state as state
from mover.storage import load_tasks, save_tasks
from mover.utils import (
    cleanup_staging_dirs,
    is_cross_filesystem,
    staging_dir_name,
)
from common.logger import get_logger
from common import run_state

_log = get_logger("mover")

_semaphore: Optional[asyncio.Semaphore] = None


async def _try_broadcast() -> None:
    if state._broadcast_callback is not None:
        try:
            await state._broadcast_callback()
        except Exception:
            pass


def _count_files(path: Path) -> int:
    if path.is_file():
        return 1
    return sum(1 for p in path.rglob("*") if p.is_file())


def _calc_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


async def _execute_move(task_id: str) -> None:
    task = state.tasks[task_id]
    source = Path(task["source"])
    final_target = Path(task["target"])
    target_parent = final_target.parent

    loop = asyncio.get_running_loop()

    total_files = await loop.run_in_executor(None, _count_files, source)
    size = await loop.run_in_executor(None, _calc_size, source)

    task["files_attempted"] = total_files
    task["total_size"] = size
    save_tasks(state.tasks)

    target_parent.mkdir(parents=True, exist_ok=True)
    cross_fs = is_cross_filesystem(source, target_parent)
    task["is_cross_fs"] = cross_fs
    save_tasks(state.tasks)

    # 同文件系统快路径：os.rename 本身原子，无需复制到 staging 再删源，
    # 省去整份数据的读+写（USB 盘上尤其明显），也不存在"删源前需校验"的问题。
    if not cross_fs:
        if final_target.exists():
            raise FileExistsError(f"target path already exists: {final_target}")
        try:
            await loop.run_in_executor(None, os.rename, str(source), str(final_target))
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            _log.warning(f"[mover] 同 st_dev 但 rename 报 EXDEV，回退跨文件系统流程：{source}")
            cross_fs = True
            task["is_cross_fs"] = True
        else:
            task["files_completed"] = total_files
            return

    staging_dir = target_parent / staging_dir_name()
    staging_dst = staging_dir / source.name
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        if source.is_dir():
            await loop.run_in_executor(None, shutil.copytree, str(source), str(staging_dst))
        else:
            await loop.run_in_executor(None, shutil.copy2, str(source), str(staging_dst))

        task["files_completed"] = total_files

        if final_target.exists():
            raise FileExistsError(f"target path already exists: {final_target}")

        await loop.run_in_executor(None, os.rename, str(staging_dst), str(final_target))

    except Exception:
        try:
            shutil.rmtree(str(staging_dir))
        except Exception:
            pass
        raise

    try:
        staging_dir.rmdir()
    except Exception:
        pass

    # 删源前校验目标完整性：USB/网络盘写入可能被静默截断，若不核对大小
    # 就删源，会造成数据永久损坏且无告警。校验失败则删掉损坏副本、保留源。
    verified_size = await loop.run_in_executor(None, _calc_size, final_target)
    if verified_size != size:
        _log.error(
            f"[mover] 校验失败：{final_target} 大小 {verified_size} 字节，"
            f"源大小 {size} 字节不一致，删除损坏副本并保留源文件"
        )
        try:
            if final_target.is_dir():
                await loop.run_in_executor(None, shutil.rmtree, str(final_target))
            else:
                await loop.run_in_executor(None, os.remove, str(final_target))
        except Exception:
            pass
        raise IOError(
            f"搬运后校验失败：目标大小与源不一致（{verified_size} != {size} 字节），已保留源文件"
        )

    # Delete source to complete the move
    try:
        if source.is_dir():
            await loop.run_in_executor(None, shutil.rmtree, str(source))
        else:
            await loop.run_in_executor(None, os.remove, str(source))
    except Exception as e:
        _log.warning(f"[mover] 警告：删除源文件失败 {source}: {e}")
        task["error"] = f"搬运成功但源文件清理失败：{e}"


async def _do_move(task_id: str) -> None:
    async with _semaphore:
        task = state.tasks.get(task_id)
        if task is None:
            return
        task["status"] = "copying"
        save_tasks(state.tasks)
        await _try_broadcast()
        _log.info(f"[mover] ⏳ 开始搬运：{task['source']} → {task['target']}")
        try:
            await _execute_move(task_id)
            task = state.tasks[task_id]
            task["status"] = "done"
            task["completed_at"] = datetime.now().isoformat()
            _log.info(f"[mover] ✓ 完成：{task['target']}")
        except Exception as e:
            traceback.print_exc()
            task = state.tasks.get(task_id)
            if task:
                now_iso = datetime.now().isoformat()
                task["status"] = "failed"
                task["error"] = str(e)
                # P2-10: failed_at 现在是真正的失败时间戳；error_source 存出错的源文件路径
                task["failed_at"] = now_iso
                task["error_source"] = task.get("source")
                task["completed_at"] = now_iso
            _log.error(f"[mover] ✗ 失败：{task_id}: {e}")
        finally:
            # P2-11 (3D): 原地裁剪而不是替换 dict 引用，避免并发协程持旧引用
            _trim_tasks_inplace(config.MOVER_MAX_HISTORY)
            save_tasks(state.tasks)
            await _try_broadcast()


async def _requeue(task_id: str, *, retrying: bool = False) -> dict:
    task = state.tasks[task_id]
    task["status"] = "pending"
    task["error"] = None
    task["failed_at"] = None
    task["error_source"] = None
    task["files_attempted"] = 0
    task["files_completed"] = 0
    task["completed_at"] = None
    save_tasks(state.tasks)
    # P1-5a Q4: 暂停时不 dispatch；恢复时 resume() 会扫描 pending 触发
    if not state.paused:
        asyncio.create_task(_do_move(task_id))
    await _try_broadcast()
    result: dict = {"ok": True, "task_id": task_id}
    if retrying:
        result["retrying"] = True
    if state.paused:
        result["queued"] = True
        result["reason"] = "mover paused"
    return result


# ── Public API ─────────────────────────────────────────────────────────────────

async def submit(source: str, target: str, task_id: str) -> dict:
    """发起搬运任务，立即返回。

    幂等规则：
    - task_id 对应 status=done   → 返回 {"ok": True, "already_moved": True, "target_path": "..."}
    - task_id 对应 status=copying → 返回 {"ok": True, "in_progress": True, "task_id": "..."}
    - task_id 对应 status=failed  → 覆盖旧记录，重新排队
    - task_id 不存在              → 新建任务，立即返回 {"ok": True, "task_id": "..."}
    """
    existing = state.tasks.get(task_id)
    if existing:
        status = existing["status"]
        if status in ("pending", "copying"):
            return {"ok": True, "in_progress": True, "task_id": task_id}
        if status == "done":
            return {"ok": True, "already_moved": True, "target_path": existing["target"]}
        # failed → re-queue
        return await _requeue(task_id, retrying=True)

    source_path = Path(source)
    final_target = Path(target) / source_path.name
    now = datetime.now().isoformat()
    state.tasks[task_id] = {
        "task_id":         task_id,
        "source":          source,
        "target":          str(final_target),
        "status":          "pending",
        "created_at":      now,
        "completed_at":    None,
        "error":           None,
        "files_attempted": 0,
        "files_completed": 0,
        "failed_at":       None,        # P2-10: ISO 时间戳，失败时记录
        "error_source":    None,        # P2-10: 失败时存出错的源文件路径
        "is_cross_fs":     False,
        "total_size":      None,
    }
    save_tasks(state.tasks)
    # P1-5a Q4: 暂停时不 dispatch；任务以 status=pending 排队，resume 时执行
    if state.paused:
        await _try_broadcast()
        return {"ok": True, "task_id": task_id, "queued": True, "reason": "mover paused"}
    asyncio.create_task(_do_move(task_id))
    await _try_broadcast()
    return {"ok": True, "task_id": task_id}


async def pause() -> None:
    """P1-5a Q4: 软暂停 mover。新 submit 入队为 pending 但不 dispatch。"""
    state.paused = True
    run_state.save("mover", paused=True)
    await _try_broadcast()


async def resume() -> None:
    """P1-5a Q4: 恢复 mover。扫描所有 pending 任务，按 created_at 升序触发执行。"""
    state.paused = False
    run_state.save("mover", paused=False)
    pending = sorted(
        [t for t in state.tasks.values() if t["status"] == "pending"],
        key=lambda t: t.get("created_at", ""),
    )
    for task in pending:
        asyncio.create_task(_do_move(task["task_id"]))
    await _try_broadcast()


async def retry(task_id: str) -> dict:
    """重试失败的搬运任务。task_id 不存在或状态非 failed 返回错误。"""
    task = state.tasks.get(task_id)
    if task is None:
        return {"ok": False, "error": "task not found"}
    if task["status"] != "failed":
        return {"ok": False, "error": "task is not in failed status"}
    if not Path(task["source"]).exists():
        return {"ok": False, "error": "source path no longer exists"}
    return await _requeue(task_id)


async def get_task(task_id: str) -> dict | None:
    """查询单个任务状态。不存在返回 None。"""
    return state.tasks.get(task_id)


async def list_tasks(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """查询任务列表（按 created_at 倒序），支持状态过滤和分页。

    返回 (items, total)。
    """
    items = list(state.tasks.values())
    if status:
        items = [t for t in items if t["status"] == status]
    total = len(items)
    items.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return items[offset : offset + limit], total


async def delete_task(task_id: str) -> bool:
    """从持久化记录中删除任务（不影响文件）。不存在返回 False。"""
    if task_id not in state.tasks:
        return False
    del state.tasks[task_id]
    save_tasks(state.tasks)
    return True


async def clear_tasks(statuses: tuple = ("done", "failed")) -> int:
    """清空指定状态的历史记录（默认 done + failed），返回删除数量。"""
    to_delete = [
        tid for tid, t in state.tasks.items() if t["status"] in statuses
    ]
    for tid in to_delete:
        del state.tasks[tid]
    if to_delete:
        save_tasks(state.tasks)
    return len(to_delete)


def _trim_tasks_inplace(max_history: int) -> None:
    """P2-11 (3D) 并发安全：不替换 dict 引用，原地 pop 已归档任务。

    pending/copying 始终保留；done/failed 按 completed_at 倒序保留最新 max_history 条。
    """
    archived = [(tid, t) for tid, t in state.tasks.items()
                if t.get("status") in ("done", "failed")]
    if len(archived) <= max_history:
        return
    archived.sort(key=lambda kv: kv[1].get("completed_at") or "", reverse=True)
    keep = {tid for tid, _ in archived[:max_history]}
    for tid, _ in archived:
        if tid not in keep:
            state.tasks.pop(tid, None)


def _migrate_failed_at(tasks: dict) -> None:
    """P2-10 兼容性迁移：旧版 failed_at 存源文件路径（看起来不像 ISO 时间戳）。

    将这些值移到 error_source；failed_at 改为 None（旧记录失败时间已无法恢复）。
    """
    for t in tasks.values():
        fa = t.get("failed_at")
        if fa and isinstance(fa, str) and ("/" in fa or "\\" in fa):
            t["error_source"] = fa
            t["failed_at"] = None


async def start() -> None:
    """启动 manager：加载持久化状态，清理残留临时目录，恢复 copying → failed。"""
    global _semaphore
    _semaphore = asyncio.Semaphore(config.MOVER_MAX_CONCURRENT)

    state.tasks = load_tasks()
    _migrate_failed_at(state.tasks)

    # Recover interrupted tasks
    for task_id, task in state.tasks.items():
        if task["status"] == "copying":
            cleanup_staging_dirs(Path(task["target"]).parent)
            task["status"] = "failed"
            task["error"] = "进程中断，staging 已清理"
            task["completed_at"] = datetime.now().isoformat()
            _log.info(f"[mover] 启动恢复：任务 {task_id} 已标记为 failed")
        # P1-5a Q4: pending 任务保留状态，启动后 dispatch（见下方）。
        # 2026-11-13 起 paused 会持久化（common/run_state.py）：关机前是暂停的，启动后仍暂停，
        # pending 留到用户点「恢复」再执行。

    # Clean orphan staging dirs
    known_parents: set[Path] = {Path(t["target"]).parent for t in state.tasks.values()}
    for parent in known_parents:
        count = cleanup_staging_dirs(parent)
        if count:
            _log.info(f"[mover] 清理孤儿 staging 目录 {count} 个：{parent}")

    # 启动时裁剪一次历史（清理旧文件可能累积的 done/failed）
    _trim_tasks_inplace(config.MOVER_MAX_HISTORY)
    save_tasks(state.tasks)

    # P1-5a Q4: 启动恢复后，dispatch 所有 pending 任务（按 created_at 升序）
    pending = sorted(
        [t for t in state.tasks.values() if t["status"] == "pending"],
        key=lambda t: t.get("created_at", ""),
    )
    if state.paused:
        if pending:
            _log.info(f"[mover] 恢复成关机前的「暂停」，{len(pending)} 个 pending 任务等点恢复再执行")
    else:
        for task in pending:
            asyncio.create_task(_do_move(task["task_id"]))
        if pending:
            _log.info(f"[mover] 启动后触发 {len(pending)} 个 pending 任务")

    _log.info(f"[mover] 已启动 | 并发：{config.MOVER_MAX_CONCURRENT}")
