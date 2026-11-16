# SPDX-License-Identifier: AGPL-3.0-or-later
"""粘贴链接下载（链接解析 + 入队）和「状态」命令。不连真实 Telegram。"""
import asyncio
from types import SimpleNamespace

import pytest

import config
from downloader import state
from downloader.tg import handlers
from downloader.tg.handlers import parse_message_links as parse


# ── 链接解析 ────────────────────────────────────────────────────────────

def test_公开频道链接():
    assert parse("https://t.me/somechannel/123") == [("somechannel", 123)]


def test_私有链接_chat_id拼成负100前缀整数():
    r = parse("https://t.me/c/1234567890/55")
    assert r == [(-1001234567890, 55)]
    assert isinstance(r[0][0], int)


def test_带话题_公开():
    assert parse("https://t.me/somechannel/7/123") == [("somechannel", 123)]


def test_带话题_私有():
    assert parse("https://t.me/c/1234567890/7/123") == [(-1001234567890, 123)]


def test_telegram_me域名():
    assert parse("https://telegram.me/somechannel/9") == [("somechannel", 9)]


def test_无协议前缀():
    assert parse("t.me/somechannel/9") == [("somechannel", 9)]


def test_带查询参数():
    assert parse("https://t.me/somechannel/9?single") == [("somechannel", 9)]
    assert parse("https://t.me/somechannel/9?comment=3") == [("somechannel", 9)]


def test_一条文字两个链接():
    t = "看这个 https://t.me/aaaaa/1 和 t.me/c/42/2，谢谢"
    assert parse(t) == [("aaaaa", 1), (-10042, 2)]


def test_同一链接重复只算一次():
    t = "https://t.me/aaaaa/1 https://t.me/aaaaa/1?single t.me/aaaaa/1"
    assert parse(t) == [("aaaaa", 1)]


def test_不是链接返回空():
    assert parse("今天天气不错") == []
    assert parse("") == []


def test_没有消息ID返回空():
    assert parse("t.me/username") == []
    assert parse("https://t.me/username") == []
    assert parse("https://t.me/joinchat/AbCdEf") == []


# ── 入队（假 client / 假 create_job）──────────────────────────────────────

def _msg(mid, gid=None, media=True):
    return SimpleNamespace(id=mid, grouped_id=gid, media=object() if media else None)


class FakeClient:
    def __init__(self, msgs, entity_err=None):
        self.msgs = {m.id: m for m in msgs}
        self.entity_err = entity_err

    async def get_entity(self, chat):
        if self.entity_err:
            raise self.entity_err
        return SimpleNamespace(title="频道甲")

    async def get_messages(self, entity, ids):
        if isinstance(ids, list):
            return [self.msgs.get(i) for i in ids]
        return self.msgs.get(ids)


@pytest.fixture
def jobs(monkeypatch):
    calls = []

    async def fake_create_job(scene, chat, **kw):
        calls.append((scene, chat, kw))
        return {"chat_name": "频道甲"}

    import downloader.history.runner as runner
    import downloader.history.utils as hutils
    monkeypatch.setattr(runner, "create_job", fake_create_job)
    monkeypatch.setattr(hutils, "is_downloadable_media", lambda m: bool(m.media))
    return calls


def run(coro):
    return asyncio.run(coro)


def test_单条消息入队_开区间外扩一格(monkeypatch, jobs):
    monkeypatch.setattr(handlers, "client", FakeClient([_msg(100)]))
    out = run(handlers._queue_link_download("somechannel", 100))
    assert out == "✅ 已加入下载：频道甲 #100"
    assert jobs == [("B", "somechannel", {"filter_type": "id", "min_id": 99, "max_id": 101})]


def test_相册整组下载(monkeypatch, jobs):
    msgs = [_msg(i, gid=5) for i in (98, 99, 100)] + [_msg(97, gid=4), _msg(101, gid=6)]
    monkeypatch.setattr(handlers, "client", FakeClient(msgs))
    out = run(handlers._queue_link_download(-1001234567890, 99))
    assert out == "✅ 已加入下载：频道甲 #99（相册 3 个）"
    assert jobs[0][1] == "-1001234567890"
    assert jobs[0][2]["min_id"] == 97 and jobs[0][2]["max_id"] == 101


