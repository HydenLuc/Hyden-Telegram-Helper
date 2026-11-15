# SPDX-License-Identifier: AGPL-3.0-or-later
"""mover/manager.py：_execute_move 的同盘 rename 快路径 + 跨盘删源前完整性校验。

不启动后台 worker/semaphore，直接调 _execute_move，专注验证这两条数据安全修复：
1. 同文件系统时走 os.rename，不经过整份 copy+staging。
2. 跨文件系统时，目标大小与源不一致就不删源（防 USB/网络盘静默截断后误删原件）。
"""
import shutil
from pathlib import Path

import pytest

import mover.manager as manager
import mover.state as state
import mover.storage as storage
from mover.utils import STAGING_PREFIX


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MOVER_STATE_FILE", tmp_path / "mover_state.json")
    state.tasks = {}
    state.paused = False


def _make_task(task_id: str, source: Path, target_dir: Path) -> dict:
    task = {
        "task_id": task_id, "source": str(source),
        "target": str(target_dir / source.name),
        "status": "pending", "created_at": "2026-01-01T00:00:00",
        "completed_at": None, "error": None,
        "files_attempted": 0, "files_completed": 0,
        "failed_at": None, "error_source": None,
        "is_cross_fs": False, "total_size": None,
    }
    state.tasks[task_id] = task
    return task


async def test_same_fs_uses_rename_fast_path(tmp_path: Path):
    source = tmp_path / "src" / "file.bin"
    source.parent.mkdir()
    source.write_bytes(b"hello world")
    target_dir = tmp_path / "dst"
    target_dir.mkdir()

    _make_task("t1", source, target_dir)
    await manager._execute_move("t1")

    final = target_dir / "file.bin"
    assert final.read_bytes() == b"hello world"
    assert not source.exists()
    assert state.tasks["t1"]["is_cross_fs"] is False
    # 快路径不经过 staging，target_dir 下不该留任何 .mover_staging_* 残留
    assert not any(p.name.startswith(STAGING_PREFIX) for p in target_dir.iterdir())


async def test_cross_fs_verify_catches_truncated_copy(tmp_path: Path, monkeypatch):
    """模拟 USB/网络盘把 copy 写截断：删源前必须先发现大小不一致，保留源、删掉坏副本。"""
    source = tmp_path / "src" / "file.bin"
    source.parent.mkdir()
    source.write_bytes(b"x" * 1000)
    target_dir = tmp_path / "dst"
    target_dir.mkdir()

    _make_task("t2", source, target_dir)
    monkeypatch.setattr(manager, "is_cross_filesystem", lambda a, b: True)

    def truncated_copy2(src, dst, *a, **kw):
        data = Path(src).read_bytes()
        Path(dst).write_bytes(data[: len(data) // 2])   # 只写一半，模拟静默截断

    monkeypatch.setattr(manager.shutil, "copy2", truncated_copy2)

    with pytest.raises(IOError):
        await manager._execute_move("t2")

    # 源必须还在、内容完整——这是本次修复要保证的核心不变量
    assert source.exists()
    assert source.read_bytes() == b"x" * 1000
    # 损坏的目标副本必须被清掉，不留下半截文件冒充"已搬运"
    assert not (target_dir / "file.bin").exists()


async def test_cross_fs_size_match_deletes_source(tmp_path: Path, monkeypatch):
    """校验通过（大小一致）时行为不变：正常删源完成搬运。"""
    source = tmp_path / "src" / "file.bin"
    source.parent.mkdir()
    source.write_bytes(b"y" * 500)
    target_dir = tmp_path / "dst"
    target_dir.mkdir()

    _make_task("t3", source, target_dir)
    monkeypatch.setattr(manager, "is_cross_filesystem", lambda a, b: True)

    await manager._execute_move("t3")

    final = target_dir / "file.bin"
    assert final.read_bytes() == b"y" * 500
    assert not source.exists()
