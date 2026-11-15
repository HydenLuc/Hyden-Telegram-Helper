# SPDX-License-Identifier: AGPL-3.0-or-later
"""control 服务：只能看 / 启停**本项目**的几个容器（2026-11-11）。

control 挂了 docker.sock，等于拿着宿主机 root。这组用例钉死它「能碰什么、不能碰什么」：
  ① 别的 compose 项目的容器绝不能出现、也绝不能被启停
  ② 只认 downloader / mover / unzipper / dashboard；dashboard 只能看
  ③ 只有 start / stop / restart 三个动作
"""
import pytest

from control import docker_api as d

PROJECT = "tghelper"


def _c(svc, state="running", project=PROJECT, cid=None):
    return {
        "Id": cid or f"id-{project}-{svc}",
        "State": state,
        "Status": "Up 5 minutes" if state == "running" else "Exited (0) 1 minute ago",
        "Labels": {d.LABEL_PROJECT: project, d.LABEL_SERVICE: svc},
    }


# ── 筛选 ────────────────────────────────────────────────────────────────

def test_别的项目的容器绝不能出现():
    """核心用例：同一台机器上 Immich、Frigate 也是 compose 起的，服务名可能也叫 dashboard。"""
    got = d.summarize([
        _c("downloader"),
        _c("dashboard", project="immich"),       # 别的项目、同名服务
        _c("frigate", project="frigate"),
    ], PROJECT)
    ids = [s["container_id"] for s in got if s["container_id"]]
    assert ids == ["id-tghelper-downloader"]


def test_只显示四个服务_顺序固定():
    got = d.summarize([_c("control"), _c("unzipper"), _c("mover"), _c("downloader"), _c("dashboard")], PROJECT)
    assert [s["name"] for s in got] == ["downloader", "mover", "unzipper", "dashboard"]


def test_状态归类():
    got = {s["name"]: s for s in d.summarize(
        [_c("downloader"), _c("mover", "exited"), _c("unzipper", "restarting")], PROJECT)}
    assert got["downloader"]["state"] == "running"
    assert got["mover"]["state"] == "stopped"
    assert got["unzipper"]["state"] == "starting"
    assert got["dashboard"]["state"] == "missing"


def test_dashboard只读():
    got = {s["name"]: s for s in d.summarize([_c(n) for n in d.VISIBLE], PROJECT)}
    assert got["dashboard"]["controllable"] is False
    assert all(got[n]["controllable"] for n in ("downloader", "mover", "unzipper"))


# ── 动作校验 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,action,ok", [
    ("downloader", "stop", True),
    ("mover", "restart", True),
    ("unzipper", "start", True),
    ("dashboard", "stop", False),      # 停了网页就没了
    ("control", "stop", False),        # 不在可见清单里
    ("immich_server", "stop", False),  # 别的项目
    ("downloader", "rm", False),       # 不允许的动作
    ("downloader", "exec", False),
])
def test_动作白名单(name, action, ok):
    assert (d.check_action(name, action) is None) is ok


async def test_停服务只打给本项目的那个容器(monkeypatch):
    calls = []

    async def fake_call(method, path, **kw):
        calls.append((method, path))
        if path.startswith("/containers/json"):
            return 200, [_c("downloader"), _c("downloader", project="other", cid="id-other")]
        return 204, None

    async def fake_project():
        return PROJECT

    monkeypatch.setattr(d, "docker_call", fake_call)
    monkeypatch.setattr(d, "own_project", fake_project)
    r = await d.do_action("downloader", "stop")
    assert r["ok"]
    posts = [p for m, p in calls if m == "POST"]
    assert posts == [f"/containers/id-tghelper-downloader/stop?t={d.STOP_TIMEOUT_S}"]


async def test_本来就停着也算成功(monkeypatch):
    async def fake_call(method, path, **kw):
        if path.startswith("/containers/json"):
            return 200, [_c("mover", "exited")]
        return 304, None

    async def fake_project():
        return PROJECT

    monkeypatch.setattr(d, "docker_call", fake_call)
    monkeypatch.setattr(d, "own_project", fake_project)
    r = await d.do_action("mover", "stop")
    assert r["ok"] and "本来就是" in r["message"]


async def test_被拒绝的动作根本不去碰Docker(monkeypatch):
    async def boom(*a, **kw):
        raise AssertionError("不该调 Docker")

    monkeypatch.setattr(d, "docker_call", boom)
    r = await d.do_action("dashboard", "stop")
    assert not r["ok"] and r["http"] == 403


# ── 不健康自动重启（2026-11-13）────────────────────────────────────────

import asyncio

from control import autoheal as ah


def test_autoheal_冷却期内不重复重启():
    h = ah.Healer(cooldown_s=600, max_per_hour=3)
    assert h.decide("downloader", 0) == (True, "")
    h.record("downloader", 0)
    assert h.decide("downloader", 300) == (False, "cooldown")
    assert h.decide("downloader", 601)[0] is True
    assert h.decide("mover", 300)[0] is True          # 各服务分开算


def test_autoheal_一小时超过上限就停手_过了窗口恢复():
    h = ah.Healer(cooldown_s=10, max_per_hour=3)
    for t in (0, 100, 200):
        assert h.decide("unzipper", t)[0]
        h.record("unzipper", t)
    assert h.decide("unzipper", 300) == (False, "too_many")
    assert h.decide("unzipper", 3601)[0] is True      # 第一次那条滑出窗口


def _fake_docker(monkeypatch, unhealthy, calls, restart_status=204):
    async def own_project():
        return PROJECT

    async def docker_call(method, path, *, timeout=40):
        calls.append((method, path))
        if method == "GET":
            return 200, unhealthy
        return restart_status, None

    async def no_notify(_text):
        calls.append(("NOTIFY", _text))

    monkeypatch.setattr(d, "own_project", own_project)
    monkeypatch.setattr(d, "docker_call", docker_call)
    monkeypatch.setattr(ah, "_notify", no_notify)


def test_autoheal_只重启本项目的不健康服务(monkeypatch):
    calls = []
    _fake_docker(monkeypatch, [
        _c("downloader"),
        _c("dashboard", project="immich"),     # 别的项目：绝不能碰
        _c("control"),                          # 不在四个服务里：不碰
    ], calls)
    got = asyncio.run(ah.heal_once(ah.Healer(), now=0))
    assert got == ["downloader"]
    posts = [p for m, p in calls if m == "POST"]
    assert posts == [f"/containers/id-tghelper-downloader/restart?t={d.STOP_TIMEOUT_S}"]
    get = [p for m, p in calls if m == "GET"][0]
    assert "unhealthy" in get and "tghelper" in get


def test_autoheal_放弃时只通知一次(monkeypatch):
    calls = []
    _fake_docker(monkeypatch, [_c("mover")], calls)
    h = ah.Healer(cooldown_s=0, max_per_hour=1)
    asyncio.run(ah.heal_once(h, now=0))          # 重启一次
    asyncio.run(ah.heal_once(h, now=10))         # 超上限 → 放弃 + 通知
    asyncio.run(ah.heal_once(h, now=20))         # 已放弃 → 不再通知
    notes = [p for m, p in calls if m == "NOTIFY"]
    assert sum("停止自动重启" in n for n in notes) == 1
    assert len([1 for m, _ in calls if m == "POST"]) == 1
