# SPDX-License-Identifier: AGPL-3.0-or-later
"""日志文件名：没设 SERVICE_NAME 时按启动入口推断（2026-11-13）。

手动 `python -m mover.main` 之类启动时，以前四个进程共写 app.log，午夜 rotate 会互相删日志。
"""
import sys
import types

from common import logger


def _fake_main(monkeypatch, *, spec_name=None, file=None):
    m = types.ModuleType("__main__")
    m.__spec__ = types.SimpleNamespace(name=spec_name) if spec_name else None
    if file:
        m.__file__ = file
    monkeypatch.setitem(sys.modules, "__main__", m)
    monkeypatch.delenv("SERVICE_NAME", raising=False)


def test_环境变量优先(monkeypatch):
    _fake_main(monkeypatch, spec_name="mover.main")
    monkeypatch.setenv("SERVICE_NAME", "custom")
    assert logger._service_name() == "custom"


def test_python_m_模块入口(monkeypatch):
    _fake_main(monkeypatch, spec_name="unzipper.main")
    assert logger._service_name() == "unzipper"


def test_python_bot_py_算下载器(monkeypatch):
    _fake_main(monkeypatch, file="/somewhere/bot.py")
    assert logger._service_name() == "downloader"


def test_认不出来退回_app_log(monkeypatch):
    _fake_main(monkeypatch, spec_name="pytest.__main__")
    assert logger._service_name() == ""
