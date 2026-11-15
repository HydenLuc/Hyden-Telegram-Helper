# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from common.path_utils import validate_path


def test_absolute_path_creates_dir(tmp_path: Path):
    target = tmp_path / "new_dir"
    p, err = validate_path(str(target))
    assert err is None
    assert p == target.expanduser()
    assert target.is_dir()


def test_relative_path_rejected():
    p, err = validate_path("./relative")
    assert p is None
    assert "absolute" in err


def test_empty_string_rejected():
    p, err = validate_path("")
    assert p is None
    assert "non-empty" in err


def test_non_string_rejected():
    p, err = validate_path(None)
    assert p is None
    assert err is not None


def test_uncreatable_path_rejected():
    # /proc 子目录通常不可创建
    p, err = validate_path("/proc/cant-create-here-xyz")
    assert p is None
    assert "cannot create" in err


def test_existing_dir_ok(tmp_path: Path):
    p, err = validate_path(str(tmp_path))
    assert err is None
    assert p == tmp_path


# ── Docker 下只能改到 /data 下面（2026-11-11）────────────────────────────

def test_docker_拒绝data以外的路径(monkeypatch, tmp_path):
    """核心用例：以前设置页能把目录改到容器可写层，重建容器就丢、宿主机还看不到。"""
    import config
    monkeypatch.setattr(config, "IS_DOCKER", True)
    for bad in ("/app/downloads", "/state/dl", "/tmp/x", "/data/../etc"):
        p, err = validate_path(bad)
        assert p is None and "/data" in err, f"{bad} 没被拦住"


def test_docker_data下面的照常放行(monkeypatch, tmp_path):
    import config
    from common import path_utils
    monkeypatch.setattr(config, "IS_DOCKER", True)
    monkeypatch.setattr(path_utils, "DOCKER_DATA_MOUNT", tmp_path)   # 测试机上没有 /data
    p, err = validate_path(str(tmp_path / "telegramDMZ" / "download"))
    assert err is None and p.is_dir()


def test_原生不受data限制(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "IS_DOCKER", False)
    p, err = validate_path(str(tmp_path / "anywhere"))
    assert err is None
