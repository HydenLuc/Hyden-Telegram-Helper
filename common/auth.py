# SPDX-License-Identifier: AGPL-3.0-or-later
"""共享 API 认证。

三模块（downloader / mover / unzipper）通过此模块统一启用 `X-API-Key` 鉴权。

行为：
- 浏览器从别的网站发来的写请求（`Origin` 对不上）一律 403，不管设没设 API_KEY（见 is_cross_site）
- 当 `config.API_KEY` 为空字符串时，其余请求放行（向下兼容旧用户）
- 当 `config.API_KEY` 非空时：
  - `/api/` 前缀路径要求 `X-API-Key` header 匹配
  - WebSocket 端点（`/ws`）通过 `check_ws_auth(request)` 检查 query string `?key=` 或 header
  - `/` 首页会把 API_KEY 明文注入返回的 HTML 供前端 JS 用，因此也要求
    `?key=` 或 `X-API-Key` 之一匹配——否则 key 形同虚设（谁都能访问 / 拿到 key
    再去调 /api/）。dashboard 反代模块页面时走 X-API-Key header，不受影响；
    直接访问某模块端口需要在 URL 后加 `?key=<API_KEY>`。

用法：
    from aiohttp import web
    from common.auth import auth_middleware, check_ws_auth

    app = web.Application(middlewares=[auth_middleware])

    async def _ws_handler(request):
        if not check_ws_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        ...
"""
import hmac
from urllib.parse import urlsplit

from aiohttp import web

import config

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _key_ok(given: str) -> bool:
    """常数时间比较，免得能按响应时间一位一位猜。"""
    return hmac.compare_digest(given.encode(), config.API_KEY.encode())


def is_cross_site(request: web.Request) -> bool:
    """浏览器从**别的网站**发来的请求（2026-11-15）。

    为什么要拦：默认不设 API_KEY、只听 127.0.0.1。这时你本机浏览器里打开的任何网页，
    都能用 JS / 表单向 http://localhost:8092/api/move 之类的接口发请求（CSRF），
    或者用 WebSocket 读状态（里面有文件名）。浏览器跨站请求一定带 `Origin` 头，
    它和本服务的地址对不上就拒绝。

    · 没有 Origin：curl、脚本、服务之间互相调用（dashboard 转发时会去掉 Origin）→ 放行
    · Origin 是 "null"（沙箱 iframe、本地文件）→ 当跨站
    · 在反向代理后面：代理一般保留 Host；改写了 Host 的（nginx 默认）会带 X-Forwarded-Host，两个都认
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return False
    if origin == "null":
        return True
    netloc = urlsplit(origin).netloc.lower()
    hosts = {(request.host or "").lower()}
    fwd = request.headers.get("X-Forwarded-Host", "")
    hosts.update(h.strip().lower() for h in fwd.split(",") if h.strip())
    return netloc not in hosts


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if (request.path.startswith('/api/') and request.method not in _SAFE_METHODS
            and is_cross_site(request)):
        return web.json_response({"error": "Forbidden: cross-site request"}, status=403)
    if config.API_KEY:
        if request.path.startswith('/api/'):
            if not _key_ok(request.headers.get('X-API-Key', '')):
                return web.json_response({"error": "Unauthorized"}, status=401)
        elif request.path == '/':
            key = request.rel_url.query.get('key', '') or request.headers.get('X-API-Key', '')
            if not _key_ok(key):
                return web.json_response(
                    {"error": "Unauthorized，请在 URL 后加 ?key=<API_KEY> 访问"}, status=401)
    return await handler(request)


def check_ws_auth(request: web.Request) -> bool:
    """WebSocket 端点鉴权检查。

    认证顺序：query string `?key=...` → header `X-API-Key`。
    `config.API_KEY` 为空时放行。
    """
    if is_cross_site(request):      # 别的网站开 WebSocket 读状态（CSWSH）
        return False
    if not config.API_KEY:
        return True
    key = request.rel_url.query.get('key', '') or request.headers.get('X-API-Key', '')
    return _key_ok(key)
