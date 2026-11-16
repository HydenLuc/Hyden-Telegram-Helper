# SPDX-License-Identifier: AGPL-3.0-or-later
"""防封号：DOWNLOAD_START_INTERVAL / DOWNLOAD_START_JITTER 全局开始间隔节流。

用假时钟 + 假 sleep，测试本身不真睡。
"""
import asyncio

import pytest

import config
from downloader.download import manager


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    async def sleep(self, s):
        self.slept.append(s)
        self.now += s


@pytest.fixture
def ft(monkeypatch):
    monkeypatch.setattr(manager, "_next_start_at", 0.0)
    monkeypatch.setattr(config, "DOWNLOAD_START_INTERVAL", 0.0)
    monkeypatch.setattr(config, "DOWNLOAD_START_JITTER", 0.0)
    return FakeTime()


def go(ft, n=1):
    async def _run():
        for _ in range(n):
            await manager._throttle_start(clock=ft.clock, sleep=ft.sleep)
    asyncio.run(_run())


def test_interval为0不等待(ft):
    go(ft, 3)
    assert ft.slept == []


def test_连续两次开始间隔不小于interval(ft, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_START_INTERVAL", 5.0)
    starts = []

    async def _run():
        for _ in range(3):
            await manager._throttle_start(clock=ft.clock, sleep=ft.sleep)
            starts.append(ft.now)
    asyncio.run(_run())
    assert starts[1] - starts[0] >= 5.0 and starts[2] - starts[1] >= 5.0
    assert ft.slept == [5.0, 5.0]       # 第一次不用等


def test_负数当0(ft, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_START_INTERVAL", -3.0)
    monkeypatch.setattr(config, "DOWNLOAD_START_JITTER", -2.0)
    go(ft, 3)
    assert ft.slept == []


def test_jitter在间隔上叠加随机量(ft, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_START_INTERVAL", 2.0)
    monkeypatch.setattr(config, "DOWNLOAD_START_JITTER", 3.0)
    monkeypatch.setattr(manager.random, "uniform", lambda a, b: b)   # 取上限
    go(ft, 2)
    assert ft.slept == [5.0]


def test_并发等待者排队_各预占一个槽(ft, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_START_INTERVAL", 4.0)
    waits = []

    async def rec_sleep(s):          # 只记录要等多久，不推进时间（三个同时到达）
        waits.append(s)

    async def _run():
        await asyncio.gather(*(manager._throttle_start(clock=ft.clock, sleep=rec_sleep)
                               for _ in range(3)))
    asyncio.run(_run())
    assert sorted(waits) == [4.0, 8.0]      # 第一个直接开，后两个依次错开 4 秒


@pytest.mark.parametrize("raw,expect", [("", 0.0), ("abc", 0.0), ("-1", 0.0), ("2.5", 2.5)])
def test_config解析(monkeypatch, raw, expect):
    monkeypatch.setenv("DOWNLOAD_START_INTERVAL", raw)
    assert config._nonneg_float("DOWNLOAD_START_INTERVAL") == expect
