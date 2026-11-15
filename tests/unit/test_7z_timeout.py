# SPDX-License-Identifier: AGPL-3.0-or-later
"""unzipper/extractor.py：7z 超时按体积估算，而不是硬编码 600s。"""
from pathlib import Path

from unzipper.extractor import _compute_7z_timeout, _7Z_MIN_TIMEOUT_S


def test_small_file_uses_floor(tmp_path: Path):
    f = tmp_path / "small.7z"
    f.write_bytes(b"x" * 1024)
    assert _compute_7z_timeout(f) == _7Z_MIN_TIMEOUT_S


def test_large_file_scales_above_floor(tmp_path: Path):
    f = tmp_path / "big.7z"
    # 50 GB 大小（稀疏文件，不真的写满磁盘）
    with f.open("wb") as fh:
        fh.truncate(50 * 1024 * 1024 * 1024)
    timeout = _compute_7z_timeout(f)
    assert timeout > _7Z_MIN_TIMEOUT_S
    # 50GB / 5MB/s ≈ 10240s
    assert timeout > 9000


def test_multipart_sums_all_volumes(tmp_path: Path):
    stem = "archive.7z"
    for i in range(1, 4):
        (tmp_path / f"{stem}.{i:03d}").write_bytes(b"x" * (2 * 1024 * 1024 * 1024))
    first = tmp_path / f"{stem}.001"
    timeout = _compute_7z_timeout(first)
    # 6GB 总量 / 5MB/s ≈ 1229s，明显高于只看单卷（2GB → 410s，仍会被 floor 拉到 600）
    assert timeout > 1000


def test_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UNZIPPER_7Z_TIMEOUT", "42")
    f = tmp_path / "big.7z"
    with f.open("wb") as fh:
        fh.truncate(100 * 1024 * 1024 * 1024)
    assert _compute_7z_timeout(f) == 42.0


def test_missing_file_falls_back_to_floor(tmp_path: Path):
    ghost = tmp_path / "gone.7z"
    assert _compute_7z_timeout(ghost) == _7Z_MIN_TIMEOUT_S
