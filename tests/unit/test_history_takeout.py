# SPDX-License-Identifier: AGPL-3.0-or-later
"""历史扫描走 takeout（#2013）：开关关着时和以前一模一样；开着时套 takeout；失败自动退回普通会话、不重不漏。

用真的 TelegramClient + 真的 iter_messages，只把最底层的网络调用（_call）换成一个假服务器，
这样 Telethon 内部的 takeout 代理机制（我们借用了它的私有类）一变，这里就会挂。
"""
import asyncio
import json
from datetime import datetime, timezone

import pytest
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl import functions, types

import config
from downloader.history import takeout

PEER = types.InputPeerChannel(channel_id=1, access_hash=1)
IDS = list(range(1, 251))          # 250 条，Telethon 一页 100 条 → 3 页


class FakeServer:
    """按 Telegram 的语义回 messages.getHistory，记下每个请求是不是套了 takeout。"""

    def __init__(self, ids=IDS, *, init_exc=None, takeout_fail_on_page=None, flood_on_page=None, delay=0):
        self.ids = ids
        self.delay = delay
        self.init_exc = init_exc
        self.takeout_fail_on_page = takeout_fail_on_page
        self.flood_on_page = flood_on_page
        self.calls = []                 # (是否套了 takeout, takeout_id, 内层请求类名)
        self.history_pages = {"takeout": 0, "plain": 0}
        self.history_reqs = []          # (是否 takeout, GetHistoryRequest 副本参数)

    async def call(self, _sender, request, ordered=False, flood_sleep_threshold=None):
        tk = isinstance(request, functions.InvokeWithTakeoutRequest)
        inner = request.query if tk else request
        self.calls.append((tk, request.takeout_id if tk else None, type(inner).__name__))
        if isinstance(inner, functions.account.InitTakeoutSessionRequest):
            if self.init_exc:
                raise self.init_exc
            return types.account.Takeout(id=4242)
        if isinstance(inner, functions.account.FinishTakeoutSessionRequest):
            return True
        if isinstance(inner, functions.messages.GetHistoryRequest):
            await asyncio.sleep(self.delay)
            key = "takeout" if tk else "plain"
            self.history_pages[key] += 1
            self.history_reqs.append((tk, inner.offset_id, inner.add_offset, inner.limit))
            if tk and self.takeout_fail_on_page == self.history_pages[key]:
                raise errors.TakeoutInvalidError(request=inner)
            if self.flood_on_page == self.history_pages[key]:
                raise errors.FloodWaitError(request=inner, capture=30)
            return self._page(inner)
        raise AssertionError(f"没想到的请求 {type(inner).__name__}")

    def _page(self, req):
        desc = sorted(self.ids, reverse=True)
        start = 0
        if req.offset_id:
            start = next((i for i, m in enumerate(desc) if m < req.offset_id), len(desc))
        start += req.add_offset
        end = start + req.limit
        page = desc[max(start, 0):max(end, 0)]
        msgs = [types.Message(id=i, peer_id=types.PeerChannel(1),
                              date=datetime(2026, 1, 1, tzinfo=timezone.utc), message="")
                for i in page]
        return types.messages.ChannelMessages(
            pts=1, count=len(self.ids), messages=msgs, topics=[], chats=[], users=[])


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(takeout, "_pool", takeout._Pool())
    logs = []
    monkeypatch.setattr(takeout._log, "info", lambda m, *a, **k: logs.append(("info", m)))
    monkeypatch.setattr(takeout._log, "warning", lambda m, *a, **k: logs.append(("warning", m)))

    def _make(on: bool, **kw):
        monkeypatch.setattr(config, "HISTORY_TAKEOUT", on, raising=False)
        srv = FakeServer(**kw)
        c = TelegramClient(StringSession(), 1, "x")
        c._call = srv.call
        return c, srv, logs
    return _make


async def _scan(c, **kw):
    out = []
    async for m in takeout.scan_messages(c, PEER, reverse=True, **kw):
        out.append(m.id)
    return out


# ── 开关关着：和以前完全一样 ─────────────────────────────────────────────────

async def test_关着就是原样的iter_messages(make):
    c, srv, logs = make(False)
    got = await _scan(c)
    assert got == IDS
    assert not any(tk for tk, _, _ in srv.calls)                      # 一个请求都没套 takeout
    assert not any(n.endswith("TakeoutSessionRequest") for _, _, n in srv.calls)
    assert not logs


async def test_关着时参数一个不改地交给iter_messages(make, monkeypatch):
    c, _, _ = make(False)
    seen = []

    async def fake_iter(chat, **kw):
        seen.append((chat, kw))
        yield types.Message(id=1, peer_id=types.PeerChannel(1), date=None, message="")
    monkeypatch.setattr(c, "iter_messages", fake_iter)
    kw = {"reverse": True, "min_id": 5, "max_id": 99, "offset_date": datetime(2026, 1, 1)}
    async for _ in takeout.scan_messages(c, 123, **kw):
        pass
    assert seen == [(123, kw)]


