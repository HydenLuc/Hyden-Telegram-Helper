# SPDX-License-Identifier: AGPL-3.0-or-later
"""通用原子文件写入。

所有持久化的 JSON / 文本写入都应该走这里——避免崩溃时留下半截文件。
模式：写到 .tmp → os.replace 原子替换。
"""
import json
import os
from pathlib import Path
from typing import Any


def _tmp_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".tmp") if path.suffix else path.with_name(path.name + ".tmp")


def _fsync_dir(dir_path: Path) -> None:
    """fsync 目录项，让 rename 本身也落盘（否则掉电时改名操作可能丢失）。

    部分文件系统（FAT/exFAT、某些 9p/drvfs 挂载）不支持对目录 fsync，
    最佳努力，失败静默跳过——不影响 tmp+replace 本身的原子性。
    """
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """原子写文本：tmp + fsync + os.replace + fsync 目录。

    只有 tmp+replace、没有 fsync 时，rename 前的写入可能仍停留在页缓存里——
    USB 盘意外拔出/掉电会丢数据甚至留下空文件（completed.json 空了导致去重
    失效、历史消失）。fsync 文件句柄 + fsync 目录项，让写入和改名都真正落盘。
    """
    tmp = _tmp_path(path)
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def atomic_write_json(path: Path, data: Any, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    """原子写 JSON：tmp + os.replace。"""
    atomic_write_text(path, json.dumps(data, ensure_ascii=ensure_ascii, indent=indent))
