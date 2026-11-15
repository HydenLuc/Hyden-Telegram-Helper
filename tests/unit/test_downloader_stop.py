# SPDX-License-Identifier: AGPL-3.0-or-later
"""下载器页「⏹ 停止」按钮的接口 `/api/downloader/stop`（2026-11-11 改成只做 Docker 版）。

## 钉死的事

1. **绝不能「回 ok 但其实没停」**：2026-11-11 之前是 launchctl 版，在 Docker 里 launchctl
   不存在、异常被吞掉，却照样回 ok:true —— 界面显示已停，实际根本没停。
   现在先确认控制服务连得上，连不上就如实报 503。
2. **响应先发出去，再停**：停的是自己所在的容器，顺序反了前端会拿到 Connection reset。
3. 原生部署返回 501（原生用 ./stop.sh）。
"""
import asyncio
import json

import config
from common import control_client
from downloader.web import api


async def _stop():
    return await api._api_downloader_stop(None)


async def test_原生部署返回501且不去连控制服务(monkeypatch):
    async def boom(*a, **kw):
        raise AssertionError("原生部署不该去连控制服务")

    monkeypatch.setattr(config, "IS_DOCKER", False)
    monkeypatch.setattr(control_client, "call", boom)
    resp = await _stop()
    assert resp.status == 501


async def test_控制服务连不上要如实报错_不能假装停了(monkeypatch):
    """核心用例 1。"""
    monkeypatch.setattr(config, "IS_DOCKER", True)
    monkeypatch.setattr(config, "CONTROL_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "CONTROL_PORT", 1)
    resp = await _stop()
    body = json.loads(resp.body.decode())
    assert resp.status == 503 and body["ok"] is False


async def test_先回响应再请控制服务停(monkeypatch):
    """核心用例 2。"""
    calls = []

    async def fake_call(method, path, timeout=30):
        calls.append((method, path))
        return 200, {"ok": True, "services": []}

    monkeypatch.setattr(config, "IS_DOCKER", True)
    monkeypatch.setattr(control_client, "call", fake_call)
    monkeypatch.setattr(api, "_STOP_DELAY_S", 0.05)

    resp = await _stop()
    assert resp.status == 200 and json.loads(resp.body.decode())["stopping"] is True
    assert ("POST", "/api/services/downloader/stop") not in calls, "响应还没回就去停了"

    await asyncio.sleep(0.2)
    assert ("POST", "/api/services/downloader/stop") in calls


def test_路由已注册():
    from downloader.web.server import _build_web_app
    routes = [(r.method, r.resource.canonical) for r in _build_web_app().router.routes()]
    assert ("POST", "/api/downloader/stop") in routes


def test_status里带is_docker给前端决定显不显示按钮():
    import inspect
    assert '"is_docker":' in inspect.getsource(api._api_status)
