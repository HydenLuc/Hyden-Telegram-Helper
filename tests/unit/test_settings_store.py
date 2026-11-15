# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from common.settings_store import SettingsStore


def make(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "s.json", ["foo", "bar"])


def test_load_default_when_missing(tmp_path: Path):
    s = make(tmp_path).load()
    assert s == {
        "path_history": {"foo": [], "bar": []},
        "use_last_path": True,
    }


def test_load_corrupt_returns_default(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text("{ not json")
    s = make(tmp_path).load()
    assert s["path_history"] == {"foo": [], "bar": []}


def test_save_load_roundtrip(tmp_path: Path):
    store = make(tmp_path)
    data = store.load()
    data["use_last_path"] = False
    store.add_to_history(data, "foo", "/a")
    store.save(data)

    reloaded = store.load()
    assert reloaded["use_last_path"] is False
    assert reloaded["path_history"]["foo"] == ["/a"]


def test_history_dedup_and_max_10(tmp_path: Path):
    store = make(tmp_path)
    data = store.load()
    for i in range(15):
        store.add_to_history(data, "foo", f"/p{i}")
    # Most recent first, max 10
    assert data["path_history"]["foo"][:3] == ["/p14", "/p13", "/p12"]
    assert len(data["path_history"]["foo"]) == 10


def test_history_dedup_moves_to_front(tmp_path: Path):
    store = make(tmp_path)
    data = store.load()
    store.add_to_history(data, "foo", "/a")
    store.add_to_history(data, "foo", "/b")
    store.add_to_history(data, "foo", "/a")  # dedup
    assert data["path_history"]["foo"] == ["/a", "/b"]


def test_empty_path_ignored(tmp_path: Path):
    store = make(tmp_path)
    data = store.load()
    store.add_to_history(data, "foo", "")
    assert data["path_history"]["foo"] == []


def test_unknown_field_partial_dict(tmp_path: Path):
    """旧文件可能没有所有 history_keys；load 应补齐。"""
    p = tmp_path / "s.json"
    p.write_text('{"path_history": {"foo": ["/x"]}, "use_last_path": false}')
    s = make(tmp_path).load()
    assert s["path_history"]["foo"] == ["/x"]
    assert s["path_history"]["bar"] == []
    assert s["use_last_path"] is False
