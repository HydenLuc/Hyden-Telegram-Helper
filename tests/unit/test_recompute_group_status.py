# SPDX-License-Identifier: AGPL-3.0-or-later
"""downloader/download/manager.py::_recompute_group_status"""
from downloader.download.manager import _recompute_group_status


def make_group(statuses):
    return {"files": {f"f{i}": {"status": s} for i, s in enumerate(statuses)}}


def test_empty():
    s, t = _recompute_group_status(make_group([]))
    assert s == "downloading"
    assert t is None


def test_all_done():
    s, t = _recompute_group_status(make_group(["done", "done", "done"]))
    assert s == "done"
    assert t is not None  # ISO timestamp set


def test_all_error():
    s, t = _recompute_group_status(make_group(["error", "error"]))
    assert s == "error"
    assert t is None


def test_mixed_done_and_error():
    s, t = _recompute_group_status(make_group(["done", "error"]))
    assert s == "partial"
    assert t is None


def test_done_and_active():
    s, t = _recompute_group_status(make_group(["done", "downloading"]))
    assert s == "partial"


def test_only_active():
    s, t = _recompute_group_status(make_group(["downloading", "waiting"]))
    assert s == "downloading"


def test_error_with_active():
    s, t = _recompute_group_status(make_group(["error", "downloading"]))
    # No done, has active → downloading
    assert s == "downloading"