async def test_runner用的是scan_messages且关着时传的参数和以前一样(monkeypatch, tmp_path):
    """run_job 走 takeout.scan_messages；开关关着时最终调到 client.iter_messages(chat_id, reverse=True, min_id=…)。"""
    import downloader.state as state
    from downloader.history import runner

    monkeypatch.setattr(config, "HISTORY_TAKEOUT", False, raising=False)
    seen = []

    class C:
        async def iter_messages(self, chat, **kw):
            seen.append((chat, kw))
            for i in (11, 12):
                yield types.Message(id=i, peer_id=types.PeerChannel(1), date=datetime(2026, 1, 1), message="")
    monkeypatch.setattr(runner, "client", C())
    monkeypatch.setattr(runner, "is_downloadable_media", lambda m: True)
    monkeypatch.setattr(runner, "media_filename", lambda m: f"f{m.id}")
    monkeypatch.setattr(runner, "message_size", lambda m: 0)
    monkeypatch.setattr(runner, "_extract_fuid", lambda m: None)
    monkeypatch.setattr(runner, "_persist", lambda: None)

    async def _nob():
        pass
    import downloader.web.websocket as ws
    monkeypatch.setattr(ws, "_broadcast", _nob)
    monkeypatch.setattr(state, "completed_downloads", [], raising=False)
    monkeypatch.setattr(state, "history_jobs", {"j1": {
        "job_id": "j1", "scene": "C", "chat_id": -1001, "status": "running", "phase": "scanning",
        "last_seen_id": 10, "total_scanned": 0, "total_queued": 0, "total_skipped": 0,
        "total_duplicates": 0, "scan_results": [], "updated_at": "", "filter_type": None,
    }}, raising=False)
    await runner.run_job("j1")
    assert seen == [(-1001, {"reverse": True, "min_id": 10})]
    j = state.history_jobs["j1"]
    assert j["status"] == "ready_for_selection" and [r["message_id"] for r in j["scan_results"]] == [11, 12]


# ── 开关打开 ─────────────────────────────────────────────────────────────────

async def test_打开后扫描请求都套takeout_用完就关(make, tmp_path):
    c, srv, _ = make(True)
    got = await _scan(c)
    assert got == IDS
    hist = [(tk, tid) for tk, tid, n in srv.calls if n == "GetHistoryRequest"]
    assert hist and all(tk and tid == 4242 for tk, tid in hist)
    names = [n for _, _, n in srv.calls]
    assert names[0] == "InitTakeoutSessionRequest" and names[-1] == "FinishTakeoutSessionRequest"
    assert not (tmp_path / "takeout.json").exists()        # 正常关掉了，不留记录


async def test_没有动session里的takeout_id(make):
    c, _, _ = make(True)
    await _scan(c)
    assert c.session.takeout_id is None


async def test_两个job同时扫共用一个takeout会话(make):
    c, srv, _ = make(True, delay=0.02)
    a, b = await asyncio.gather(_scan(c), _scan(c))
    assert a == IDS and b == IDS
    names = [n for _, _, n in srv.calls]
    assert names.count("InitTakeoutSessionRequest") == 1
    assert names.count("FinishTakeoutSessionRequest") == 1 and names[-1] == "FinishTakeoutSessionRequest"


async def test_中途break也会关掉takeout(make):
    c, srv, _ = make(True)
    import contextlib
    async with contextlib.aclosing(takeout.scan_messages(c, PEER, reverse=True)) as it:
        async for m in it:
            if m.id == 30:
                break
    assert [n for _, _, n in srv.calls][-1] == "FinishTakeoutSessionRequest"


# ── 退回普通会话 ─────────────────────────────────────────────────────────────

async def test_申请失败就退回普通会话并记日志(make):
    c, srv, logs = make(True, init_exc=errors.TakeoutInitDelayError(request=None, capture=3600))
    got = await _scan(c)
    assert got == IDS
    assert not any(tk for tk, _, n in srv.calls if n == "GetHistoryRequest")
    assert any(lv == "warning" and "退回普通会话" in m for lv, m in logs)
    # 冷却期内第二个 job 不再去撞
    await _scan(c)
    assert [n for _, _, n in srv.calls].count("InitTakeoutSessionRequest") == 1


async def test_用到一半失效就退回普通会话接着扫_不重不漏(make):
    c, srv, logs = make(True, takeout_fail_on_page=2)      # 第 2 页 takeout 请求报 TAKEOUT_INVALID
    got = await _scan(c)
    assert got == IDS                                       # 1..250 一条不少、一条不重
    assert srv.history_pages["takeout"] == 2 and srv.history_pages["plain"] >= 1
    assert any(lv == "warning" and "中途失败" in m and "已扫 100 条" in m for lv, m in logs)


async def test_退回后接着扫保留用户的上限(make):
    c, _, _ = make(True, takeout_fail_on_page=2)
    out = []
    async for m in takeout.scan_messages(c, PEER, reverse=True, min_id=20, max_id=200):
        out.append(m.id)
    assert out == list(range(21, 200))


async def test_限流照旧抛给runner_不算takeout坏了(make):
    c, srv, logs = make(True, flood_on_page=2)
    c.flood_sleep_threshold = 0
    with pytest.raises(errors.FloodWaitError):
        await _scan(c)
    assert not any("退回" in m for _, m in logs)
    assert [n for _, _, n in srv.calls][-1] == "FinishTakeoutSessionRequest"


async def test_上次进程留下的takeout会话先关掉(make, tmp_path):
    (tmp_path / "takeout.json").write_text(json.dumps({"takeout_id": 77}), encoding="utf-8")
    c, srv, _ = make(True)
    await _scan(c)
    assert srv.calls[0] == (True, 77, "FinishTakeoutSessionRequest")
    assert srv.calls[1][2] == "InitTakeoutSessionRequest"


async def test_限流计数():
    import logging
    takeout.install_flood_counter()
    n0, s0 = takeout.flood_counter.count, takeout.flood_counter.seconds
    logging.getLogger("telethon.client.users").info(
        "Sleeping%s for %ds (%s) on %s flood wait", "", 12, "0:00:12", "GetHistoryRequest")
    assert takeout.flood_counter.count - n0 == 1 and takeout.flood_counter.seconds - s0 == 12
