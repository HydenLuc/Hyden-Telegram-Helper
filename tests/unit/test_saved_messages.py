# SPDX-License-Identifier: AGPL-3.0-or-later
"""「我的收藏」全局唯一例外（hyden 2026-09-24 定）。

## 这组用例防的是什么

收藏（Saved Messages）悄悄停了好几天，是两个坑叠在一起：

① 启动默认两个暂停开关都开，收藏标的 exempt → 归 exempt_paused 管 → 重启后一直停着。
② Telethon 把「发给自己、且不是转发」的消息强制判成 outgoing，而 handler 原来挂的是
   `NewMessage(incoming=True)` → 直接上传进收藏的文件**从来**没被收过，只有转发的能下。

规则：只要服务在跑，收藏的媒体永远放行——不看暂停开关、不看监听列表、不看方向。
**其余聊天的行为一点都不能变**（这是反向用例那一半的意义）。
"""
from pathlib import Path

import pytest

from downloader import state
from downloader.tg import handlers

ME = 111111111            # 自己的 user id（占位） = 收藏的 chat_id
OTHER_USER = 123456789    # 别人的私聊
CHANNEL = -1001234567890  # 普通频道
EXEMPT = -1009999999999   # 例外频道


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(handlers, "_current_self_id", lambda: ME)
    saved = (dict(state.watched), state.monitoring_paused, state.exempt_paused,
             state.saved_paused)
    state.watched.clear()
    state.watched.update({
        str(CHANNEL): {"name": "普通", "exempt": False},
        str(EXEMPT):  {"name": "例外", "exempt": True},
        str(ME):      {"name": "白",   "exempt": True},
    })
    state.monitoring_paused = False
    state.exempt_paused = False
    state.saved_paused = False
    yield
    state.watched.clear()
    state.watched.update(saved[0])
    state.monitoring_paused, state.exempt_paused, state.saved_paused = (
        saved[1], saved[2], saved[3])


def gate(chat_id, *, out=False, private=None):
    if private is None:
        private = chat_id > 0
    return handlers._passes_listen_gate(chat_id, out=out, is_private=private)


# ── 收藏：永远放行 ──────────────────────────────────────────────────────

def test_两个暂停全开时收藏照样下():
    """核心用例①：这就是它停了好几天的原因。"""
    state.monitoring_paused = True
    state.exempt_paused = True
    assert gate(ME)


def test_直接上传进收藏也要下():
    """核心用例②：Telethon 把这类消息判成 outgoing，原来一律被丢。"""
    assert gate(ME, out=True)


def test_暂停加直接上传叠在一起也要下():
    state.monitoring_paused = True
    state.exempt_paused = True
    assert gate(ME, out=True)


def test_收藏被移出监听列表也照样下():
    """「永久打开」：误点了取消监听也不该让它停。"""
    state.watched.pop(str(ME))
    assert gate(ME)


def test_还不知道自己是谁时不误判(monkeypatch):
    """self id 未知（理论上启动时不会发生）→ 退回普通规则，不能把谁都当成收藏。"""
    monkeypatch.setattr(handlers, "_current_self_id", lambda: None)
    assert not handlers._is_saved_messages(ME, True)
    assert not gate(ME, out=True), "self id 未知时 outgoing 不该放行"


def test_同号的非私聊不算收藏():
    """chat_id 碰巧等于自己的 id 但不是私聊 → 不是收藏（防御性，正常不会出现）。"""
    assert not handlers._is_saved_messages(ME, False)


# ── 其余聊天：行为必须和以前一模一样 ─────────────────────────────────────

def test_别的聊天里自己发的媒体不下():
    """反向用例：handler 不再按方向过滤后，这条全靠 gate 兜着。"""
    assert not gate(CHANNEL, out=True)
    assert not gate(OTHER_USER, out=True)
    assert not gate(EXEMPT, out=True)


def test_普通频道受全局暂停控制():
    assert gate(CHANNEL)
    state.monitoring_paused = True
    assert not gate(CHANNEL)
    state.exempt_paused = True
    state.monitoring_paused = False
    assert gate(CHANNEL), "例外暂停不该影响普通频道"


def test_例外频道受例外暂停控制():
    assert gate(EXEMPT)
    state.monitoring_paused = True
    assert gate(EXEMPT), "全局暂停不该影响例外频道"
    state.exempt_paused = True
    assert not gate(EXEMPT)


def test_没监听的聊天不下():
    assert not gate(-1000000000001)
    assert not gate(OTHER_USER)


# ── 装配：handler 真的不再按方向过滤 ─────────────────────────────────────

def test_handler没有挂incoming过滤():
    """光改 gate 没用：decorator 上还挂着 incoming=True 的话，收藏的 outgoing 根本进不来。"""
    import inspect
    src = inspect.getsource(handlers)
    assert "@client.on(events.NewMessage())\nasync def handle_media" in src, \
        "handle_media 又挂回了方向过滤——收藏里直接上传的文件会被 Telethon 层丢掉"
    assert "_passes_listen_gate(" in inspect.getsource(handlers.handle_media)


# ── 收藏开关 saved_paused（2026-11-10）──────────────────────────────────

def test_收藏开关关掉就不收():
    """核心用例：以前没有开关，「关监听」关不掉收藏。"""
    state.saved_paused = True
    assert not gate(ME)
    assert not gate(ME, out=True)


def test_收藏开关只管收藏():
    """收藏暂停不能连累别的聊天。"""
    state.saved_paused = True
    assert gate(CHANNEL)
    assert gate(EXEMPT)


def test_另外两个开关不管收藏():
    """全局暂停 / 例外暂停开着，只要收藏开关没关，收藏照收。"""
    state.monitoring_paused = True
    state.exempt_paused = True
    state.saved_paused = False
    assert gate(ME)
    state.saved_paused = True
    assert not gate(ME)


def test_收藏开关接口落盘(monkeypatch):
    """开关要持久化：重启后保持上次的选择。"""
    import asyncio
    from downloader.web import api

    store = {}
    monkeypatch.setattr(api.storage, "load_settings", lambda: dict(store))
    monkeypatch.setattr(api.storage, "save_settings", lambda d: store.update(d))

    async def _noop():
        return None
    monkeypatch.setattr(api, "_broadcast", _noop)

    asyncio.run(api._api_saved_pause(None))
    assert state.saved_paused is True and store["saved_paused"] is True
    asyncio.run(api._api_saved_resume(None))
    assert state.saved_paused is False and store["saved_paused"] is False


def test_启动时没设置就按暂停():
    """设置文件里没有 saved_paused 键时，bot.py 必须按「暂停」处理。"""
    src = Path(__file__).resolve().parents[2].joinpath("bot.py").read_text(encoding="utf-8")
    assert 'load_settings().get("saved_paused", True)' in src
