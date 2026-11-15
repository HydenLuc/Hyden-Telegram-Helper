# SPDX-License-Identifier: AGPL-3.0-or-later
"""dashboard「服务启停」面板后端（2026-11-11 改成只做 Docker 版）。

原生部署：一律返回「不支持」，前端隐藏面板。
Docker：转给 control 服务，dashboard 自己不碰 docker.sock。
（2026-09-28 ~ 11-11 的 launchctl 版已删，它只在作者自己的 Mac 上能用。）
"""
import config
from common import control_client
from dashboard import services


async def test_原生部署_面板隐藏(monkeypatch):
    monkeypatch.setattr(config, "IS_DOCKER", False)
    status, body = await services.list_services()
    assert status == 200 and body["supported"] is False and body["services"] == []


async def test_原生部署_启停一律拒绝且不去连控制服务(monkeypatch):
    async def boom(*a, **kw):
        raise AssertionError("原生部署不该去连控制服务")

    monkeypatch.setattr(config, "IS_DOCKER", False)
    monkeypatch.setattr(control_client, "call", boom)
    status, body = await services.act("downloader", "stop")
    assert status == 501 and not body["ok"]


async def test_Docker_转给控制服务(monkeypatch):
    calls = []

    async def fake_call(method, path, timeout=30):
        calls.append((method, path))
        return 200, {"ok": True, "services": [{"name": "downloader", "state": "running"}]}

    monkeypatch.setattr(config, "IS_DOCKER", True)
    monkeypatch.setattr(control_client, "call", fake_call)
    status, body = await services.list_services()
    assert status == 200 and body["supported"] is True
    await services.act("mover", "restart")
    assert calls == [("GET", "/api/services"), ("POST", "/api/services/mover/restart")]


async def test_Docker_控制服务连不上要如实报错(monkeypatch):
    monkeypatch.setattr(config, "IS_DOCKER", True)
    monkeypatch.setattr(config, "CONTROL_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "CONTROL_PORT", 1)        # 没人听的端口
    status, body = await services.list_services()
    assert status == 503 and body["supported"] is True and "连不上控制服务" in body["message"]
