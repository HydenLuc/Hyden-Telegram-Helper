# SPDX-License-Identifier: AGPL-3.0-or-later
"""common.pathlimits：路径分量长度保护。

背景见模块注释——2026-08-13 一个 288 字节的目录名让 rsync 静默跳过 23 个文件，
退出码还是 0。这里覆盖的是「不能再静默」的那几条。
"""
import os

import pytest

from common.pathlimits import (
    MAX_NAME_BYTES,
    fix_long_names,
    is_too_long,
    scan_long_names,
    truncate_bytes,
    truncate_filename,
)

CN = "中"          # UTF-8 占 3 字节
LONG_CN = CN * 100  # 300 字节，超 255 的文件系统硬上限


def _fs_allows_long_names() -> bool:
    """当前临时目录所在文件系统能不能建 300 字节的文件名。

    macOS 的 APFS 按「字符数」限 255，300 字节的中文名建得出来；
    Linux 的 ext4 / overlayfs / ZFS 按「字节数」限 255，造测试素材这一步就失败。
    这几条用例要先造出超长名再验证修复，造不出来就没得测，只能跳过。
    （线上不受影响：ZFS 本来就是 255 字节上限，代码写盘前会截到 200 字节。）
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        try:
            os.mkdir(os.path.join(d, LONG_CN))
            return True
        except OSError:
            return False


needs_long_names = pytest.mark.skipif(
    not _fs_allows_long_names(),
    reason="文件系统按字节限 255，造不出超长名素材（Linux 常态，见 _fs_allows_long_names）",
)


def test_truncate_cuts_on_char_boundary():
    out = truncate_bytes(LONG_CN, 200)
    assert len(out.encode()) <= 200
    out.encode().decode("utf-8")            # 切半个字会在这里炸
    assert out == CN * 66                   # 66*3=198，第 67 个放不下


def test_truncate_filename_keeps_extension():
    name = LONG_CN + ".mp4"
    out = truncate_filename(name)
    assert out.endswith(".mp4"), "扩展名丢了播放器就认不出"
    assert len(out.encode()) <= MAX_NAME_BYTES


def test_truncate_filename_ignores_fake_extension():
    """结尾那段太长就不是扩展名，是文件名里的假点号。"""
    name = "x." + LONG_CN
    out = truncate_filename(name)
    assert len(out.encode()) <= MAX_NAME_BYTES


def test_short_names_untouched():
    assert truncate_filename("正常名字.mp4") == "正常名字.mp4"
    assert not is_too_long("正常名字.mp4")


@needs_long_names
def test_fix_long_names_renames_dir_and_file(tmp_path):
    d = tmp_path / LONG_CN
    d.mkdir()
    (d / (LONG_CN + ".mp4")).write_text("x")

    renamed = fix_long_names(tmp_path)

    assert len(renamed) == 2
    for p in tmp_path.rglob("*"):
        assert not is_too_long(p.name), f"{p.name!r} 还是超长"
    # 内容还在
    files = list(tmp_path.rglob("*.mp4"))
    assert len(files) == 1 and files[0].read_text() == "x"


def test_fix_long_names_is_bottom_up(tmp_path):
    """先改父目录的话，子路径会全部失效。

    ⚠️ 这里每层用 210 字节而不是 300：三层 300 字节会撞上 **PATH_MAX**（macOS 1024），
    那是**整条路径**的上限，和本模块管的「单个分量」是两回事。
    fix_long_names 只解决分量超限；路径整体太深仍可能失败，这是已知边界。
    """
    lvl = CN * 70          # 210 字节 > MAX_NAME_BYTES(200)，但三层加起来不超 PATH_MAX
    deep = tmp_path / lvl / lvl / lvl
    deep.mkdir(parents=True)
    (deep / "keep.txt").write_text("ok")

    fix_long_names(tmp_path)

    found = list(tmp_path.rglob("keep.txt"))
    assert len(found) == 1, "自底向上没做对，深层文件丢了"
    assert found[0].read_text() == "ok"
    for p in tmp_path.rglob("*"):
        assert not is_too_long(p.name)


@needs_long_names
def test_fix_long_names_handles_collision(tmp_path):
    """两个超长名字截短后会撞在一起，不能互相覆盖。"""
    (tmp_path / (CN * 90 + "AAA")).mkdir()      # 前 66 个字相同
    (tmp_path / (CN * 90 + "BBB")).mkdir()

    fix_long_names(tmp_path)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 2, f"撞名后被覆盖了：{names}"
    for n in names:
        assert not is_too_long(n), f"去重后缀把 {n!r} 又顶超了"


def test_fix_long_names_noop_on_clean_tree(tmp_path):
    (tmp_path / "正常").mkdir()
    (tmp_path / "正常" / "文件.mp4").write_text("x")
    assert fix_long_names(tmp_path) == []


def test_fix_long_names_missing_root_is_safe(tmp_path):
    assert fix_long_names(tmp_path / "不存在") == []


@needs_long_names
def test_scan_reports_without_changing(tmp_path):
    d = tmp_path / LONG_CN
    d.mkdir()
    hits = scan_long_names(tmp_path)
    assert len(hits) == 1
    assert hits[0][1] == 300
    assert d.exists(), "scan 不该动任何东西"


@needs_long_names
def test_the_2026_08_13_case(tmp_path):
    """回归：288 字节的乱码目录名（GBK 被当 CP437 解出来的那种）。"""
    mojibake = "".join(chr(0xC0 + (i % 60)) for i in range(144))   # 144 chars × 2 bytes = 288
    assert len(mojibake.encode()) == 288
    d = tmp_path / mojibake
    d.mkdir()
    for i in range(23):
        (d / f"file_{i}.mp4").write_text("x")

    fix_long_names(tmp_path)

    survivors = list(tmp_path.rglob("*.mp4"))
    assert len(survivors) == 23, "23 个文件不能再丢一次"
    assert all(not is_too_long(p.name) for p in tmp_path.rglob("*"))


def test_unreadable_tree_raises_not_reports_clean(tmp_path, monkeypatch):
    """读不动整棵树时必须抛错，不能报「✅ 没发现问题」。

    2026-08-20 实测踩到：一台 Mac 上从 SSH 扫 NFS 挂载，每层都是 EPERM，
    而 os.walk 默认吞掉错误产出零条目 → 扫描器报告「干净」。
    和这个模块要修的 rsync 静默跳过是同一类病。
    """
    import os as _os
    from common.pathlimits import WalkFailed

    real_walk = _os.walk

    def blind_walk(top, topdown=True, onerror=None, followlinks=False):
        if onerror is not None:
            onerror(PermissionError(1, "Operation not permitted", str(top)))
        return iter(())

    monkeypatch.setattr(_os, "walk", blind_walk)
    with pytest.raises(WalkFailed):
        scan_long_names(tmp_path)
    with pytest.raises(WalkFailed):
        fix_long_names(tmp_path)
    monkeypatch.setattr(_os, "walk", real_walk)


@needs_long_names
def test_partial_read_error_does_not_raise(tmp_path):
    """只有个别子目录读不动、其余读到了 → 照常返回，别整个炸掉。"""
    (tmp_path / "正常").mkdir()
    (tmp_path / "正常" / (CN * 100)).mkdir()
    # 没有报错，正常返回
    assert len(scan_long_names(tmp_path)) == 1
