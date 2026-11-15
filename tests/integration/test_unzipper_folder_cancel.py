# SPDX-License-Identifier: AGPL-3.0-or-later
"""unzipper/manager.py：取消文件夹任务不能把 Step 1 移进 task_root 的原始
非压缩包文件、以及已经解压成功的产物，跟着 rmtree(task_root) 一起删掉。

不走真实 7z/py7zr；用 fake extract() 模拟"第一个压缩包解压成功、第二个压缩包
解压途中用户点了取消"。
"""
from pathlib import Path

import pytest

import config
import unzipper.manager as manager
import unzipper.state as _state
import unzipper.storage as storage


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_STORAGE_FILE", tmp_path / "unzipper_history.json")
    _state.current_tasks = {}
    _state.history = []
    _state.pending_multipart = {}


async def test_cancel_restores_originals_and_archives_completed_work(tmp_path, monkeypatch):
    source = tmp_path / "incoming" / "batch"
    source.mkdir(parents=True)
    (source / "notes.txt").write_text("原始笔记，从未被任何解压流程处理过", encoding="utf-8")
    (source / "a.zip").write_bytes(b"fake-a")
    (source / "b.zip").write_bytes(b"fake-b")

    output_base = tmp_path / "output"
    output_base.mkdir()
    monkeypatch.setattr(config, "OUTPUT_PATH", output_base)

    call_count = {"n": 0}

    async def fake_extract(archive_path, output_base=None, passwords=None,
                            on_attempt=None, on_pct=None, register_proc=None,
                            explicit_out_dir=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # a.zip："解压成功"：真的落地一份产物，模拟已完成的工作
            explicit_out_dir.mkdir(parents=True, exist_ok=True)
            (explicit_out_dir / "content.txt").write_text("extracted ok", encoding="utf-8")
            return explicit_out_dir, None
        # b.zip：模拟用户此时点了取消（cancel_task 会 terminate 子进程，
        # extract() 因此抛异常返回；cancel_flag 由取消请求并发设置）
        task_id = next(iter(_state.current_tasks))
        _state.current_tasks[task_id]["cancel_flag"] = True
        raise RuntimeError("simulated cancel mid-extract")

    monkeypatch.setattr(manager, "extract", fake_extract)

    await manager._process_folder(source)

    # ── 核心断言 1：从未被处理的原始文件必须已经移回 source ──────────
    restored = source / "notes.txt"
    assert restored.exists(), "取消后原始非压缩包文件必须移回 source，不能被 rmtree 删掉"
    assert restored.read_text(encoding="utf-8") == "原始笔记，从未被任何解压流程处理过"

    # ── 核心断言 2：已经解压成功的产物不能被直接删掉，应归档到 @已取消 ──
    cancelled_base = output_base / "@已取消"
    assert cancelled_base.exists(), "已完成的解压产物应归档到 @已取消，而不是被 rmtree"
    archived_dirs = list(cancelled_base.iterdir())
    assert len(archived_dirs) == 1
    contents = list(archived_dirs[0].rglob("content.txt"))
    assert len(contents) == 1
    assert contents[0].read_text(encoding="utf-8") == "extracted ok"

    # ── 核心断言 3：history 记一条 cancelled ─────────────────────────
    assert _state.history[-1]["status"] == "cancelled"
    assert _state.history[-1]["name"] == "batch"

    # ── task 已从 current_tasks 清出 ──────────────────────────────────
    assert _state.current_tasks == {}
