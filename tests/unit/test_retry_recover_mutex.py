# SPDX-License-Identifier: AGPL-3.0-or-later
"""downloader：重试接口与崩溃恢复扫描的并发互斥。

task_id 已经在 active_downloads（正在下载中，或另一路径已抢先接管）时，不能
再被重试接口 / 恢复扫描重复启动一次 download_one——否则两个 download_one 并发
写同一批 .partN 会互相破坏。
"""
import pytest

import downloader.state as state


@pytest.fixture(autouse=True)
def _isolate_state():
    state.active_downloads = {}
    state.pending_tasks = {}
    state.completed_downloads = []
    yield
    state.active_downloads = {}
    state.pending_tasks = {}
    state.completed_downloads = []


async def test_retry_skips_task_already_active():
    from downloader.web.api import _retry_one_task

    state.active_downloads["t1"] = {"task_id": "t1", "status": "downloading"}
    result = await _retry_one_task("t1")
    assert result["ok"] is False
    assert "下载中" in result["error"]


async def test_recover_skips_task_already_active(monkeypatch):
    from downloader.download.manager import _recover_one
    from downloader.tg.client import client

    state.active_downloads["t2"] = {"task_id": "t2", "status": "downloading"}
    rec = {
        "chat_id": 1, "message_id": 2, "save_path": "/nonexistent/path.bin",
        "expected_size": 100, "grouped_id": None,
    }
    state.pending_tasks["t2"] = rec

    async def _boom(*a, **kw):
        raise AssertionError("task_id 已在 active_downloads 时不该再重取 message / 重新下载")

    monkeypatch.setattr(client, "get_messages", _boom)

    # 不抛异常即代表 guard 生效（否则会走到 _boom 触发 AssertionError）
    await _recover_one("t2", rec)
