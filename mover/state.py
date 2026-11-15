# SPDX-License-Identifier: AGPL-3.0-or-later
"""全局运行时状态（模块级变量）。"""
from typing import Any, Callable, Awaitable

# 任务字典：task_id → task_record dict
# task_record 字段见 mover/docs/internals.md
tasks: dict[str, dict[str, Any]] = {}

# P1-5a Q4 软暂停：暂停时新 submit 入队为 status=pending 但不 dispatch
# 不持久化（重启回到 False；启动恢复扫描会触发执行所有 pending 任务）
paused: bool = False

# WebSocket 广播回调（由 main.py 注入，避免循环依赖）
_broadcast_callback: Callable[[], Awaitable[None]] | None = None


def set_broadcast_callback(cb: Callable[[], Awaitable[None]]) -> None:
    global _broadcast_callback
    _broadcast_callback = cb
