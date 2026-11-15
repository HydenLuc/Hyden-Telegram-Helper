# SPDX-License-Identifier: AGPL-3.0-or-later
"""备份 / 还原工具用的「状态目录在哪」。规则和 config.STATE_DIR 保持一致（2026-11-11）。

为什么不直接 import config：备份工具常在**宿主机**上跑（比如服务器上的每日定时备份），
宿主机没装项目依赖（python-dotenv、telethon…），而且 import config 会建数据目录、
要求 API_ID 等必填项。所以这里只用标准库，自己读一遍规则。

优先级：命令行 --state-dir → 环境变量 STATE_DIR → 项目根 .env 里的 STATE_DIR → 项目/state
相对路径一律按项目根算。

Docker 部署：宿主机上项目的 state/ 就是挂进容器的 /state，用默认值即可。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _from_env_file_key(env_file: Path, key: str) -> str:
    """从 .env 里读一个键（不依赖 python-dotenv）。没有就返回空串。"""
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith(f"{key}="):
            return s.split("=", 1)[1].strip().strip("'\"")
    return ""


def _from_env_file(env_file: Path) -> str:
    return _from_env_file_key(env_file, "STATE_DIR")


def resolve_state_dir(cli_value: str | None = None) -> Path:
    raw = (cli_value or os.getenv("STATE_DIR", "") or _from_env_file(PROJECT_ROOT / ".env")).strip()
    if not raw:
        return PROJECT_ROOT / "state"
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()
