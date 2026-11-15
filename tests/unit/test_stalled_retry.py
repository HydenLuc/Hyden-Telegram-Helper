# SPDX-License-Identifier: AGPL-3.0-or-later
"""搁置任务的周期性重试（2026-09-17 新增）。

## 为什么要有这个

`recover_pending_tasks` **只在启动时跑一次**。跑完还失败的任务就永远躺在
`pending_tasks` 里，**没有任何周期任务会再碰它们** —— 界面上混在「队列」里
看着像在排队，实际 11 个大文件任务躺了一个多月（hyden 报的
「队列 18 但实际只有一个在下」就是这个）。

## 两条必须钉死的

① **已经在下的任务绝不能再起一次** —— 同 task_id 起两次会互相踩踏。
   run_id 守卫能防数据损坏，但白下一遍 3.5 GB 没人能防。
② **退避必须生效** —— 一个永远下不成的任务如果每轮都重试，
   会把连接预算吃光，正常任务排不进来。
"""
import time

import pytest

import config
from downloader import state
from downloader.download import manager


@pytest.fixture(autouse=True)
def _clean():
    state.pending_tasks.clear()
    state.active_downloads.clear()
    yield
    state.pending_tasks.clear()
    state.active_downloads.clear()


def _pending(tid, *, retry=0, last_attempt=0.0):
    state.pending_tasks[tid] = {
        "chat_id": -100, "message_id": 1, "save_path": f"/tmp/{tid}.mp4",
        "expected_size": 999, "retry_count": retry,
        "last_attempt_at": last_attempt, "source": "realtime",
    }


def test_从没试过的任务立刻可重试():
    _pending("a")                      # last_attempt_at = 0 → 早就过了退避
    assert "a" in manager.stalled_tasks()


def test_正在下载的任务绝不重复发起():
    """核心用例①：起两次会白下一遍几个 GB。"""
    _pending("busy")
    state.active_downloads["busy"] = {"_run": 1, "status": "downloading"}
    assert "busy" not in manager.stalled_tasks()


def test_刚试过的任务要等退避():
    """核心用例②：不等的话失败任务会把连接预算吃光。"""
    now = time.time()
    _pending("fresh", retry=0, last_attempt=now)
    assert "fresh" not in manager.stalled_tasks(now=now)
    # 过了一个间隔就该放行
    assert "fresh" in manager.stalled_tasks(now=now + config.STALLED_RETRY_INTERVAL + 1)


def test_失败越多等越久():
    now = time.time()
    base = max(60, config.STALLED_RETRY_INTERVAL)
    _pending("r0", retry=0, last_attempt=now)
    _pending("r3", retry=3, last_attempt=now)

    # 过了 1 个间隔：retry=0 的放行，retry=3 的还得等（2^3 = 8 倍）
    t = now + base + 1
    got = manager.stalled_tasks(now=t)
    assert "r0" in got and "r3" not in got

    # 过了 8 个间隔：retry=3 的也放行
    assert "r3" in manager.stalled_tasks(now=now + base * 8 + 1)


def test_退避封顶在24小时():
    """重试次数很大时别算成天文数字，否则任务等于被永久放弃。"""
    now = time.time()
    _pending("many", retry=99, last_attempt=now)
    assert "many" in manager.stalled_tasks(now=now + 24 * 3600 + 1)


def test_空队列不报错():
    assert manager.stalled_tasks() == []


async def test_重试一批时会先记时间戳(monkeypatch):
    """先记后发：就算发起时抛异常，退避也已生效，不会变成紧循环。"""
    _pending("boom")
    calls = []

    async def _boom(task_id, rec, **kw):
        calls.append(task_id)
        raise RuntimeError("模拟发起失败")

    monkeypatch.setattr(manager, "_recover_one", _boom)
    monkeypatch.setattr(manager.storage, "save_pending_tasks", lambda *a, **k: None)

    n = await manager.retry_stalled_once()

    assert calls == ["boom"], "没发起重试"
    assert n == 0, "抛异常的不该算成功发起"
    assert state.pending_tasks["boom"]["last_attempt_at"] > 0, \
        "时间戳没记上 —— 下一轮会立刻再试，变成紧循环"


async def test_每轮不超过批量上限(monkeypatch):
    for i in range(20):
        _pending(f"t{i}")
    started = []

    async def _ok(task_id, rec, **kw):
        started.append(task_id)

    monkeypatch.setattr(manager, "_recover_one", _ok)
    monkeypatch.setattr(manager.storage, "save_pending_tasks", lambda *a, **k: None)

    await manager.retry_stalled_once()
    assert len(started) <= max(1, config.STALLED_RETRY_BATCH)
