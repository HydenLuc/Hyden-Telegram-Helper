# SPDX-License-Identifier: AGPL-3.0-or-later
"""重启 / 断电后回到上次的运行状态 + 开机自启（2026-11-13，hyden 要求）。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import config
from common import run_state

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def statedir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "RESTART_MODE", "RESUME")
    return tmp_path


# ── run_state ──────────────────────────────────────────────────────────────────

def test_从没记录过_用出厂默认(statedir):
    assert run_state.restore("downloader", "monitoring_paused", True) is True
    assert run_state.restore("mover", "paused", False) is False


def test_恢复成关机前的样子(statedir):
    run_state.save("downloader", monitoring_paused=False)
    run_state.save("downloader", exempt_paused=False)      # 分两次写，前一个不能丢
    assert run_state.restore("downloader", "monitoring_paused", True) is False
    assert run_state.restore("downloader", "exempt_paused", True) is False
    run_state.save("unzipper", paused=True)
    assert run_state.restore("unzipper", "paused", False) is True


def test_PAUSED模式_一律回到出厂默认(statedir, monkeypatch):
    run_state.save("downloader", monitoring_paused=False)
    run_state.save("mover", paused=True)
    monkeypatch.setattr(config, "RESTART_MODE", "PAUSED")
    assert run_state.restore("downloader", "monitoring_paused", True) is True
    assert run_state.restore("mover", "paused", False) is False


def test_文件坏了_按默认启动不崩(statedir):
    (statedir / "run_state_mover.json").write_text("{坏的", encoding="utf-8")
    assert run_state.restore("mover", "paused", False) is False
    (statedir / "run_state_mover.json").write_text("[1,2]", encoding="utf-8")
    assert run_state.restore("mover", "paused", False) is False


def test_各模块各写各的文件(statedir):
    run_state.save("downloader", monitoring_paused=False)
    run_state.save("mover", paused=True)
    assert sorted(p.name for p in statedir.iterdir()) == ["run_state_downloader.json", "run_state_mover.json"]


# ── 页面上的开关会落盘 ────────────────────────────────────────────────────────

async def test_下载器暂停按钮会记下来(statedir, monkeypatch):
    from downloader.web import api
    async def nop(): pass
    monkeypatch.setattr(api, "_broadcast", nop)
    await api._api_resume(None)
    await api._api_exempt_resume(None)
    assert run_state.load("downloader") == {"monitoring_paused": False, "exempt_paused": False}
    await api._api_pause(None)
    assert run_state.load("downloader")["monitoring_paused"] is True


async def test_解压器暂停按钮会记下来(statedir, monkeypatch):
    from unzipper.web import api
    async def nop(): pass
    monkeypatch.setattr(api, "_broadcast", nop)
    await api._api_pause(None)
    assert run_state.load("unzipper") == {"paused": True}


async def test_搬运器暂停会记下来(statedir, monkeypatch):
    from mover import manager
    async def nop(): pass
    monkeypatch.setattr(manager, "_try_broadcast", nop)
    await manager.pause()
    assert run_state.load("mover") == {"paused": True}


def test_启动入口用的是恢复值而不是写死暂停():
    bot = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert 'run_state.restore("downloader", "monitoring_paused", True)' in bot
    assert 'run_state.restore("downloader", "exempt_paused", True)' in bot
    assert "state.monitoring_paused = True\n" not in bot
    assert 'run_state.restore("mover", "paused", False)' in (ROOT / "mover/main.py").read_text(encoding="utf-8")
    assert 'run_state.restore("unzipper", "paused", False)' in (ROOT / "unzipper/main.py").read_text(encoding="utf-8")


def test_重启模式写错了按RESUME():
    out = subprocess.run([sys.executable, "-c", "import config;print(config.RESTART_MODE)"],
                         cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "RESTART_MODE": "whatever"}).stdout.strip()
    assert out == "RESUME"


# ── 开机自启 ──────────────────────────────────────────────────────────────────

def test_macOS自启配置(monkeypatch, tmp_path):
    from tools import autostart
    calls = []
    monkeypatch.setattr(autostart.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(autostart, "_is_docker", lambda: False)
    monkeypatch.setattr(autostart.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(autostart.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    assert autostart.status()["enabled"] is False
    r = autostart.enable()
    assert r["ok"] and r["enabled"]
    text = autostart._mac_plist().read_text(encoding="utf-8")
    assert "--boot" in text and "<key>AbandonProcessGroup</key><true/>" in text
    assert autostart.MAC_LABEL in text
    import plistlib
    plistlib.loads(text.encode())              # 必须是合法 plist
    r = autostart.disable()
    assert r["ok"] and not r["enabled"] and not autostart._mac_plist().exists()


def test_Linux自启配置(monkeypatch, tmp_path):
    from tools import autostart
    calls = []

    class R:
        returncode, stdout, stderr = 0, "Linger=no", ""
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.setattr(autostart, "_is_docker", lambda: False)
    monkeypatch.setattr(autostart.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(autostart.shutil, "which", lambda _: "/usr/bin/loginctl")
    monkeypatch.setattr(autostart.subprocess, "run", lambda cmd, **k: (calls.append(cmd), R())[1])
    r = autostart.enable()
    assert r["ok"] and r["enabled"] and "enable-linger" in r["note"]
    unit = autostart._linux_unit().read_text(encoding="utf-8")
    assert "start.sh --boot" in unit and "ExecStop" in unit
    assert ["systemctl", "--user", "enable", autostart.LINUX_UNIT] in calls


def test_Docker和Windows不在这里管(monkeypatch):
    from tools import autostart
    monkeypatch.setattr(autostart, "_is_docker", lambda: True)
    assert autostart.status()["how"] == "docker" and autostart.enable()["ok"] is False
    monkeypatch.setattr(autostart, "_is_docker", lambda: False)
    monkeypatch.setattr(autostart.platform, "system", lambda: "Windows")
    assert autostart.status()["supported"] is False


# ── 断电重启后 pid 被别的程序占用 ─────────────────────────────────────────────

@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="shell 脚本只在 Linux / macOS 用")
def test_stop脚本不会杀掉占了旧pid的别的程序(tmp_path):
    shutil.copy(ROOT / "stop.sh", tmp_path / "stop.sh")
    (tmp_path / ".run").mkdir()
    victim = subprocess.Popen(["sleep", "30"])        # 冒充「断电重启后拿到同一个 pid 的别的程序」
    try:
        (tmp_path / ".run" / "mover.pid").write_text(str(victim.pid))
        out = subprocess.run(["bash", str(tmp_path / "stop.sh")], cwd=tmp_path,
                             capture_output=True, text=True, timeout=30)
        assert victim.poll() is None, "stop.sh 把别人的进程杀了"
        assert "已不是本程序" in out.stdout + out.stderr
        assert not (tmp_path / ".run" / "mover.pid").exists()
    finally:
        victim.kill()


def test_shell脚本里变量后面不直接跟中文():
    """macOS 自带的 bash 3.2 在 UTF-8 环境下会把紧跟的中文字节当成变量名的一部分：
    `$pidfile）` → 变量 `pidfile\\xef` 未定义 → set -u 直接退出（2026-11-13 CI 的 macOS 上撞到）。
    一律写成 `${pidfile}）`。"""
    import re
    bad = []
    for f in ROOT.rglob("*.sh"):
        if any(p in f.parts for p in (".venv", "node_modules", ".git")):
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line):
                bad.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not bad, "变量后面直接跟了非 ASCII 字符，改成 ${变量}：\n" + "\n".join(bad)
