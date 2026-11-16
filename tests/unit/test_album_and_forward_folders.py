# SPDX-License-Identifier: AGPL-3.0-or-later
"""两处文件夹归属（2026-11-15，hyden 实测后定）。不连真实 Telegram。

① 历史下载 / 粘贴链接下载：同一相册（grouped_id 相同）要放进同一个文件夹。
   以前 `_start_api_download` 每条消息各建一个目录，相册被拆开。
② 转发进收藏的媒体：文件夹按原频道 / 原发送人命名，不再全堆在自己名字下面。
"""
import asyncio
from types import SimpleNamespace

import pytest
from telethon.tl.types import Channel, ChatPhotoEmpty, User

import config
from downloader import state
from downloader.download import manager
from downloader.tg import handlers
from downloader.web import api

CHAT = -1001234567890


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path)

    async def fake_get_entity(_cid):
        await asyncio.sleep(0)   # 真实调用会让出事件循环，并发用例靠它制造交错
        return SimpleNamespace(id=1)

    monkeypatch.setattr(api.client, "get_entity", fake_get_entity)
    monkeypatch.setattr(api, "entity_display_name", lambda _e: "某频道")
    monkeypatch.setattr(api, "media_filename", lambda m: f"file_{m.id}.jpg")
    monkeypatch.setattr(api, "_format_details_header", lambda m: "HEADER")
    monkeypatch.setattr(api, "_format_media_entry", lambda m, i, name: f"ENTRY {i} {name}")

    async def fake_download_one(*a, **k):
        return None

    monkeypatch.setattr(manager, "download_one", fake_download_one)
    old_groups = dict(state._group_dirs)
    state._group_dirs.clear()
    yield tmp_path
    state._group_dirs.clear()
    state._group_dirs.update(old_groups)


def msg(mid, grouped_id=None, text=""):
    return SimpleNamespace(id=mid, grouped_id=grouped_id, message=text, views=0, forwards=0)


def start(m, seq):
    return api._start_api_download(m, CHAT, m.id, task_id_tag="hist_test", task_id_seq=seq,
                                   source="history")


# ── ① 相册不拆 ──────────────────────────────────────────────────────────

def test_同一相册放进同一个文件夹(env):
    async def go():
        r1 = await start(msg(322, grouped_id=77, text="影片说明"), 0)
        r2 = await start(msg(323, grouped_id=77), 1)
        return r1, r2

    r1, r2 = asyncio.run(go())
    assert r1["save_dir"] == r2["save_dir"]
    detail = (env / "某频道").glob("*/消息详情.txt")
    lines = next(detail).read_text(encoding="utf-8").splitlines()
    assert lines == ["HEADER", "ENTRY 1 file_322.jpg", "ENTRY 2 file_323.jpg"]


def test_并发进来的同组消息也不拆(env):
    """历史下载是 create_task 并发 spawn 的，get_entity 那个 await 会让两条交错。"""
    async def go():
        return await asyncio.gather(start(msg(10, grouped_id=5), 0),
                                    start(msg(11, grouped_id=5), 1),
                                    start(msg(12, grouped_id=5), 2))

    rs = asyncio.run(go())
    assert len({r["save_dir"] for r in rs}) == 1
    assert len(list((env / "某频道").iterdir())) == 1


def test_说明文字在后一条时也补写(env):
    async def go():
        r1 = await start(msg(20, grouped_id=9), 0)
        await start(msg(21, grouped_id=9, text="后到的说明"), 1)
        return r1

    r1 = asyncio.run(go())
    from pathlib import Path
    assert (Path(r1["save_dir"]) / "文字信息.txt").read_text(encoding="utf-8") == "后到的说明"


def test_不同相册和单条消息照旧各自一个文件夹(env):
    async def go():
        return [await start(msg(1, grouped_id=100), 0),
                await start(msg(2, grouped_id=200), 1),
                await start(msg(3), 2),
                await start(msg(4), 3)]

    rs = asyncio.run(go())
    assert len({r["save_dir"] for r in rs}) == 4


def test_直接下载照旧孤立目录(env):
    """toast「直接下载」不复用相册目录（docs/md5-dedup-design.md Q2）。"""
    async def go():
        return [await api._start_api_download(msg(30, grouped_id=3), CHAT, 30, skip_md5_index=True),
                await api._start_api_download(msg(31, grouped_id=3), CHAT, 31, skip_md5_index=True)]

    rs = asyncio.run(go())
    assert rs[0]["save_dir"] != rs[1]["save_dir"]


# ── ② 转发按原来源命名 ──────────────────────────────────────────────────

def _fwd(chat=None, sender=None, from_name=None):
    return SimpleNamespace(forward=SimpleNamespace(chat=chat, sender=sender, from_name=from_name))


def test_转发自频道用频道名():
    ch = Channel(id=1, title="原频道", photo=ChatPhotoEmpty(), date=None)
    assert handlers._forward_source_name(_fwd(chat=ch)) == "原频道"


def test_转发自个人用对方名字():
    u = User(id=2, first_name="张", last_name="三")
    assert handlers._forward_source_name(_fwd(sender=u)) == "张 三"


def test_隐藏账号用署名():
    assert handlers._forward_source_name(_fwd(from_name="匿名的人")) == "匿名的人"


def test_不是转发返回None():
    assert handlers._forward_source_name(SimpleNamespace(forward=None)) is None
    assert handlers._forward_source_name(_fwd()) is None


def test_取来源不发网络请求():
    """handle_media 里这一步和相册目录登记之间不能 yield，所以必须是同步函数。"""
    assert not asyncio.iscoroutinefunction(handlers._forward_source_name)
