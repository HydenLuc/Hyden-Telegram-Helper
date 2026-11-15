# SPDX-License-Identifier: AGPL-3.0-or-later
"""WebSocket 实时推送：1s 广播循环 + 任务状态快照。"""
import asyncio
import json

from aiohttp import web

import mover.state as state
from common.auth import check_ws_auth

ws_clients: set[web.WebSocketResponse] = set()


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    if not check_ws_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    try:
        await ws.send_str(_build_state())
        async for _ in ws:
            pass  # ignore incoming messages
    finally:
        ws_clients.discard(ws)
    return ws


async def _broadcast() -> None:
    """向所有已连接客户端推送当前状态快照。"""
    if not ws_clients:
        return
    payload = _build_state()
    dead: set[web.WebSocketResponse] = set()
    for ws in ws_clients:
        try:
            await ws.send_str(payload)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def _broadcast_loop() -> None:
    while True:
        await asyncio.sleep(1)
        await _broadcast()


def _build_state() -> str:
    """构建 WebSocket 推送的 JSON 状态快照。"""
    tasks = state.tasks
    running = sum(1 for t in tasks.values() if t["status"] == "copying")
    queue_depth = sum(1 for t in tasks.values() if t["status"] == "pending")
    return json.dumps(
        {
            "tasks": tasks,
            "running": running,
            "queue_depth": queue_depth,
            "paused": state.paused,
        },
        ensure_ascii=False,
    )
