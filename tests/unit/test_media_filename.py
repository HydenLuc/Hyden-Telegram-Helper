# SPDX-License-Identifier: AGPL-3.0-or-later
"""downloader/utils.py：media_filename 对发送方可控 file_name 的路径穿越防护。"""
from downloader.utils import _sanitize_filename


def test_plain_filename_passthrough():
    assert _sanitize_filename("video.mp4", "fallback.bin") == "video.mp4"


def test_relative_traversal_neutralized():
    """../../x 里的 / 会被 sanitize() 换成空格，不再能拼出上级目录引用。"""
    cleaned = _sanitize_filename("../../x", "fallback.bin")
    assert "/" not in cleaned
    assert "\\" not in cleaned


def test_absolute_path_neutralized():
    cleaned = _sanitize_filename("/etc/passwd", "fallback.bin")
    assert "/" not in cleaned


def test_windows_absolute_path_neutralized():
    cleaned = _sanitize_filename("C:\\Windows\\evil.exe", "fallback.bin")
    assert "\\" not in cleaned
    assert ":" not in cleaned


def test_bare_dotdot_falls_back():
    """裸 ".." 没有分隔符也能被 Path 解释成上级目录，必须单独拦。"""
    assert _sanitize_filename("..", "fallback.bin") == "fallback.bin"


def test_bare_dot_falls_back():
    assert _sanitize_filename(".", "fallback.bin") == "fallback.bin"


def test_empty_after_cleaning_falls_back():
    assert _sanitize_filename("   ", "fallback.bin") == "fallback.bin"


def test_dotdot_with_trailing_dots_falls_back():
    """".. " 或 "..." 去掉首尾空格/点后也不能剩下裸 .."""
    assert _sanitize_filename(" .. ", "fallback.bin") == "fallback.bin"
