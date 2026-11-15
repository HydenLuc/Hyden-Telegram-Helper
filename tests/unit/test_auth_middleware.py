# SPDX-License-Identifier: AGPL-3.0-or-later
"""common/auth.py：/ 首页在设置 API_KEY 后也必须鉴权（否则明文泄露 key）。"""
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from common.auth import auth_middleware


async def _ok(_request):
    return web.json_response({"ok": True, "page": "index with embedded key"})


@pytest.fixture
def app_with_key(monkeypatch):
    import config
    monkeypatch.setattr(config, "API_KEY", "secret123")
    application = web.Application(middlewares=[auth_middleware])
    application.router.add_get("/", _ok)
    application.router.add_get("/api/status", _ok)
    return application


@pytest.fixture
def app_no_key(monkeypatch):
    import config
    monkeypatch.setattr(config, "API_KEY", "")
    application = web.Application(middlewares=[auth_middleware])
    application.router.add_get("/", _ok)
    application.router.add_get("/api/status", _ok)
    return application


async def test_index_rejected_without_key(app_with_key):
    async with TestClient(TestServer(app_with_key)) as client:
        r = await client.get("/")
        assert r.status == 401


async def test_index_accepted_with_query_key(app_with_key):
    async with TestClient(TestServer(app_with_key)) as client:
        r = await client.get("/?key=secret123")
        assert r.status == 200


async def test_index_accepted_with_header_key(app_with_key):
    """dashboard 反代模块首页时走这条路径。"""
    async with TestClient(TestServer(app_with_key)) as client:
        r = await client.get("/", headers={"X-API-Key": "secret123"})
        assert r.status == 200


async def test_index_rejected_with_wrong_key(app_with_key):
    async with TestClient(TestServer(app_with_key)) as client:
        r = await client.get("/?key=wrong")
        assert r.status == 401


async def test_api_still_requires_header_key(app_with_key):
    async with TestClient(TestServer(app_with_key)) as client:
        r = await client.get("/api/status")
        assert r.status == 401
        r2 = await client.get("/api/status", headers={"X-API-Key": "secret123"})
        assert r2.status == 200


async def test_no_key_configured_index_open(app_no_key):
    """API_KEY 未设置时保持旧行为：/ 不鉴权（向下兼容）。"""
    async with TestClient(TestServer(app_no_key)) as client:
        r = await client.get("/")
        assert r.status == 200


# ── 跨站请求（2026-11-15）：默认没密码时，别的网站不能借你的浏览器调写接口 ────────────

async def _post_ok(_request):
    return web.json_response({"ok": True})


def _app(monkeypatch, key=""):
    import config
    monkeypatch.setattr(config, "API_KEY", key)
    application = web.Application(middlewares=[auth_middleware])
    application.router.add_post("/api/move", _post_ok)
    application.router.add_get("/api/status", _ok)
    return application


async def test_别的网站发写请求_拒绝(monkeypatch):
    async with TestClient(TestServer(_app(monkeypatch))) as c:
        r = await c.post("/api/move", json={}, headers={"Origin": "https://evil.example"})
        assert r.status == 403


async def test_同源和没有Origin的写请求_放行(monkeypatch):
    async with TestClient(TestServer(_app(monkeypatch))) as c:
        same = f"http://{c.server.host}:{c.server.port}"
        assert (await c.post("/api/move", json={}, headers={"Origin": same})).status == 200
        assert (await c.post("/api/move", json={})).status == 200        # curl / 服务间调用


async def test_Origin_null_当跨站(monkeypatch):
    async with TestClient(TestServer(_app(monkeypatch))) as c:
        assert (await c.post("/api/move", json={}, headers={"Origin": "null"})).status == 403


async def test_反向代理改写Host时认X_Forwarded_Host(monkeypatch):
    async with TestClient(TestServer(_app(monkeypatch))) as c:
        r = await c.post("/api/move", json={}, headers={
            "Origin": "https://tg.example.org", "X-Forwarded-Host": "tg.example.org"})
        assert r.status == 200


async def test_跨站GET不拦_由浏览器同源策略管(monkeypatch):
    async with TestClient(TestServer(_app(monkeypatch))) as c:
        assert (await c.get("/api/status", headers={"Origin": "https://evil.example"})).status == 200


def test_WebSocket_跨站拒绝(monkeypatch):
    import config
    from unittest.mock import MagicMock
    from common.auth import check_ws_auth
    monkeypatch.setattr(config, "API_KEY", "")
    req = MagicMock()
    req.headers = {"Origin": "https://evil.example"}
    req.host = "127.0.0.1:8091"
    assert check_ws_auth(req) is False
    req.headers = {"Origin": "http://127.0.0.1:8091"}
    assert check_ws_auth(req) is True
