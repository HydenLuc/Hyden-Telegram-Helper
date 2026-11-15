# SPDX-License-Identifier: AGPL-3.0-or-later
"""common/atomic_io.py."""
import json
from pathlib import Path

import pytest

from common.atomic_io import atomic_write_json, atomic_write_text


def test_write_json_roundtrip(tmp_path: Path):
    p = tmp_path / "data.json"
    payload = {"a": 1, "b": [1, 2, "汉字"]}
    atomic_write_json(p, payload)
    assert json.loads(p.read_text(encoding="utf-8")) == payload


def test_write_text_roundtrip(tmp_path: Path):
    p = tmp_path / "note.txt"
    atomic_write_text(p, "hello\n世界")
    assert p.read_text(encoding="utf-8") == "hello\n世界"


def test_overwrite(tmp_path: Path):
    p = tmp_path / "x.json"
    atomic_write_json(p, {"v": 1})
    atomic_write_json(p, {"v": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"v": 2}


def test_no_partial_file_on_error(tmp_path: Path, monkeypatch):
    """模拟 os.replace 抛异常时，原文件不被破坏。"""
    p = tmp_path / "existing.json"
    atomic_write_json(p, {"old": True})
    original = p.read_text(encoding="utf-8")

    import common.atomic_io as mod

    def fake_replace(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(mod.os, "replace", fake_replace)
    with pytest.raises(OSError):
        atomic_write_json(p, {"new": True})
    # 原文件保留
    assert p.read_text(encoding="utf-8") == original


def test_no_extension_path(tmp_path: Path):
    """路径无后缀时也能写。"""
    p = tmp_path / "noext"
    atomic_write_text(p, "hi")
    assert p.read_text(encoding="utf-8") == "hi"
