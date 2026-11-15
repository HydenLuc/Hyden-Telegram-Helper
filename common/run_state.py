# SPDX-License-Identifier: AGPL-3.0-or-later
"""重启 / 断电后回到上次的运行状态（2026-11-13，hyden 要求）。

以前：下载器每次启动都把「全局暂停」「例外暂停」强制打开，解压器 / 搬运器每次启动都是「运行」。
断电来电或者重开程序，状态全变了，要人去页面上重新点。

现在：每个模块在开关被拨动时，把自己的开关写进 state/run_state_<模块>.json
（**各写各的文件**：四个模块是四个进程，抢同一个 JSON 会互相覆盖）。启动时按 RESTART_MODE：

  RESUME（默认）  恢复成关机前的样子。从来没记录过的开关 → 用出厂默认（下载监听暂停）。
  PAUSED          每次启动都回到出厂默认（旧行为）。离线期间积压太多、不想一来电就全开下时用：
                  2026-08-06 重启后积压一下子全开下，队列涨到 1800+，那时才加了「启动默认暂停」。

写失败只记日志不抛：开关本身已经在内存里生效了，不能因为落盘失败让页面上的按钮报错。
"""
from __future__ import annotations

import json
import logging

import config
from common.atomic_io import atomic_write_json

_log = logging.getLogger("run_state")


def _file(module: str):
    return config.STATE_DIR / f"run_state_{module}.json"


def load(module: str) -> dict:
    f = _file(module)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        _log.warning(f"[run_state] 读 {f.name} 失败，按出厂默认启动：{e}")
        return {}


def save(module: str, **flags) -> None:
    """记下开关的当前值（只改传进来的键，其余保留）。"""
    data = load(module)
    data.update({k: bool(v) for k, v in flags.items()})
    try:
        atomic_write_json(_file(module), data)
    except Exception as e:
        _log.error(f"[run_state] 写 {_file(module).name} 失败（重启后这个开关会回到默认）：{e}")


def restore(module: str, key: str, default: bool) -> bool:
    """启动时该用的开关值。default = 出厂默认（PAUSED 模式下永远用它）。"""
    if config.RESTART_MODE == "PAUSED":
        return default
    v = load(module).get(key)
    return default if v is None else bool(v)
