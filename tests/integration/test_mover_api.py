# SPDX-License-Identifier: AGPL-3.0-or-later
"""mover /api/move：黑名单、幂等性。

不启动真服务；直接 import handler，用 aiohttp 测试 client。
需要 mock 掉 manager.start() 和 storage 路径。
"""
import os
import json
from pathlib import Path

import pytest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


@pytest.fixture
async def mover_app(tmp_path: Path, monkeypatch):
    """构建一个隔离的 mover app（不启动 manager 后台 task）。"""
    # 隔离 mover_state.json 到 tmp
    import mover.storage as storage
    monkeypatch.setattr(storage, "MOVER_STATE_FILE", tmp_path / "mover_state.json")

    import mover.state as state
    state.tasks = {}
    state.paused = False

    import config
    monkeypatch.setattr(config, "API_KEY", "")  # 关闭鉴权简化

    from common.auth import auth_middleware
    from mover.web.api import _api_move, _api_tasks_get, _api_open

    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post("/api/move", _api_move)
    app.router.add_get("/api/tasks/{task_id}", _api_tasks_get)
    app.router.add_post("/api/open", _api_open)
    return app


async def test_blacklist_etc(mover_app):
    async with TestClient(TestServer(mover_app)) as client:
        r = await client.post("/api/move", json={
            "source": "/tmp/foo", "target": "/etc/dst", "task_id": "t1",
        })
        assert r.status == 403
        body = await r.json()
        assert "blacklist" in body["error"]


async def test_blacklist_proc(mover_app):
    async with TestClient(TestServer(mover_app)) as client:
        r = await client.post("/api/move", json={
            "source": "/tmp/foo", "target": "/proc/dst", "task_id": "t1",
        })
        assert r.status == 403


async def test_relative_target_rejected(mover_app):
    async with TestClient(TestServer(mover_app)) as client:
        r = await client.post("/api/move", json={
            "source": "/tmp/foo", "target": "./relative", "task_id": "t1",
        })
        assert r.status == 400


async def test_idempotency_done_returns_already_moved(mover_app, tmp_path):
    """P2-11: 已完成的 task_id 重发应返回 already_moved，即使 source 不存在。"""
    import mover.state as state
    state.tasks["done-task"] = {
        "task_id": "done-task",
        "source": "/tmp/already-deleted",
        "target": str(tmp_path / "moved.zip"),
        "status": "done",
        "created_at": "2026-01-01T00:00:00",
        "completed_at": "2026-01-01T00:01:00",
        "error": None,
        "failed_at": None,
        "error_source": None,
    }
    async with TestClient(TestServer(mover_app)) as client:
        r = await client.post("/api/move", json={
            "source": "/tmp/already-deleted",
            "target": str(tmp_path),
            "task_id": "done-task",
        })
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is True
        assert body["already_moved"] is True
        assert body["target_path"] == str(tmp_path / "moved.zip")


# ── 黑名单绕过（2026-09-17 修）──────────────────────────────────────────
#
# 原来只 resolve 目标、不 resolve 黑名单。macOS 上 /etc → private/etc 是软链，
# 于是 `/etc/dst` resolve 成 `/private/etc/dst`，跟黑名单里的 `/etc` 比不上 → 放行。
# **所以在 macOS 上这条黑名单从来没生效过。**
# `test_blacklist_etc` 长期红着其实一直在报这个真问题。

async def test_黑名单挡得住软链绕过(mover_app):
    """macOS 上 /etc、/var、/tmp 都是软链，两边都 resolve 才比得上。
    /private/etc、/private/var 在 Linux 上不存在，靠黑名单里写死的条目拦（2026-11-10）。"""
    from mover.web.api import _is_blacklisted
    from pathlib import Path
    for bad in ("/etc/dst", "/private/etc/dst", "/var/dst", "/private/var/dst",
                "/usr/dst", "/bin/dst", "/proc/dst"):
        assert _is_blacklisted(Path(bad)), f"{bad} 没被拦住"


async def test_黑名单挡得住上级目录绕过(mover_app):
    from mover.web.api import _is_blacklisted
    from pathlib import Path
    assert _is_blacklisted(Path("/tmp/../etc/dst")), "用 ../ 绕进 /etc 没被拦住"


async def test_正常目标不被误伤(mover_app):
    from mover.web.api import _is_blacklisted
    from pathlib import Path
    for ok in ("/Users/me/nas/tghelper/x", "/mnt/data/x", "/home/me/x"):
        assert not _is_blacklisted(Path(ok)), f"{ok} 被误拦了"


# ── 白名单（2026-11-13）：搬运目标必须在数据目录之下 ──────────────────────

@pytest.fixture
def roots(tmp_path, monkeypatch):
    import config
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_ROOT", str(data))
    monkeypatch.setattr(config, "DOWNLOAD_DIR", data / "telegramDMZ" / "download")
    monkeypatch.setattr(config, "WATCH_PATH", data / "telegramDMZ" / "move")
    monkeypatch.setattr(config, "OUTPUT_PATH", data / "telegramDMZ" / "unzip")
    monkeypatch.delenv("MOVE_ALLOWED_ROOTS", raising=False)
    return tmp_path


def test_白名单_数据目录之下放行_之外拒绝(roots, monkeypatch):
    from mover.web.api import _target_in_allowed_roots
    assert _target_in_allowed_roots(roots / "data" / "telegramDMZ" / "move")
    assert _target_in_allowed_roots(roots / "data" / "其他子目录")
    assert not _target_in_allowed_roots(roots / "elsewhere")
    assert not _target_in_allowed_roots(roots / "data" / ".." / "elsewhere")   # ../ 绕不出去
    assert not _target_in_allowed_roots(Path("/Library/x"))                    # 黑名单没覆盖的系统目录
    monkeypatch.setenv("MOVE_ALLOWED_ROOTS", f"{roots / 'elsewhere'}, relative/ignored")
    assert _target_in_allowed_roots(roots / "elsewhere" / "x")


async def test_白名单_接口返回403(mover_app, roots):
    src = roots / "data" / "telegramDMZ" / "download" / "a.zip"
    src.parent.mkdir(parents=True); src.write_bytes(b"x")
    async with TestClient(TestServer(mover_app)) as client:
        r = await client.post("/api/move", json={
            # 别用 tmp_path 下的目录当「之外」：macOS 的 tmp 在 /private/var 里，会先被黑名单挡掉
            "source": str(src), "target": str(Path.home() / "tghelper-whitelist-test-x"), "task_id": "w1"})
        assert r.status == 403
        assert "allowed" in (await r.json())["error"]
