# SPDX-License-Identifier: AGPL-3.0-or-later
"""控制网页标题「<名字> TGhelper」（2026-11-13，hyden 定）。"""
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import dashboard.main as dm


def test_名字的优先级():
    d = {"display_name": "", "hide_name": False}
    assert dm.brand_name(d, "") == "Hyden"                         # 没登录、没自定义
    assert dm.brand_name(d, "Alice") == "Alice"                    # 默认用登录的账号名
    assert dm.brand_name({**d, "display_name": "John"}, "Alice") == "John"   # 自定义优先
    assert dm.brand_name({**d, "hide_name": True, "display_name": "John"}, "Alice") == ""  # 隐藏


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "_BRANDING_FILE", tmp_path / "dashboard_branding.json")
    import config
    monkeypatch.setattr(config, "API_KEY", "")
    app = web.Application()
    app.router.add_get("/api/branding", dm._branding_get_handler)
    app.router.add_post("/api/branding", dm._branding_post_handler)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_保存后马上读得到_而且落盘(client, tmp_path):
    r = await client.get("/api/branding")
    assert (await r.json())["display_name"] == ""
    r = await client.post("/api/branding", json={"display_name": "  John\n的 ", "hide_name": False})
    assert r.status == 200
    assert (await r.json())["display_name"] == "John 的"           # 换行和多余空格去掉
    assert json.loads((tmp_path / "dashboard_branding.json").read_text(encoding="utf-8"))["display_name"] == "John 的"
    r = await client.post("/api/branding", json={"hide_name": True})   # 只改一项，另一项保留
    d = await r.json()
    assert d["hide_name"] is True and d["display_name"] == "John 的"


async def test_非法输入被拒(client):
    assert (await client.post("/api/branding", json={"display_name": "x" * 31})).status == 400
    assert (await client.post("/api/branding", json={"hide_name": "yes"})).status == 400
    assert (await client.post("/api/branding", data="not json")).status == 400


def test_文件坏了用默认(tmp_path, monkeypatch):
    f = tmp_path / "b.json"; f.write_text("{坏", encoding="utf-8")
    monkeypatch.setattr(dm, "_BRANDING_FILE", f)
    assert dm.load_branding() == {"display_name": "", "hide_name": False}
