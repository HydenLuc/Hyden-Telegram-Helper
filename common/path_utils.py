# SPDX-License-Identifier: AGPL-3.0-or-later
"""路径输入校验（HTTP 接口共用）。"""
from pathlib import Path

import config

# Docker 里工作目录只能放在这个挂载点下面（compose 把宿主机的数据目录挂到这里）
DOCKER_DATA_MOUNT = Path("/data")


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_path(raw) -> tuple[Path | None, str | None]:
    """校验用户提供的路径字符串。

    返回 (Path, None) 表示成功；(None, error) 表示失败。
    会创建目标目录（mkdir parents=True exist_ok=True）。

    Docker 部署（2026-11-11 加）：只接受 /data 下面的路径。
    容器里 /data 以外的地方是容器自己的可写层——下载器 / 解压器的设置页把目录改到那里，
    文件照样能写进去，但**重建容器就全没了**，而且宿主机上根本看不到。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, "path must be a non-empty string"
    p = Path(raw).expanduser()
    if not p.is_absolute():
        return None, "path must be absolute"
    if config.IS_DOCKER and not _is_under(p, DOCKER_DATA_MOUNT):
        return None, (f"Docker 部署里路径必须在 {DOCKER_DATA_MOUNT} 下面"
                      f"（{DOCKER_DATA_MOUNT} 之外是容器自己的空间，重建容器就会丢）。"
                      "要换宿主机上的位置，改宿主机 .env 里的 HOST_DATA_ROOT 再重建容器")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return None, f"cannot create directory: {e}"
    return p, None
