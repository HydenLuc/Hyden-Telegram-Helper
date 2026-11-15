# SPDX-License-Identifier: AGPL-3.0-or-later
"""同一个 task_id 被两次 download_one 复用时的归属守卫（2026-09-17 回归）。

## 这组用例防的是什么

用户重试、启动恢复扫描**都复用原 task_id**。于是同一个 task_id 可能同时存在
两个 `download_one` 协程：老的那次被超时看门狗 cancel 之后，它的收尾逻辑仍会执行。

不认归属的话，老的那次会把**新那次**刚建好的 `active_downloads` 记录 pop 掉，
新那次接着写就是 `KeyError` → `download_one` 整个崩掉 → 收尾没跑完 →
任务**永久卡在 pending_tasks 里**。而且崩的形式是 asyncio 的
「Task exception was never retrieved」，错误计数里都看不见。

2026-09-17 实测：11 个任务因此在队列里躺了一个多月，每个都下到了 99%+。
"""
import time

import pytest

from downloader import state
from downloader.download import manager


@pytest.fixture(autouse=True)
def _clean_state():
    state.active_downloads.clear()
    state.completed_downloads.clear()
    yield
    state.active_downloads.clear()
    state.completed_downloads.clear()


def _put(task_id: str, run_id: int) -> dict:
    """模拟 download_one 建记录。"""
    rec = dict(_run=run_id, task_id=task_id, status="downloading",
               queued_at=time.time(), started_at=None, finished_at=None,
               error_msg="", path="", dir="", pct=0)
    state.active_downloads[task_id] = rec
    return rec


def test_run_id_递增且唯一():
    a, b, c = manager._next_run_id(), manager._next_run_id(), manager._next_run_id()
    assert a < b < c


def test_旧协程收尾不能摘掉新协程的记录():
    """核心用例：这就是 2026-09-17 那个 bug。"""
    tid = "-100123_456"
    old_run = manager._next_run_id()
    _put(tid, old_run)

    # 新的一次接管（重试 / 恢复扫描复用同一个 task_id）
    new_run = manager._next_run_id()
    _put(tid, new_run)

    # 老的那次被 cancel 后才执行收尾 —— 它必须认出自己已经不当家
    manager._finish(tid, "timeout", "超过 60s 无进度，已取消", run_id=old_run)

    assert tid in state.active_downloads, "新那次的记录被老那次摘掉了"
    assert state.active_downloads[tid]["_run"] == new_run
    assert state.active_downloads[tid]["status"] == "downloading", "状态被老那次改写了"


async def test_当家的那次可以正常收尾():
    # ⚠️ 必须是 async：status="done" 会走 MD5 索引，那里 create_task 需要事件循环。
    #    同步跑会 RuntimeError: no running event loop（pytest.ini 已开 asyncio_mode=auto）
    tid = "-100123_789"
    run = manager._next_run_id()
    _put(tid, run)
    manager._finish(tid, "done", run_id=run)
    assert tid not in state.active_downloads
    assert state.completed_downloads, "收尾了却没进 completed"


def test_不传_run_id_时保持旧行为():
    """外部调用点（api 等）没有 run_id，不能因此失效。"""
    tid = "-100123_000"
    _put(tid, manager._next_run_id())
    manager._finish(tid, "error", "手动取消")
    assert tid not in state.active_downloads


def test_记录已不在时收尾是无操作():
    manager._finish("不存在的任务", "done", run_id=1)          # 不该抛
    manager._finish("不存在的任务", "done")                     # 同上


def test_老协程重复收尾不会连累后续的新协程():
    """老协程可能在多个分支里调 _finish（超时→异常→finally），每次都不能误伤。"""
    tid = "-100123_111"
    old_run = manager._next_run_id()
    _put(tid, old_run)
    new_run = manager._next_run_id()
    _put(tid, new_run)

    for status in ("timeout", "error", "error"):
        manager._finish(tid, status, "老协程的收尾", run_id=old_run)

    assert state.active_downloads.get(tid, {}).get("_run") == new_run
    assert not state.completed_downloads, "老协程的收尾不该产生完成记录"
