# SPDX-License-Identifier: AGPL-3.0-or-later
"""首次登录要验证码时去哪儿输（2026-11-12）。

以前一律在终端等输入：start.sh 后台启动 / Docker / launchd 下没有终端 → EOFError，
**新用户第一次启动必崩**。现在：有终端在终端输，没终端在网页输。
网页登录流程本身的测试在 test_web_login.py。
"""
import asyncio
import io
import os
import sys

import pytest

from downloader.tg import client as tgc


class _TTY(io.StringIO):
    def isatty(self):
        return True


def test_有终端_在终端输(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _TTY())
    assert tgc.login_mode() == "terminal"


def test_后台启动没终端_走网页(monkeypatch):
    """核心用例：nohup / Docker 下 stdin 不是终端。"""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert tgc.login_mode() == "web"


def test_stdin被关掉或没有_也走网页(monkeypatch):
    closed = io.StringIO(); closed.close()
    monkeypatch.setattr(sys, "stdin", closed)
    assert tgc.login_mode() == "web"
    monkeypatch.setattr(sys, "stdin", None)
    assert tgc.login_mode() == "web"


async def test_走网页时用自己的网页登录流程(monkeypatch):
    got = {}

    async def fake_web_login(client, phone):
        got["phone"] = phone

    async def boom(**kw):
        raise AssertionError("网页模式不该再走 client.start")

    import downloader.tg.web_login as wl
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(tgc.client, "start", boom)
    monkeypatch.setattr(wl, "web_login", fake_web_login)
    await tgc.start_client()
    assert "phone" in got


@pytest.mark.skipif(os.name == "nt", reason="Windows 上 chmod 不管读权限")
def test_登录文件自动收紧到600(monkeypatch, tmp_path):
    f = tmp_path / "userbot.session"
    f.write_bytes(b"x"); f.chmod(0o644)
    monkeypatch.setattr(tgc, "SESSION_FILE", f)
    tgc.lock_down_session()
    assert f.stat().st_mode & 0o777 == 0o600


def test_两个入口都用同一个登录函数():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for entry in ("bot.py", "downloader/main.py"):
        src = (root / entry).read_text(encoding="utf-8")
        assert "await start_client()" in src, f"{entry} 又直接调 client.start 了"
        assert "client.start(phone" not in src
