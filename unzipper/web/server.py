# SPDX-License-Identifier: AGPL-3.0-or-later
from aiohttp import web

from common.auth import auth_middleware
from unzipper.web.api import (
    _index_handler,
    _api_state,
    _api_confirm,
    _api_retry,
    _api_open,
    _api_health,
    _api_submit,
    _api_pending,
    _api_history,
    _api_history_delete,
    _api_passwords_get,
    _api_passwords_add,
    _api_passwords_remove,
    _api_passwords_reorder,
    _api_concurrency_get,
    _api_concurrency_post,
    _api_pause,
    _api_resume,
    _api_settings_get,
    _api_settings_post,
    _api_extract_status,
    _api_cancel,
)
from unzipper.web.websocket import _ws_handler


def _build_unzipper_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/",                    _index_handler)
    app.router.add_get("/ws",                  _ws_handler)
    app.router.add_get("/api/state",           _api_state)
    app.router.add_post("/api/confirm/{id}",   _api_confirm)
    app.router.add_post("/api/retry",          _api_retry)
    app.router.add_post("/api/open",           _api_open)
    app.router.add_get("/api/health",          _api_health)
    app.router.add_post("/api/submit",         _api_submit)
    app.router.add_get("/api/pending",         _api_pending)
    app.router.add_get("/api/history",         _api_history)
    app.router.add_delete("/api/history",      _api_history_delete)
    app.router.add_get("/api/passwords",       _api_passwords_get)
    app.router.add_post("/api/passwords",      _api_passwords_add)
    app.router.add_delete("/api/passwords",    _api_passwords_remove)
    app.router.add_post("/api/passwords/reorder", _api_passwords_reorder)
    app.router.add_get("/api/concurrency",     _api_concurrency_get)
    app.router.add_post("/api/concurrency",    _api_concurrency_post)
    app.router.add_post("/api/pause",          _api_pause)
    app.router.add_post("/api/resume",         _api_resume)
    app.router.add_get("/api/settings",        _api_settings_get)
    app.router.add_post("/api/settings",       _api_settings_post)
    app.router.add_post("/api/extract-status", _api_extract_status)
    app.router.add_post("/api/cancel/{task_id}", _api_cancel)
    return app
