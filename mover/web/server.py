# SPDX-License-Identifier: AGPL-3.0-or-later
from aiohttp import web

from common.auth import auth_middleware
from mover.web.api import (
    _index_handler,
    _api_move,
    _api_tasks_list,
    _api_tasks_get,
    _api_tasks_delete,
    _api_tasks_retry,
    _api_tasks_clear,
    _api_health,
    _api_open,
    _api_pause,
    _api_resume,
)
from mover.web.websocket import _ws_handler


def _build_mover_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/",                           _index_handler)
    app.router.add_get("/ws",                         _ws_handler)
    app.router.add_post("/api/move",                  _api_move)
    app.router.add_get("/api/tasks",                  _api_tasks_list)
    app.router.add_post("/api/tasks/clear",           _api_tasks_clear)
    app.router.add_get("/api/tasks/{task_id}",        _api_tasks_get)
    app.router.add_delete("/api/tasks/{task_id}",     _api_tasks_delete)
    app.router.add_post("/api/tasks/{task_id}/retry", _api_tasks_retry)
    app.router.add_get("/api/health",                 _api_health)
    app.router.add_post("/api/open",                  _api_open)
    app.router.add_post("/api/pause",                 _api_pause)
    app.router.add_post("/api/resume",                _api_resume)
    return app
