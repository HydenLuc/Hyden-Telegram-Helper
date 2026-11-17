# SPDX-License-Identifier: AGPL-3.0-or-later
"""控制台设置页后端（#1803）：开放的字段、校验、留空 = 删行、密钥只写不读、说明卡片齐全。"""
import re
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import config
from common.env_writer import save_env_values
from dashboard import settings_api as sa
from dashboard.help_texts import HELP
from dashboard.templates import DASHBOARD_HTML


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("API_ID=1\nMAX_TOTAL_CONNECTIONS=20\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", f)
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "IS_DOCKER", False)
    monkeypatch.setattr(config, "FLOOD_SLEEP_THRESHOLD", 60)
    for k in sa._EDITABLE_FIELDS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MAX_TOTAL_CONNECTIONS", "20")
    return f


@pytest.fixture
async def client(env_file, monkeypatch):
    async def _no_hot(_updates):
        return []
    monkeypatch.setattr(sa, "_apply_hot", _no_hot)
    app = web.Application()
    app.router.add_get("/api/config", sa.config_get_handler)
    app.router.add_post("/api/config", sa.config_post_handler)
    app.router.add_get("/api/help", sa.help_handler)
    app.router.add_post("/api/notify/test", sa.notify_test_handler)
    async with TestClient(TestServer(app)) as c:
        yield c


# ── .env 写入：值为 None = 删掉这一行 ─────────────────────────────────────────

