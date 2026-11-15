# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import pytest

from common.env_writer import save_env_value, save_env_values


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_create_new_file(tmp_path: Path):
    p = tmp_path / ".env"
    save_env_value(p, "FOO", "bar")
    assert "FOO=bar" in _read(p)


def test_replace_existing_key(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("FOO=old\nKEEP=yes\n")
    save_env_value(p, "FOO", "new")
    text = _read(p)
    assert "FOO=new" in text
    assert "KEEP=yes" in text
    assert "FOO=old" not in text


def test_append_when_missing(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("KEEP=yes\n")
    save_env_value(p, "NEW", "val")
    text = _read(p)
    assert "KEEP=yes" in text
    assert "NEW=val" in text


def test_batch(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("A=1\nB=2\nC=3\n")
    save_env_values(p, {"A": "11", "D": "4"})
    text = _read(p)
    assert "A=11" in text
    assert "B=2" in text
    assert "C=3" in text
    assert "D=4" in text


def test_empty_kvs_is_noop(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("X=1\n")
    save_env_values(p, {})
    assert _read(p) == "X=1\n"


def test_preserves_existing_lines_order(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("A=1\nB=2\nC=3\n")
    save_env_value(p, "B", "22")
    lines = _read(p).strip().split("\n")
    assert lines == ["A=1", "B=22", "C=3"]


def test_rejects_embedded_newline_in_value(tmp_path: Path):
    """value 里塞 \\n 曾能在 .env 里注入任意新变量（如 API_KEY=attacker）。"""
    p = tmp_path / ".env"
    p.write_text("DOWNLOAD_DIR=/data\n")
    with pytest.raises(ValueError):
        save_env_value(p, "DOWNLOAD_DIR", "/data\nAPI_KEY=attacker\nBOT_TOKEN=evil")
    # 拒绝后原文件不受影响
    assert _read(p) == "DOWNLOAD_DIR=/data\n"


def test_rejects_embedded_cr_in_value(tmp_path: Path):
    p = tmp_path / ".env"
    with pytest.raises(ValueError):
        save_env_value(p, "FOO", "bar\rBAZ=qux")


def test_rejects_equals_in_key(tmp_path: Path):
    p = tmp_path / ".env"
    with pytest.raises(ValueError):
        save_env_values(p, {"FOO=BAR": "x"})


def test_batch_rejects_if_any_value_bad(tmp_path: Path):
    """批量写入时任一 kv 含非法字符，整批都不落盘（不留半截注入）。"""
    p = tmp_path / ".env"
    p.write_text("KEEP=yes\n")
    with pytest.raises(ValueError):
        save_env_values(p, {"OK": "fine", "BAD": "x\ny=z"})
    assert _read(p) == "KEEP=yes\n"
