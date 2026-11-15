# SPDX-License-Identifier: AGPL-3.0-or-later
"""跨环境适配第二批（2026-11-11）：退出信号 / 7-Zip 查找 / 打开文件夹。

背景见 docs/cross-platform-audit.md。
"""
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


# ── 退出信号：真进程、真 SIGTERM ────────────────────────────────────────

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


@pytest.mark.skipif(os.name == "nt", reason="Windows 没有 SIGTERM 语义")
@pytest.mark.parametrize("module,port_key", [
    ("mover.main", "MOVER_PORT"),
    ("unzipper.main", "UNZIPPER_PORT"),
    ("dashboard.main", "DASHBOARD_PORT"),
])
def test_收到SIGTERM几秒内退出(tmp_path, module, port_key):
    """核心用例：以前这三个模块没装处理器，在容器里当 1 号进程时 SIGTERM 被直接忽略，
    docker stop 只能干等 10 秒后硬杀，收尾代码一行都不跑。"""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.endswith("_PORT")}
    env.update({
        "API_ID": "1", "API_HASH": "x", "PHONE": "+10000000000",
        "DATA_ROOT": str(tmp_path / "data"), "LISTEN_HOST": "127.0.0.1",
        port_key: str(port), "TGH_IN_DOCKER": "0", "SERVICE_NAME": module.split(".")[0],
        "PYTHONPATH": str(PROJECT),
    })
    proc = subprocess.Popen([sys.executable, "-m", module], cwd=tmp_path, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        assert _wait_port(port), f"{module} 没起来：\n{proc.stdout.read().decode(errors='replace')[-2000:]}"
        t0 = time.time()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=8)
        took = time.time() - t0
        out = proc.stdout.read().decode(errors="replace")
        assert took < 5, f"{module} 收到 SIGTERM 后 {took:.1f} 秒才退出"
        assert "开始退出" in out, f"{module} 没走到我们的退出处理：\n{out[-1500:]}"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_compose里开了init():
    src = (PROJECT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "init: true" in src


# ── 7-Zip 查找 ──────────────────────────────────────────────────────────

def _reload_extractor(monkeypatch, which_map, env=None):
    import importlib
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: which_map.get(name))
    for k in ("SEVENZIP_BIN",):
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    import unzipper.extractor as ex
    return importlib.reload(ex)


def test_7z_优先用环境变量指定的(monkeypatch, tmp_path):
    fake = tmp_path / "my7z"
    fake.write_text("")
    ex = _reload_extractor(monkeypatch, {"7z": "/usr/bin/7z"}, {"SEVENZIP_BIN": str(fake)})
    assert ex.SEVEN_ZIP == str(fake)


def test_7z_mac的brew叫7zz(monkeypatch):
    """核心用例：以前只找 7z，brew 装的 sevenzip 叫 7zz，多卷包直接失败。"""
    ex = _reload_extractor(monkeypatch, {"7zz": "/opt/homebrew/bin/7zz"})
    assert ex.SEVEN_ZIP == "/opt/homebrew/bin/7zz"
    assert ex.HAS_7Z


def test_7z_环境变量指错了退回自动查找(monkeypatch):
    ex = _reload_extractor(monkeypatch, {"7z": "/usr/bin/7z"}, {"SEVENZIP_BIN": "/nope/7z"})
    assert ex.SEVEN_ZIP == "/usr/bin/7z"


def test_7z_都没有(monkeypatch):
    ex = _reload_extractor(monkeypatch, {})
    if os.name != "nt":
        assert ex.SEVEN_ZIP is None and not ex.HAS_7Z


def test_7z_命令里用的是找到的路径():
    src = (PROJECT / "unzipper" / "extractor.py").read_text(encoding="utf-8")
    assert 'cmd = ["7z"' not in src, "又写死成 7z 了"


@pytest.fixture(autouse=True)
def _restore_extractor():
    """上面的用例 reload 过 extractor，结束后按真实环境再 reload 一次，别影响别的测试。"""
    yield
    import importlib
    import unzipper.extractor as ex
    importlib.reload(ex)


# ── 打开文件夹 ──────────────────────────────────────────────────────────

def test_打开文件夹_docker里直接说明原因(monkeypatch, tmp_path):
    import config
    from common import open_folder
    monkeypatch.setattr(config, "IS_DOCKER", True)
    ok, why = open_folder.open_in_file_manager(tmp_path)
    assert not ok and "Docker" in why


@pytest.mark.skipif(os.name == "nt", reason="Windows 走 os.startfile")
def test_打开文件夹_没有桌面环境给原因不抛异常(monkeypatch, tmp_path):
    import config
    from common import open_folder
    monkeypatch.setattr(config, "IS_DOCKER", False)
    monkeypatch.setattr(open_folder.shutil, "which", lambda name: None)
    ok, why = open_folder.open_in_file_manager(tmp_path)
    assert not ok and "找不到" in why


@pytest.mark.skipif(os.name == "nt", reason="Windows 走 os.startfile")
def test_打开文件夹_mac用open_linux用xdg_open(monkeypatch, tmp_path):
    import config
    from common import open_folder
    calls = []
    monkeypatch.setattr(config, "IS_DOCKER", False)
    monkeypatch.setattr(open_folder.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(open_folder.subprocess, "Popen", lambda args, **kw: calls.append(args))
    ok, _ = open_folder.open_in_file_manager(tmp_path)
    assert ok
    expected = "open" if sys.platform == "darwin" else "xdg-open"
    assert calls == [[f"/usr/bin/{expected}", str(tmp_path)]]


def test_业务代码里不再写死xdg_open():
    hits = []
    for f in PROJECT.rglob("*.py"):
        rel = f.relative_to(PROJECT)
        if rel.parts[0] in (".venv", "tests") or rel.as_posix() == "common/open_folder.py":
            continue
        if "xdg-open" in f.read_text(encoding="utf-8", errors="ignore"):
            hits.append(rel.as_posix())
    assert not hits, f"这些文件又写死了 xdg-open：{hits}"
