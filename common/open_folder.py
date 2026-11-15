# SPDX-License-Identifier: AGPL-3.0-or-later
"""在服务所在机器的文件管理器里打开一个文件夹（网页上「打开文件夹」按钮用）。

以前四处都写死 `xdg-open`（Linux 桌面专用），而且不捕获异常：
macOS / Windows 上直接 500，Docker 里也是 500（2026-11-11 跨环境排查发现）。

各环境的做法：
  · Windows：os.startfile —— 等于在资源管理器里双击
  · macOS：open
  · Linux：xdg-open（要有桌面环境；纯服务器上没有这个命令，会返回原因）
  · Docker：容器打不开宿主机的文件管理器，直接返回原因，不去瞎试
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import config


def open_in_file_manager(path: Path) -> tuple[bool, str]:
    """打开文件夹。返回 (是否成功, 失败原因)。不抛异常。"""
    if config.IS_DOCKER:
        return False, "Docker 部署里打不开宿主机的文件管理器，请在宿主机上打开这个目录"
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]  # 只有 Windows 有
            return True, ""
        cmd = "open" if sys.platform == "darwin" else "xdg-open"
        exe = shutil.which(cmd)
        if not exe:
            return False, f"找不到 {cmd} 命令（这台机器可能没有桌面环境）"
        # 不等它结束：文件管理器会一直开着。start_new_session 让它跟服务进程脱钩，
        # 服务重启时不会把用户开着的窗口一起带走。
        subprocess.Popen([exe, str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True, ""
    except Exception as e:  # noqa: BLE001 —— 打不开就告诉用户原因，不能让接口 500
        return False, str(e)
