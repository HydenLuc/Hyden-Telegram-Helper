# SPDX-License-Identifier: AGPL-3.0-or-later
from aiohttp import web

from common.auth import auth_middleware
from downloader.web.api import (
    _index_handler,
    _api_search, _api_watch_add, _api_watch_remove,
    _api_watch_reset_stats, _api_watch_cid_reset_stats,
    _api_watch_cid_exempt,
    _api_watch_cid_favorite,
    _api_auth, _api_auth_resend, _api_auth_qr, _api_state, _api_open, _api_retry, _api_retry_all_failed,
    _api_status, _api_history, _api_download,
    _api_completed_clear, _api_completed_delete, _api_history_clear_done,
    _api_history_clear_failed,
    _api_history_move_group,
    _api_dq_list, _api_dq_clear, _api_dq_delete, _api_dq_download,
    _api_toasts_list, _api_toast_queue, _api_toast_skip,
    _api_toast_download, _api_toast_keep, _api_toast_open_matched,
    _api_toast_delete,
    _api_hp_start, _api_hp_list, _api_hp_stop, _api_hp_rescan,
    _api_hp_download_selected, _api_hp_delete,
    _api_settings_get, _api_settings_post,
    _api_task_pause, _api_task_resume, _api_task_cancel,
    _api_pause, _api_resume,
    _api_exempt_pause, _api_exempt_resume,
    _api_saved_pause, _api_saved_resume,
    _api_downloader_stop,
)
from downloader.web.websocket import _ws_handler



async def _health(_request):
    """GET /api/health — 只说明进程活着、事件循环能响应（Docker 健康检查用，2026-11-13）。"""
    return web.json_response({"ok": True})

def _build_web_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/",                       _index_handler)
    app.router.add_get("/ws",                     _ws_handler)
    app.router.add_get("/api/state",              _api_state)
    app.router.add_get("/api/health",             _health)
    app.router.add_get("/api/status",             _api_status)
    app.router.add_get("/api/history",            _api_history)
    app.router.add_post("/api/open",              _api_open)
    app.router.add_get("/api/search",             _api_search)
    app.router.add_post("/api/watch",                       _api_watch_add)
    # P1-7: 统计控制路由必须在 {chat_id} 通配之前注册（避免 reset-stats 被当 cid）
    app.router.add_post("/api/watch/reset-stats",           _api_watch_reset_stats)
    app.router.add_post("/api/watch/{cid}/reset-stats",     _api_watch_cid_reset_stats)
    app.router.add_post("/api/watch/{cid}/exempt",          _api_watch_cid_exempt)
    app.router.add_post("/api/watch/{cid}/favorite",        _api_watch_cid_favorite)
    app.router.add_delete("/api/watch/{chat_id}",           _api_watch_remove)
    app.router.add_post("/api/auth",              _api_auth)
    app.router.add_post("/api/auth/resend",       _api_auth_resend)
    app.router.add_post("/api/auth/qr",           _api_auth_qr)
    app.router.add_post("/api/retry",             _api_retry)
    app.router.add_post("/api/retry-all-failed",  _api_retry_all_failed)
    app.router.add_post("/api/download",          _api_download)
    app.router.add_get("/api/settings",                    _api_settings_get)
    app.router.add_post("/api/settings",                   _api_settings_post)
    app.router.add_post("/api/completed/clear",            _api_completed_clear)
    app.router.add_delete("/api/history/done",             _api_history_clear_done)
    app.router.add_delete("/api/history/failed",           _api_history_clear_failed)
    app.router.add_post("/api/history/move-group",          _api_history_move_group)
    app.router.add_delete("/api/completed/{task_id}",      _api_completed_delete)
    app.router.add_post("/api/task/{task_id}/pause",       _api_task_pause)
    app.router.add_post("/api/task/{task_id}/resume",      _api_task_resume)
    app.router.add_post("/api/task/{task_id}/cancel",      _api_task_cancel)
    app.router.add_post("/api/pause",                      _api_pause)
    app.router.add_post("/api/resume",                     _api_resume)
    app.router.add_post("/api/exempt-pause",               _api_exempt_pause)
    app.router.add_post("/api/exempt-resume",              _api_exempt_resume)
    app.router.add_post("/api/saved-pause",                _api_saved_pause)
    app.router.add_post("/api/saved-resume",               _api_saved_resume)
    # 硬停 downloader（launchctl bootout；不受 KeepAlive 自动拉回）
    app.router.add_post("/api/downloader/stop",            _api_downloader_stop)
    # F6: 重复下载确认队列
    app.router.add_get(   "/api/duplicate-queue",                    _api_dq_list)
    app.router.add_delete("/api/duplicate-queue",                    _api_dq_clear)
    app.router.add_post(  "/api/duplicate-queue/{task_id}/download", _api_dq_download)
    app.router.add_delete("/api/duplicate-queue/{task_id}",          _api_dq_delete)
    # MD5 dedup: toast endpoints
    app.router.add_get(   "/api/toasts",                             _api_toasts_list)
    app.router.add_post(  "/api/toast/{toast_id}/queue",             _api_toast_queue)
    app.router.add_post(  "/api/toast/{toast_id}/skip",              _api_toast_skip)
    app.router.add_post(  "/api/toast/{toast_id}/download",          _api_toast_download)
    app.router.add_post(  "/api/toast/{toast_id}/keep",              _api_toast_keep)
    app.router.add_post(  "/api/toast/{toast_id}/open-matched",      _api_toast_open_matched)
    app.router.add_delete("/api/toast/{toast_id}",                   _api_toast_delete)
    # 历史消息下载（history-pull）
    app.router.add_post(  "/api/history-pull/start",                          _api_hp_start)
    app.router.add_get(   "/api/history-pull/jobs",                           _api_hp_list)
    app.router.add_post(  "/api/history-pull/{job_id}/stop",                  _api_hp_stop)
    app.router.add_post(  "/api/history-pull/{job_id}/rescan",                _api_hp_rescan)
    app.router.add_post(  "/api/history-pull/{job_id}/download-selected",     _api_hp_download_selected)
    app.router.add_delete("/api/history-pull/{job_id}",                       _api_hp_delete)
    return app
