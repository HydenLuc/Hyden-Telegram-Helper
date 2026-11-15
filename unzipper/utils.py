# SPDX-License-Identifier: AGPL-3.0-or-later
import errno
import re
from pathlib import Path

from common.constants import ARCHIVE_EXTS

_IGNORE_NAMES   = frozenset({'.DS_Store', 'Thumbs.db', 'desktop.ini', '__MACOSX'})
_INPROG_EXTS    = frozenset({'.part', '.tmp', '.downloading', '.crdownload'})


def unique_dir_name(parent: Path, base_name: str) -> str:
    """Return base_name if free, else base_name_000, base_name_001, ..."""
    if not (parent / base_name).exists():
        return base_name
    i = 0
    while True:
        candidate = f"{base_name}_{i:03d}"
        if not (parent / candidate).exists():
            return candidate
        i += 1


def is_ignored(path: Path) -> bool:
    """True for hidden/system files to skip in residual detection."""
    name = path.name
    return name.startswith('.') or name in _IGNORE_NAMES


def is_multipart_part(path: Path) -> bool:
    """True for .7z.002, .7z.003 etc. (NOT .7z.001)."""
    name = path.name.lower()
    return bool(re.match(r'.*\.7z\.\d{3}$', name)) and not name.endswith('.7z.001')


def is_archive(path: Path) -> bool:
    """True for extractable archives (ignores .7z.002+ parts)."""
    if is_multipart_part(path):
        return False
    name = path.name.lower()
    if name.endswith('.7z.001'):
        return True
    return path.suffix.lower() in ARCHIVE_EXTS


def classify_error(exc: Exception) -> str:
    """Map exception to a short failure-reason string."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "磁盘空间不足"
    msg = str(exc).lower()
    # 先判具体的底层错误：缺卷/损坏会被包在"所有密码均失败: <真错>"里，必须优先识别，
    # 否则会把"缺卷导致的失败"误报成"密码错误"。
    if any(k in msg for k in ("cannot find volume", "unexpected end of archive",
                               "missing volume", "cannot open next volume",
                               "多卷不完整", "缺第")):
        return "卷缺失"
    if any(k in msg for k in ("crc error", "data error", "bad archive",
                               "corrupt", "invalid signature", "bad magic",
                               "headers error", "is not archive")):
        return "文件损坏"
    # 排除以上具体信号后，才认定是密码穷尽
    if "所有密码均失败" in str(exc):
        return "密码错误"
    return f"其他: {exc}"


def dir_total_size(path: Path) -> int:
    """Recursively sum file sizes in a directory."""
    total = 0
    try:
        for f in path.rglob('*'):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def has_inprogress_files(path: Path) -> bool:
    """True if any file has an in-progress suffix (.part, .tmp, ...)."""
    try:
        for f in path.rglob('*'):
            if f.is_file() and f.suffix.lower() in _INPROG_EXTS:
                return True
    except OSError:
        pass
    return False


def find_residuals(folder: Path) -> list[str]:
    """Return relative paths of non-ignored files / symlinks still left in folder.

    P2-symlink fix: 把符号链接也视为残留（不管 target 是否存在 / 是否为常规文件），
    避免解压后留下的 dangling symlink 不被检测到。
    """
    result = []
    try:
        for f in folder.rglob('*'):
            try:
                # 符号链接：无条件视为残留（is_file() 会跟随 symlink，dangling 时返回 False，会漏报）
                if f.is_symlink():
                    if not is_ignored(f):
                        result.append(str(f.relative_to(folder)))
                    continue
                if f.is_file() and not is_ignored(f):
                    result.append(str(f.relative_to(folder)))
            except OSError:
                # 单个 entry 异常（如权限）跳过，不影响其他遍历
                continue
    except OSError:
        pass
    return result


def scan_archives(folder: Path) -> tuple[list[Path], list[Path]]:
    """
    Recursively scan folder.
    Returns (archive_paths, non_archive_paths) — directories excluded.
    archive_paths: .zip / .rar / .7z / .7z.001 only (not .002+).
    """
    archives: list[Path] = []
    others:   list[Path] = []
    try:
        for item in sorted(folder.rglob('*')):
            if item.is_dir():
                continue
            if is_multipart_part(item):
                continue  # .002+ handled automatically by 7z when .001 is extracted
            if is_archive(item):
                archives.append(item)
            else:
                others.append(item)
    except OSError:
        pass
    return archives, others
