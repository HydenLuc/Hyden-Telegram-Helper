# SPDX-License-Identifier: AGPL-3.0-or-later
"""Windows 文件名规则（2026-11-11）。

- 控制字符：所有平台都换掉（Linux 能建，但搬到 Windows / SMB 上打不开）
- 末尾点 / 空格、保留设备名（CON NUL COM1 …）：**只在 Windows 上**改。
  Linux / macOS 上这些名字合法，改了会让老部署同一个频道换文件夹名。
"""
import pytest

from downloader import utils
from downloader.utils import _sanitize_filename, sanitize


def test_控制字符全平台都换掉():
    assert sanitize("频道\x0b名\x01字\x7f", "fb") == "频道 名 字"


@pytest.mark.parametrize("raw,want", [
    ("频道名...", "频道名"),
    ("末尾空格 . ", "末尾空格"),
    ("CON", "_CON"),
    ("con", "_con"),
    ("nul.mp4", "_nul.mp4"),
    ("COM1.txt", "_COM1.txt"),
    ("LPT9", "_LPT9"),
    ("CONSOLE", "CONSOLE"),      # 只是前缀像，不是保留名
    ("COM10", "COM10"),          # 只有 COM1-9
])
def test_Windows上修末尾点和保留名(monkeypatch, raw, want):
    monkeypatch.setattr(utils, "IS_WINDOWS", True)
    assert sanitize(raw, "fb") == want


def test_Windows上全是点就回退默认名(monkeypatch):
    monkeypatch.setattr(utils, "IS_WINDOWS", True)
    assert sanitize("...", "fb") == "fb"


def test_Windows上文件名也修(monkeypatch):
    monkeypatch.setattr(utils, "IS_WINDOWS", True)
    assert _sanitize_filename("aux.zip", "fb.bin") == "_aux.zip"
    assert _sanitize_filename("视频.mp4.", "fb.bin") == "视频.mp4"


def test_Linux和mac上不改_老部署文件夹名不能变(monkeypatch):
    """核心用例：已有部署里「频道名...」的文件夹已经存在，换名会把新旧下载分成两处。"""
    monkeypatch.setattr(utils, "IS_WINDOWS", False)
    assert sanitize("频道名...", "fb") == "频道名..."
    assert sanitize("CON", "fb") == "CON"
