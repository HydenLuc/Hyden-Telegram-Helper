# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import asyncio
from aiohttp import web

import downloader.state as state
from common.auth import check_ws_auth


def _history_jobs_summary() -> list:
    """WS 摘要模式：去掉 scan_results 完整列表，仅留 count（避免 payload 暴大）。"""
    out = []
    for job in state.history_jobs.values():
        if not isinstance(job, dict):
            continue
        d = {k: v for k, v in job.items() if k != "scan_results"}
        d["scan_results_count"] = len(job.get("scan_results") or [])
        out.append(d)
    out.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return out


def _build_state() -> str:
    total_speed   = sum(t.get("speed", 0.0) for t in state.active_downloads.values())
    waiting_count = sum(1 for t in state.active_downloads.values() if t["status"] == "waiting")
    return json.dumps({
        "active":        list(state.active_downloads.values()),
        "completed":     state.completed_downloads,
        "watched":       state.watched,
        "auth":          state._auth_step,
        "auth_info":     state._auth_info,
        "total_speed":   total_speed,
        "active_conns":  state._total_connections,
        "waiting_count": waiting_count,
        "paused":        state.monitoring_paused,
        "exempt_paused": state.exempt_paused,
        "disk_usage":    state.disk_usage,
        "duplicate_queue": state.duplicate_queue,
        "duplicate_count": len(state.duplicate_queue),
        "pending_toasts":  state.pending_toasts,
        "history_jobs":    _history_jobs_summary(),
        "settings": {
            "max_total_connections": state.MAX_TOTAL_CONNECTIONS,
            "chunk_size":            state.CHUNK_SIZE,
        },
    }, ensure_ascii=False)


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
        await asyncio.sleep(0.5)  # 0.5s：下载进度变化快，需要更实时的推送
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
