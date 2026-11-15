# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import config

from common.atomic_io import atomic_write_json
from common.logger import get_logger

_log = get_logger("mover")

MOVER_STATE_FILE = config.STATE_DIR / "mover_state.json"  # 状态目录见 config.STATE_DIR（Docker = /state；原生 = 项目 state/）


def load_tasks() -> dict:
    if not MOVER_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(MOVER_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        _log.error(f"[mover] 加载 state 失败: {e}")
        return {}


def save_tasks(tasks: dict) -> None:
    try:
        atomic_write_json(MOVER_STATE_FILE, tasks)
    except Exception as e:
        _log.error(f"[mover] 保存 state 失败: {e}")


