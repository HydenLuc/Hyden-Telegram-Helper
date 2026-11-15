# SPDX-License-Identifier: AGPL-3.0-or-later
"""unzipper/watcher.py：多卷包稳定性判断必须看整个卷集合，不能只看 .001 自身。

旧实现只比较 .001 文件自身的大小；.001 写完但 .002/.003 还在陆续到达时就会被
误判"稳定"，从而过早开放确认 → find_missing_volume 只查中间缺号，查不出"后面
还有卷没到" → 用户一确认就因为缺卷失败，后到的卷成孤儿。
"""
import asyncio

import pytest

import config
import unzipper.state as _ustate
import unzipper.watcher as watcher


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCH_PATH", tmp_path)
    _ustate.paused = False
    watcher._handled.clear()
    watcher._last_size.clear()
    yield
    watcher._handled.clear()
    watcher._last_size.clear()


async def test_multipart_not_queued_until_part_set_stable(tmp_path):
    (tmp_path / "archive.7z.001").write_bytes(b"a" * 100)
    (tmp_path / "archive.7z.002").write_bytes(b"b" * 100)
    q = asyncio.Queue()

    await watcher._scan_once(q)
    assert q.empty(), "第一轮扫描不该立刻判定稳定"

    await watcher._scan_once(q)
    assert not q.empty(), "两轮扫描卷数+大小都不变才该判定稳定并入队"


async def test_new_tail_volume_resets_stability(tmp_path):
    (tmp_path / "archive.7z.001").write_bytes(b"a" * 100)
    (tmp_path / "archive.7z.002").write_bytes(b"b" * 100)
    q = asyncio.Queue()

    await watcher._scan_once(q)
    assert q.empty()

    # 本该稳定的第二轮，.003 却姗姗来迟——旧实现只看 .001 自身大小，会在这一轮
    # 就误判"稳定"入队；新实现按整个卷集合的签名判断，必须重新等待。
    (tmp_path / "archive.7z.003").write_bytes(b"c" * 100)
    await watcher._scan_once(q)
    assert q.empty(), ".003 到达应重置稳定计时，不能在这一轮就入队"

    await watcher._scan_once(q)
    assert not q.empty(), "3 卷集合稳定一轮之后才该入队"
    kind, path = q.get_nowait()
    assert kind == "multipart"
    assert path.name == "archive.7z.001"
