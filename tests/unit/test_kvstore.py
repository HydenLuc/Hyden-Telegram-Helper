# SPDX-License-Identifier: AGPL-3.0-or-later
"""kvstore.KVStore：增量持久化的行为契约。

重点覆盖三件最容易出错的事：
  ① 只写脏键，别的行不能被动到
  ② 活字典里没了的键 = 删除（调用点不需要区分增删改）
  ③ 写失败不能静默丢——必须退化成「下次全量重写」
"""
import json
import sqlite3

import pytest

from downloader.kvstore import KVStore


@pytest.fixture
def kv(tmp_path):
    store = KVStore(tmp_path / "t.db", "things")
    yield store
    store.close()


def _flush(store, live):
    store._live = live          # mark() 平时会带上，这里直接设便于构造场景
    batch = store.snapshot()
    if batch is not None:
        store.apply(batch)


def test_import_and_load_roundtrip(kv):
    data = {"a": {"n": 1}, "b": {"n": 2, "s": "中文"}}
    assert kv.import_dict(data) == 2
    assert kv.load() == data
    assert kv.count() == 2


def test_only_dirty_key_is_written(kv, tmp_path):
    kv.import_dict({"a": {"n": 1}, "b": {"n": 2}})
    live = kv.load()

    # 绕过 KVStore 直接改库，制造一个「库里和内存不一致」的 b。
    # 如果 flush 错误地整表重写，b 会被内存里的值覆盖掉；只写脏键则 b 保持不变。
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("UPDATE things SET v=? WHERE k='b'", (json.dumps({"n": 999}),))
    conn.commit()
    conn.close()

    live["a"]["n"] = 10
    kv.mark(live, "a")
    _flush(kv, live)

    got = kv.load()
    assert got["a"] == {"n": 10}, "脏键没写进去"
    assert got["b"] == {"n": 999}, "非脏键被整表重写覆盖了"


def test_missing_key_means_delete(kv):
    kv.import_dict({"a": {"n": 1}, "b": {"n": 2}})
    live = kv.load()
    del live["b"]
    kv.mark(live, "b")          # 调用点只需说「b 变了」，不必说是删是改
    _flush(kv, live)
    assert set(kv.load()) == {"a"}


def test_mark_without_key_rewrites_all(kv):
    kv.import_dict({"a": {"n": 1}, "b": {"n": 2}})
    live = {"c": {"n": 3}}          # 整个换掉
    kv.mark(live, None)
    _flush(kv, live)
    assert kv.load() == {"c": {"n": 3}}


def test_mark_all_wins_over_pending_keys(kv):
    kv.import_dict({"a": {"n": 1}})
    live = {"z": {"n": 9}}                # 整个换掉
    kv.mark(live, "a")
    kv.mark(live, None)                   # 升级成全量，不能被降级回单键
    _flush(kv, live)
    assert kv.load() == {"z": {"n": 9}}


def test_write_failure_falls_back_to_full_rewrite(kv, monkeypatch):
    """写失败时脏键已经从 _dirty 摘掉了，必须自愈成「下次全量重写」，否则静默丢数据。"""
    kv.import_dict({"a": {"n": 1}})
    live = {"a": {"n": 1}, "b": {"n": 2}}
    kv.mark(live, "b")
    batch = kv.snapshot()

    real_connect = kv._connect

    class BrokenConn:
        """只让 executemany 炸，其余透传（sqlite3.Connection 的方法不能直接赋值）。"""
        def __init__(self, inner):
            self._inner = inner

        def executemany(self, *a, **k):
            raise sqlite3.Error("模拟磁盘满")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(kv, "_connect", lambda: BrokenConn(real_connect()))
    kv.apply(batch)
    monkeypatch.setattr(kv, "_connect", real_connect)

    assert kv.has_dirty(), "写失败后没有标记重试 —— 这一批就丢了"
    _flush(kv, live)
    assert kv.load() == live


def test_corrupt_row_does_not_kill_the_whole_table(kv, tmp_path):
    kv.import_dict({"a": {"n": 1}, "b": {"n": 2}})
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("UPDATE things SET v='{坏掉的 json' WHERE k='b'")
    conn.commit()
    conn.close()
    got = kv.load()
    assert got == {"a": {"n": 1}}, "一行坏掉不该让整张表读不出来"


def test_empty_flush_is_a_noop(kv):
    kv.import_dict({"a": {"n": 1}})
    kv._live = {"a": {"n": 1}}
    assert kv.snapshot() is None
