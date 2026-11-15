# SPDX-License-Identifier: AGPL-3.0-or-later
""".env 的读写位置（2026-11-11 修）。

## 这组用例防的是什么

设置页 / downloader / unzipper 保存配置时写的是 `config.ENV_FILE`。
以前读配置用无参数的 `load_dotenv()`，它从 config.py 所在目录往上找：
原生部署碰巧和 ENV_FILE 是同一个文件；**Docker 里读不到任何东西，
保存写进的 /state/.env 也没人读 → 设置页改了等于白改**。

现在 Docker 里 /state/.env 是「设置页覆盖层」，要能盖过宿主机注入的值；
但容器里固定的几项（数据目录、端口、服务寻址）不许被盖。

## 为什么用子进程

config 在 import 时就读 .env、计算各种默认值。在当前进程里 reload 会污染
别的测试用到的 config。每个用例起一个干净的 Python 进程去 import，互不影响。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]

PROBE = """
import json, os, config
print(json.dumps({
    "is_docker": config.IS_DOCKER,
    "env_file": str(config.ENV_FILE),
    "MAX_TOTAL_CONNECTIONS": os.getenv("MAX_TOTAL_CONNECTIONS"),
    "DATA_ROOT": os.getenv("DATA_ROOT"),
    "WEB_PORT": os.getenv("WEB_PORT"),
}))
"""


def run_config(cwd: Path, env_extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAX_TOTAL_CONNECTIONS", "DATA_ROOT", "WEB_PORT", "TGH_IN_DOCKER")}
    env.update({"API_ID": "1", "API_HASH": "x", "PHONE": "+10000000000",
                "PYTHONPATH": str(PROJECT)})
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── Docker ──────────────────────────────────────────────────────────────

def test_docker_设置页覆盖层要生效(tmp_path):
    """核心用例：以前这里读不到，设置页保存了也白保存。"""
    (tmp_path / ".env").write_text("MAX_TOTAL_CONNECTIONS=7\n", encoding="utf-8")
    got = run_config(tmp_path, {"TGH_IN_DOCKER": "1", "MAX_TOTAL_CONNECTIONS": "16"})
    assert got["is_docker"] is True
    assert got["env_file"] == str(tmp_path / ".env")
    assert got["MAX_TOTAL_CONNECTIONS"] == "7", "覆盖层没有盖过宿主机注入的值"


def test_docker_固定项不许被覆盖层改(tmp_path):
    """覆盖层里残留的数据目录 / 端口不能把容器搞坏。"""
    # config 一 import 就会建 <DATA_ROOT>/telegramDMZ/...，所以「正确的」数据目录要用能写的临时目录
    good_root = tmp_path / "data"
    (tmp_path / ".env").write_text(
        "DATA_ROOT=/Users/someone/old-mac-path\nWEB_PORT=9999\n", encoding="utf-8")
    got = run_config(tmp_path, {"TGH_IN_DOCKER": "1", "DATA_ROOT": str(good_root), "WEB_PORT": "8091"})
    assert got["DATA_ROOT"] == str(good_root)
    assert got["WEB_PORT"] == "8091"


def test_docker_没有覆盖层也能启动(tmp_path):
    got = run_config(tmp_path, {"TGH_IN_DOCKER": "1", "MAX_TOTAL_CONNECTIONS": "16"})
    assert got["MAX_TOTAL_CONNECTIONS"] == "16"


# ── 原生部署 ────────────────────────────────────────────────────────────

def test_原生_读写都是项目根的env_不管从哪个目录启动(tmp_path):
    """以前 ENV_FILE 跟着 cwd 走：从别的目录启动，保存就写到另一个文件里去了。"""
    got = run_config(tmp_path, {"TGH_IN_DOCKER": "0"})
    assert got["is_docker"] is False
    assert got["env_file"] == str(PROJECT / ".env")


def test_原生_不读工作目录里的env(tmp_path):
    """工作目录里另有一个 .env 时，不能被它带偏（读写必须是同一个文件）。"""
    (tmp_path / ".env").write_text("MAX_TOTAL_CONNECTIONS=3\n", encoding="utf-8")
    got = run_config(tmp_path, {"TGH_IN_DOCKER": "0", "MAX_TOTAL_CONNECTIONS": "16"})
    assert got["MAX_TOTAL_CONNECTIONS"] == "16"


# ── 容器检测 ────────────────────────────────────────────────────────────

def test_容器检测可以强制指定(tmp_path):
    assert run_config(tmp_path, {"TGH_IN_DOCKER": "1"})["is_docker"] is True
    assert run_config(tmp_path, {"TGH_IN_DOCKER": "0"})["is_docker"] is False


def test_检测代码认Podman():
    src = (PROJECT / "config.py").read_text(encoding="utf-8")
    assert "/run/.containerenv" in src, "Podman 不生成 /.dockerenv，只靠它会把 Podman 当成原生部署"


# ── 状态目录 STATE_DIR（2026-11-11）──────────────────────────────────────

STATE_PROBE = "import config; print(config.STATE_DIR); print(config.WATCHED_FILE); print(config.LOG_DIR)"


def run_state(cwd: Path, env_extra: dict) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("STATE_DIR", "TGH_IN_DOCKER")}
    env.update({"API_ID": "1", "API_HASH": "x", "PHONE": "+10000000000",
                "PYTHONPATH": str(PROJECT), "DATA_ROOT": str(cwd / "data")})
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", STATE_PROBE], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-3:]


def test_原生_指定绝对路径(tmp_path):
    target = tmp_path / "my-state"
    state, watched, logs = run_state(tmp_path, {"TGH_IN_DOCKER": "0", "STATE_DIR": str(target)})
    assert state == str(target.resolve())
    assert watched == str(target.resolve() / "watched_chats.json")
    assert logs == str(target.resolve() / "logs")
    assert target.is_dir(), "状态目录应该自动建好"


def test_原生_相对路径按项目根算_不按启动目录(tmp_path):
    """以前全跟着启动目录走：从别的目录启动，状态就散到那个目录去了。"""
    state, _, _ = run_state(tmp_path, {"TGH_IN_DOCKER": "0", "STATE_DIR": "custom-state-for-test"})
    try:
        assert state == str((PROJECT / "custom-state-for-test").resolve())
    finally:
        import shutil
        shutil.rmtree(PROJECT / "custom-state-for-test", ignore_errors=True)


def test_Docker_不认STATE_DIR_固定在容器工作目录(tmp_path):
    """宿主机 .env 里误写一个 STATE_DIR，状态就会写到 volume 外面、重建容器全丢。"""
    state, watched, _ = run_state(tmp_path, {"TGH_IN_DOCKER": "1", "STATE_DIR": "/somewhere/else"})
    assert state == str(tmp_path.resolve())
    assert watched == str(tmp_path.resolve() / "watched_chats.json")


def test_session文件跟着状态目录():
    src = (PROJECT / "downloader" / "tg" / "client.py").read_text(encoding="utf-8")
    assert 'config.STATE_DIR / "userbot"' in src, "session 又变回相对路径了：会跟着启动目录走"


def test_备份工具的状态目录规则和config一致(tmp_path, monkeypatch):
    sys.path.insert(0, str(PROJECT / "tools"))
    try:
        import statedir
        monkeypatch.delenv("STATE_DIR", raising=False)
        monkeypatch.setattr(statedir, "_from_env_file", lambda _p: "")
        assert statedir.resolve_state_dir() == PROJECT / "state"
        assert statedir.resolve_state_dir(str(tmp_path)) == tmp_path.resolve()
        monkeypatch.setenv("STATE_DIR", "rel-dir")
        assert statedir.resolve_state_dir() == (PROJECT / "rel-dir").resolve()
    finally:
        sys.path.remove(str(PROJECT / "tools"))


# ── 没设 API_KEY 的安全默认（2026-11-11）────────────────────────────────────

def run_raw(cwd: Path, env_extra: dict):
    env = {k: v for k, v in os.environ.items()
           if k not in ("API_KEY", "LISTEN_HOST", "ALLOW_NO_API_KEY", "TGH_IN_DOCKER")}
    env.update({"API_ID": "1", "API_HASH": "x", "PHONE": "+10000000000",
                "PYTHONPATH": str(PROJECT), "DATA_ROOT": str(cwd / "data")})
    env.update(env_extra)
    return subprocess.run([sys.executable, "-c", "import config; print('STARTED')"], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=60)


def test_原生_监听局域网又没密码_拒绝启动(tmp_path):
    """核心用例：以前只打一行警告就照常启动，接口对整个局域网敞开。"""
    r = run_raw(tmp_path, {"TGH_IN_DOCKER": "0", "LISTEN_HOST": "0.0.0.0", "API_KEY": ""})
    assert r.returncode != 0 and "STARTED" not in r.stdout
    assert "API_KEY" in r.stderr


def test_原生_显式放行可以启动(tmp_path):
    r = run_raw(tmp_path, {"TGH_IN_DOCKER": "0", "LISTEN_HOST": "0.0.0.0", "ALLOW_NO_API_KEY": "1"})
    assert r.returncode == 0 and "STARTED" in r.stdout


def test_原生_设了密码或只听本机都正常(tmp_path):
    assert run_raw(tmp_path, {"TGH_IN_DOCKER": "0", "LISTEN_HOST": "0.0.0.0", "API_KEY": "k"}).returncode == 0
    assert run_raw(tmp_path, {"TGH_IN_DOCKER": "0", "LISTEN_HOST": "127.0.0.1"}).returncode == 0


def test_Docker_不拦_默认部署必须能起(tmp_path):
    """Docker、0.0.0.0、没设 API_KEY，端口只映射到 127.0.0.1（和 VPN 地址）。不能被这条规则拦掉。"""
    r = run_raw(tmp_path, {"TGH_IN_DOCKER": "1", "LISTEN_HOST": "0.0.0.0", "API_KEY": ""})
    assert r.returncode == 0 and "STARTED" in r.stdout
    assert "ports" in r.stderr