def test_env_writer_值为None就删行(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\n# B=注释不动\nB=2\nC=3\n", encoding="utf-8")
    save_env_values(f, {"B": None, "C": "4", "D": None})
    assert f.read_text(encoding="utf-8") == "A=1\n# B=注释不动\nC=4\n"


# ── 校验 ─────────────────────────────────────────────────────────────────────

def test_下载超时下限跟着限流阈值走(env_file, monkeypatch):
    assert sa.validate_field("DOWNLOAD_TIMEOUT", "60")[1]            # 60 这个坑填不进去了
    assert sa.validate_field("DOWNLOAD_TIMEOUT", "119")[1]
    assert sa.validate_field("DOWNLOAD_TIMEOUT", "120") == ("120", None)
    monkeypatch.setattr(config, "FLOOD_SLEEP_THRESHOLD", 30)
    assert sa.validate_field("DOWNLOAD_TIMEOUT", "60") == ("60", None)


def test_总连接数上限统一成64(env_file):
    assert sa.validate_field("MAX_TOTAL_CONNECTIONS", "64") == ("64", None)
    assert sa.validate_field("MAX_TOTAL_CONNECTIONS", "65")[1]


@pytest.mark.parametrize("key,raw,expect", [
    ("HISTORY_CONN_FRACTION", "0.5", "0.5"),
    ("DOWNLOAD_START_INTERVAL", "2", "2"),
    ("DOWNLOAD_START_INTERVAL", "1.5", "1.5"),
    ("AUTOHEAL", "False", "false"),
    ("LOG_LEVEL", "debug", "DEBUG"),
    ("ADMIN_CHAT_ID", "-1001234567890", "-1001234567890"),
    ("MOVE_ALLOWED_ROOTS", "/mnt/a\n/mnt/b , /srv/x", "/mnt/a,/mnt/b,/srv/x"),
])
def test_合法值(env_file, key, raw, expect):
    assert sa.validate_field(key, raw) == (expect, None)


@pytest.mark.parametrize("key,raw", [
    ("HISTORY_CONN_FRACTION", "0.95"),
    ("HISTORY_CONN_FRACTION", "abc"),
    ("STALLED_RETRY_INTERVAL", "30"),
    ("AUTOHEAL", "yes"),
    ("ADMIN_CHAT_ID", "@someone"),
    ("BOT_TOKEN", "not-a-token"),
    ("MOVE_ALLOWED_ROOTS", "relative/path"),
    ("MOVE_ALLOWED_ROOTS", "/"),
    ("MOVE_ALLOWED_ROOTS", "/etc/x"),
    ("MOVE_ALLOWED_ROOTS", "/mnt/ok,/usr"),
])
def test_非法值(env_file, key, raw):
    val, err = sa.validate_field(key, raw)
    assert err and val is None


def test_留空就是删行(env_file):
    for k in sa._EDITABLE_FIELDS:
        assert sa.validate_field(k, "") == (None, None)
        assert sa.validate_field(k, None) == (None, None)


def test_Docker下路径只读(env_file, monkeypatch):
    monkeypatch.setattr(config, "IS_DOCKER", True)
    assert sa.validate_field("DATA_ROOT", "/x")[1]
    assert sa.validate_field("DATA_ROOT", "")[1]


def test_凭证和端口永远不开放():
    for k in ("API_ID", "API_HASH", "PHONE", "API_KEY", "WEB_PORT", "DASHBOARD_PORT",
              "LISTEN_HOST", "STATE_DIR", "ALLOW_NO_API_KEY", "FLOOD_SLEEP_THRESHOLD"):
        assert k not in sa._EDITABLE_FIELDS


# ── 接口 ─────────────────────────────────────────────────────────────────────

async def test_保存_留空删行_读回来(client, env_file):
    r = await client.post("/api/config", json={"RECOVER_WORKERS": "4", "LOG_KEEP_DAYS": "7"})
    assert r.status == 200, await r.text()
    d = await r.json()
    assert d["saved"] == ["LOG_KEEP_DAYS", "RECOVER_WORKERS"] and d["need_restart"]
    text = env_file.read_text(encoding="utf-8")
    assert "RECOVER_WORKERS=4" in text and "LOG_KEEP_DAYS=7" in text

    g = await (await client.get("/api/config")).json()
    assert g["values"]["RECOVER_WORKERS"] == "4"
    assert "RECOVER_WORKERS" in g["pending"]          # 已保存、还没重启
    assert "MAX_TOTAL_CONNECTIONS" not in g["pending"]

    r = await client.post("/api/config", json={"RECOVER_WORKERS": ""})
    assert r.status == 200
    assert "RECOVER_WORKERS" not in env_file.read_text(encoding="utf-8")
    g = await (await client.get("/api/config")).json()
    assert g["values"]["RECOVER_WORKERS"] == "" and "RECOVER_WORKERS" not in g["pending"]


async def test_跨字段校验(client, env_file):
    r = await client.post("/api/config", json={"RECOVER_WORKERS": "30"})   # 超过总连接数 20
    assert r.status == 400 and "RECOVER_WORKERS" in (await r.json())["error"]
    r = await client.post("/api/config", json={"SMALL_FILE_RESERVED_CONNECTIONS": "20"})
    assert r.status == 400
    # 同一次把总连接数调大就可以
    r = await client.post("/api/config", json={"RECOVER_WORKERS": "30", "MAX_TOTAL_CONNECTIONS": "40"})
    assert r.status == 200, await r.text()
    text = Path(env_file).read_text(encoding="utf-8")
    assert "RECOVER_WORKERS=30" in text and "MAX_TOTAL_CONNECTIONS=40" in text


async def test_不在白名单的字段被拒(client):
    r = await client.post("/api/config", json={"API_KEY": "x"})
    assert r.status == 400


async def test_机器人Token只写不读(client, env_file):
    tok = "123456789:" + "A" * 35
    r = await client.post("/api/config", json={"BOT_TOKEN": tok, "ADMIN_CHAT_ID": "12345"})
    assert r.status == 200, await r.text()
    assert f"BOT_TOKEN={tok}" in env_file.read_text(encoding="utf-8")
    g = await client.get("/api/config")
    body = await g.text()
    assert tok not in body
    d = await g.json()
    assert d["secrets_set"]["BOT_TOKEN"] is True and d["values"]["BOT_TOKEN"] == ""


async def test_测试通知(client, env_file, monkeypatch):
    sent = []

    async def fake_send(token, chat_id):
        sent.append((token, chat_id))
        return True, ""
    monkeypatch.setattr(sa, "_send_test", fake_send)
    r = await client.post("/api/notify/test", json={"ADMIN_CHAT_ID": "12345"})
    assert r.status == 400                        # 没 Token 测不了
    tok = "123456789:" + "B" * 35
    r = await client.post("/api/notify/test", json={"ADMIN_CHAT_ID": "12345", "BOT_TOKEN": tok})
    assert r.status == 200 and sent == [(tok, "12345")]
    # 框里没填 → 用已保存的
    env_file.write_text(env_file.read_text(encoding="utf-8") + f"ADMIN_CHAT_ID=999\nBOT_TOKEN={tok}\n", encoding="utf-8")
    r = await client.post("/api/notify/test", json={})
    assert r.status == 200 and sent[-1] == (tok, "999")


async def test_热改总连接数(env_file, monkeypatch):
    calls = []

    async def fake_post(port, key, payload, *, host, label):
        calls.append(payload)
        return True
    monkeypatch.setattr(sa, "peer_post_settings", fake_post)
    applied = await sa._apply_hot({"MAX_TOTAL_CONNECTIONS": "32", "LOG_LEVEL": "DEBUG"})
    assert applied == ["MAX_TOTAL_CONNECTIONS"] and calls == [{"max_total_connections": 32}]
    import os
    assert os.environ["MAX_TOTAL_CONNECTIONS"] == "32"


# ── 说明卡片 ─────────────────────────────────────────────────────────────────

def test_说明卡片每条都齐全():
    for k, h in HELP.items():
        assert h.get("what") and h.get("when"), k
        assert h.get("kind") in ("switch", "num", "info"), k
        if h["kind"] in ("switch", "num"):
            assert h.get("up") and h.get("down"), k


def test_每个可编辑字段都有说明():
    # notify 卡片管 ADMIN_CHAT_ID + BOT_TOKEN
    covered = set(HELP) | {"ADMIN_CHAT_ID", "BOT_TOKEN"}
    assert not [k for k in sa._EDITABLE_FIELDS if k not in covered]


def test_页面引用的说明键都存在():
    keys = set(re.findall(r'data-help="([^"]+)"', DASHBOARD_HTML))
    assert keys, "页面上一个「?」都没有"
    assert not [k for k in keys if k not in HELP]


def test_页面上每个可编辑字段都有输入框():
    for k in sa._EDITABLE_FIELDS:
        assert f'id="f-{k}"' in DASHBOARD_HTML, k


def test_英文说明和中文一一对应():
    """#1792 之前新加的项先写在 HELP_EN 里：键在 HELP 里有，字段一样（多一个 label）。"""
    from dashboard.help_texts import HELP_EN, LABEL_ZH
    for k, en in HELP_EN.items():
        zh = HELP[k]
        assert set(en) - {"label"} == set(zh), k
        assert all(v.strip() for v in en.values()), k
        assert not re.search(r"[\u4e00-\u9fff]", "".join(v for f, v in en.items() if f != "warn")), k
        assert f'>{LABEL_ZH[k]}<' in DASHBOARD_HTML, k
