# SPDX-License-Identifier: AGPL-3.0-or-later
"""工具函数：文件系统操作、原子移动、临时目录管理。"""
import os
import shutil
import uuid
from pathlib import Path
from common.logger import get_logger

_log = get_logger("mover")

STAGING_PREFIX = ".mover_staging_"


def staging_dir_name() -> str:
    """生成唯一临时目录名：.mover_staging_<uuid4_hex>"""
    return f"{STAGING_PREFIX}{uuid.uuid4().hex}"


def is_cross_filesystem(src: Path, dst_parent: Path) -> bool:
    """判断 src 和 dst_parent 是否在不同文件系统（通过比较 st_dev）。"""
    return os.stat(src).st_dev != os.stat(dst_parent).st_dev


def cleanup_staging_dirs(target_parent: Path) -> int:
    """清理 target_parent 下所有 .mover_staging_* 临时目录，返回清理数量。"""
    count = 0
    if not target_parent.exists():
        return 0
    for entry in target_parent.iterdir():
        if entry.name.startswith(STAGING_PREFIX) and entry.is_dir():
            try:
                shutil.rmtree(entry)
                count += 1
            except Exception as e:
                _log.error(f"[mover] 清理 staging 失败 {entry}: {e}")
    return count