def test_消息不存在(monkeypatch, jobs):
    monkeypatch.setattr(handlers, "client", FakeClient([]))
    out = run(handlers._queue_link_download("somechannel", 1))
    assert out.startswith("❌ somechannel #1：") and "不存在" in out
    assert jobs == []


def test_消息没有媒体(monkeypatch, jobs):
    monkeypatch.setattr(handlers, "client", FakeClient([_msg(1, media=False)]))
    out = run(handlers._queue_link_download("somechannel", 1))
    assert out.startswith("❌") and "没有可下载的媒体" in out
    assert jobs == []


def test_频道解析失败(monkeypatch, jobs):
    monkeypatch.setattr(handlers, "client", FakeClient([], entity_err=ValueError("x")))
    out = run(handlers._queue_link_download("nobody", 1))
    assert out.startswith("❌") and "频道解析失败" in out
    assert jobs == []


class FakeEvent:
    def __init__(self, text, chat_id, private=True):
        self.raw_text, self.chat_id, self.is_private = text, chat_id, private
        self.replies = []

    async def reply(self, t):
        self.replies.append(t)


def test_只认收藏_别的聊天不处理(monkeypatch, jobs):
    monkeypatch.setattr(handlers, "_current_self_id", lambda: 111)
    monkeypatch.setattr(handlers, "client", FakeClient([_msg(1)]))
    ev = FakeEvent("t.me/somechannel/1", chat_id=222)
    run(handlers.cmd_link_download(ev))
    assert ev.replies == [] and jobs == []


def test_收藏里多个链接各回一行_且不受暂停开关影响(monkeypatch, jobs):
    monkeypatch.setattr(handlers, "_current_self_id", lambda: 111)
    monkeypatch.setattr(handlers, "client", FakeClient([_msg(1), _msg(2)]))
    saved = (state.monitoring_paused, state.exempt_paused, state.saved_paused)
    state.monitoring_paused = state.exempt_paused = state.saved_paused = True
    try:
        ev = FakeEvent("t.me/aaaaa/1 t.me/aaaaa/2 t.me/aaaaa/1", chat_id=111)
        run(handlers.cmd_link_download(ev))
    finally:
        state.monitoring_paused, state.exempt_paused, state.saved_paused = saved
    assert len(ev.replies) == 2 and all(r.startswith("✅") for r in ev.replies)


# ── 状态命令 ────────────────────────────────────────────────────────────

def test_状态命令_搬运解压不可达也回复(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path / "not-created-yet")
    monkeypatch.setattr(state, "active_downloads", {
        "a": {"status": "downloading", "speed": 2 * 1048576},
        "b": {"status": "waiting"},
    })
    monkeypatch.setattr(state, "pending_tasks", {"a": {}, "b": {}, "c": {}, "d": {}})
    monkeypatch.setattr(state, "completed_downloads", [
        {"status": "done"}, {"status": "error"}, {"status": "timeout"}])
    monkeypatch.setattr(state, "monitoring_paused", True)
    monkeypatch.setattr(state, "exempt_paused", False)
    monkeypatch.setattr(state, "saved_paused", True)

    ev = FakeEvent("状态", chat_id=1)
    run(handlers.cmd_status(ev))
    assert len(ev.replies) == 1
    t = ev.replies[0]
    assert "在控制台查看" in t or "不可达" in t
    assert "进行中 1" in t and "排队 2" in t and "失败 2" in t and "2.0 MB/s" in t
    assert "普通频道 暂停" in t and "例外频道 开" in t and "收藏 暂停" in t
    assert "可用" in t


def test_状态命令_目录量不出来也不报错(monkeypatch):
    monkeypatch.setattr(handlers.shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError("x")))
    assert "磁盘：未知" in handlers._build_status_text()


# ── 回复不能再触发链接下载（防无限循环）──────────────────────────────────

def test_失败回复里不含可解析的链接():
    for chat in ("somechannel", -1001234567890):
        assert parse(f"❌ {handlers._link_display(chat, 55)}：消息不存在") == []
