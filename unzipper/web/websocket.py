# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import asyncio
from aiohttp import web

import unzipper.state as state
from common.auth import check_ws_auth


_INTERNAL_TASK_FIELDS = {"proc", "cancel_event"}


def _sanitize_current_tasks(tasks: dict) -> dict:
    """剔除 P2-4 的内部字段（proc / cancel_event 不可 JSON 序列化）。"""
    out = {}
    for tid, rec in tasks.items():
        if isinstance(rec, dict):
            out[tid] = {k: v for k, v in rec.items() if k not in _INTERNAL_TASK_FIELDS}
        else:
            out[tid] = rec
    return out


def _build_state() -> str:
    return json.dumps({
        "current_tasks": _sanitize_current_tasks(state.current_tasks),
        "pending": [
            {"id": id_, "name": rec["name"], "kind": rec.get("kind", "multipart")}
            for id_, rec in state.pending_multipart.items()
        ],
        "history": state.history[-100:],
        "paused": state.paused,
    }, ensure_ascii=False, default=str)


async def _broadcast():
    if not state.ws_clients:
        return
    data = _build_state()
    dead = set()
    for ws in list(state.ws_clients):
        try:
            await ws.send_str(data)
        except Exception:
            dead.add(ws)
    state.ws_clients.difference_update(dead)


async def _broadcast_loop():
    while True:
        await asyncio.sleep(1)  # 1s：解压任务粒度较粗，1s 足够
        await _broadcast()


async def _ws_handler(request):
    if not check_ws_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    state.ws_clients.add(ws)
    try:
        await ws.send_str(_build_state())
        async for _ in ws:
            pass
    finally:
        state.ws_clients.discard(ws)
    return ws
