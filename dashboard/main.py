# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dashboard 模块：单页监控聚合 + 设置面板。

- `GET /`              返回 HTML 单页
- `GET /api/overview`  后端代理：并发拉取三模块状态，统一返回
- `GET/POST /api/config`、`/api/help`、`/api/notify/test`  设置页，见 dashboard/settings_api.py

后端代理设计避开 CORS：浏览器只调 dashboard 同源 API。
"""
import asyncio
from typing import Any

import aiohttp
from aiohttp import web

import config
from dashboard.templates import DASHBOARD_HTML
from dashboard import services as svc_ctl
from dashboard import settings_api
from common.auth import PUBLIC_PAGES_KEY, auth_middleware
from common.logger import get_logger
from common.shutdown import install_stop_handler

_log = get_logger("dashboard")

# 离线判断：连续 N 次失败才标 online=false；1 次成功立即恢复
OFFLINE_THRESHOLD = 2

# 每模块独立超时（秒）。正常 <100ms。
# ⚠️ 原来是 3 秒，实测太紧：downloader 恢复数万个 pending 任务时事件循环很忙，
# 3 次里有 2 次超时 → 返回 "data": null → 前端频道页要么崩要么空白（2026-08-13）。
# 三个模块是 asyncio.gather 并发拉的，放宽不会让整体变慢，只是慢模块多等一会儿。
# 2026-08-14 再放宽到 25：恢复数万个任务时实测响应时间在
# 0.17s / 2.3s / 30s 之间剧烈抖动（大状态文件同步 dumps+fsync 把事件循环喂满，
# 已在 downloader/storage.py 用合并写治本）。10 秒会间歇性误判「离线」→ 页面空白。
MODULE_TIMEOUT = 25

_failure_counters: dict[str, int] = {
    "downloader": 0,
    "mover": 0,
    "unzipper": 0,
}


async def _fetch_module(
    session: aiohttp.ClientSession, module: str, url: str
) -> dict[str, Any]:
    """请求单个模块。返回 {"online": bool, "data": dict | None}。"""
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=MODULE_TIMEOUT)
        ) as resp:
            if resp.status == 200:
                _failure_counters[module] = 0
                return {"online": True, "data": await resp.json()}
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass

    _failure_counters[module] += 1
    online = _failure_counters[module] < OFFLINE_THRESHOLD
    return {"online": online, "data": None}


# ── 通用反向代理 ──────────────────────────────────────────────────
#    浏览器只跟 dashboard(:8090) 同源通信；此代理把 /api/proxy/<mod>/<路径>
#    转发到对应模块端口，并注入 X-API-Key（模块间共享 config.API_KEY）。
#    好处：三模块 40+ 个既有端点无需在 dashboard 逐一重写，前端直接复用。
#    拆成多容器后 host 也要跟着变（单容器时三个 *_HOST 都是 127.0.0.1，行为不变）。
_PROXY_TARGETS = {
    "dl": lambda: (config.WEB_HOST, config.WEB_PORT),            # downloader :8091
    "mv": lambda: (config.MOVER_HOST, config.MOVER_PORT),        # mover      :8092
    "uz": lambda: (config.UNZIPPER_HOST, config.UNZIPPER_PORT),  # unzipper   :8093
}
_HOP_HEADERS = {"host", "content-length", "transfer-encoding", "connection",
                "keep-alive", "x-api-key",
                # 浏览器的来源头不往后传：dashboard 自己已经查过跨站，后面的模块 Host 是
                # mover:8092 之类，和浏览器的 Origin 永远对不上，带过去会被误拦（2026-11-15）
                "origin", "referer"}


async def _proxy_handler(request: web.Request) -> web.StreamResponse:
    mod = request.match_info["mod"]
    if mod not in _PROXY_TARGETS:
        return web.json_response({"error": f"未知模块：{mod}"}, status=404)
    tail = request.match_info.get("tail", "")
    host, port = _PROXY_TARGETS[mod]()
    url = f"http://{host}:{port}/{tail}"

    fwd_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _HOP_HEADERS}
    if config.API_KEY:
        fwd_headers["X-API-Key"] = config.API_KEY
    body = await request.read()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                request.method, url,
                params=request.rel_url.query,
                headers=fwd_headers,
                data=body if body else None,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
            ) as upstream:
                raw = await upstream.read()
                resp = web.Response(
                    body=raw, status=upstream.status,
                    content_type=upstream.content_type,
                    charset=upstream.charset,
                )
                return resp
    except aiohttp.ClientConnectorError:
        return web.json_response(
            {"error": f"{mod} 模块未运行（:{port} 不可达）"}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": f"{mod} 模块响应超时"}, status=504)


async def _index_handler(_request: web.Request) -> web.Response:
    html = DASHBOARD_HTML
    html = html.replace("__DL_PORT__", str(config.WEB_PORT))
    html = html.replace("__MV_PORT__", str(config.MOVER_PORT))
    html = html.replace("__UZ_PORT__", str(config.UNZIPPER_PORT))
    # no-store：控制台是内联 HTML，禁止浏览器缓存，改动后刷新即生效
    return web.Response(text=html, content_type="text/html", charset="utf-8",
                        headers={"Cache-Control": "no-store, must-revalidate"})


def _slim(payload: dict) -> None:
    """
    就地剥掉概览用不到的大列表，只留计数。
    实测全量 overview 5.7MB，其中 downloader.completed(5000 条)=4.2MB、
    unzipper.history(87 条)=0.7MB，占 98%；概览卡片只用得到计数。
    手机端每 3 秒轮询一次，slim 后 ~45KB（约 1/125），省流量和电。
    """
    dl = (payload.get("downloader") or {}).get("data")
    if isinstance(dl, dict) and isinstance(dl.get("completed"), list):
        # downloader 已带 ?slim=1，这里通常已是空列表；completed_total 才是真计数
        dl.setdefault("completed_count", dl.get("completed_total", len(dl["completed"])))
        dl["completed"] = []
    uz = (payload.get("unzipper") or {}).get("data")
    if isinstance(uz, dict) and isinstance(uz.get("history"), list):
        uz["history_count"] = len(uz["history"])
        uz["history"] = []


# 网页端「正在下载」最多渲染多少条 active。队列有数万条时整个列表有好几 MB，
# 而人眼一次也就看几十条；真实总数走 active_count，被截断时前端会标出来。
ACTIVE_LIMIT = 300


async def _overview_handler(_request: web.Request) -> web.Response:
    _want_slim = _request.query.get("slim") == "1"
    headers = {"X-API-Key": config.API_KEY}
    async with aiohttp.ClientSession(headers=headers) as session:
        downloader, mover, unzipper = await asyncio.gather(
            _fetch_module(
                session, "downloader",
                # 上游档位跟着浏览器要的走：
                #   手机端 slim=1  → 上游也 slim=1（两个大列表都不要，只要计数）
                #   网页端 默认    → 上游 slim=completed&limit=N
                #                    砍掉 completed（5000 条 5MB），**保留 active**，
                #                    否则网页「正在下载」永远是空的。
                # ⚠️ 这里原来无条件写死 slim=1 —— 上游那一跳是省下来了，但网页端的
                #    下载列表也一起没了，恒显示空白（2026-08-13 引入，08-14 修）。
                f"http://{config.WEB_HOST}:{config.WEB_PORT}/api/status" + (
                    "?slim=1" if _want_slim
                    else f"?slim=completed&limit={ACTIVE_LIMIT}"
                ),
            ),
            _fetch_module(
                session, "mover",
                f"http://{config.MOVER_HOST}:{config.MOVER_PORT}/api/health",
            ),
            _fetch_module(
                session, "unzipper",
                f"http://{config.UNZIPPER_HOST}:{config.UNZIPPER_PORT}/api/state",
            ),
        )
    dl_data = (downloader or {}).get("data") or {}
    payload = {
        "downloader": downloader,
        "mover": mover,
        "unzipper": unzipper,
        "brand_name": brand_name(load_branding(), dl_data.get("account_name") if isinstance(dl_data, dict) else None),
        # 前端据此在「不是本机打开、又没设钥匙」时显示黄色提醒
        "no_api_key": not config.API_KEY,
    }
    # ?slim=1：只要计数不要大列表（手机端轮询用）。
    if _want_slim:
        _slim(payload)
    return web.json_response(payload)


async def _services_get_handler(_request: web.Request) -> web.Response:
    """GET /api/services — 四个服务的状态。原生部署返回 supported=False，前端隐藏面板。"""
    status, body = await svc_ctl.list_services()
    return web.json_response(body, status=status)


async def _services_action_handler(request: web.Request) -> web.Response:
    """POST /api/services/{name}/{start|stop|restart} —— 转给控制服务（只有 Docker 版）。"""
    name, action = request.match_info["name"], request.match_info["action"]
    status, body = await svc_ctl.act(name, action)
    _log.info(f"[services] {action} {name} → HTTP {status} {body.get('message')!r}")
    return web.json_response(body, status=status)


# ── 页面标题「<名字> TGhelper」（2026-11-13，hyden 定）────────────────────
# 项目名叫 Hyden TGhelper；网页上的「Hyden」默认换成登录的 Telegram 账号名，
# 设置页可以自定义，也可以勾选隐藏只显示「TGhelper」。即时生效，不用重启。
_BRANDING_FILE = config.STATE_DIR / "dashboard_branding.json"
_BRANDING_DEFAULT = {"display_name": "", "hide_name": False}
BRAND_FALLBACK = "Hyden"          # 还没登录、也没自定义时
_NAME_MAX = 30


def load_branding() -> dict:
    import json
    try:
        data = json.loads(_BRANDING_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**_BRANDING_DEFAULT, **{k: data[k] for k in _BRANDING_DEFAULT if k in data}}
    except FileNotFoundError:
        pass
    except Exception as e:
        _log.warning(f"[branding] 读 {_BRANDING_FILE.name} 失败，用默认：{e}")
    return dict(_BRANDING_DEFAULT)


def brand_name(branding: dict, account_name: str | None) -> str:
    """标题前半截显示什么。空字符串 = 只显示 TGhelper。"""
    if branding.get("hide_name"):
        return ""
    return (branding.get("display_name") or "").strip() or (account_name or "").strip() or BRAND_FALLBACK


async def _branding_get_handler(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, **load_branding()})


async def _branding_post_handler(request: web.Request) -> web.Response:
    from common.atomic_io import atomic_write_json
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "无效 JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "请求体必须是对象"}, status=400)
    data = load_branding()
    if "hide_name" in body:
        if not isinstance(body["hide_name"], bool):
            return web.json_response({"ok": False, "error": "hide_name 只能是 true / false"}, status=400)
        data["hide_name"] = body["hide_name"]
    if "display_name" in body:
        name = " ".join(str(body["display_name"] or "").split())   # 去掉换行和多余空格
        if len(name) > _NAME_MAX:
            return web.json_response({"ok": False, "error": f"名字最多 {_NAME_MAX} 个字"}, status=400)
        data["display_name"] = name
    atomic_write_json(_BRANDING_FILE, data)
    return web.json_response({"ok": True, **data})


async def _health_handler(_request: web.Request) -> web.Response:
    """GET /api/health — Docker 健康检查用（2026-11-13）。"""
    return web.json_response({"ok": True})


async def _autostart_get_handler(_request: web.Request) -> web.Response:
    """GET /api/autostart — 开机自动启动的状态（tools/autostart.py）。"""
    from tools import autostart
    return web.json_response({"ok": True, **autostart.status()})


async def _autostart_post_handler(request: web.Request) -> web.Response:
    """POST /api/autostart {"enabled": true|false} — 只写 / 删配置文件，不会立刻启停程序。"""
    from tools import autostart
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "无效 JSON"}, status=400)
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return web.json_response({"ok": False, "error": "要传 enabled: true / false"}, status=400)
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, autostart.enable if body["enabled"] else autostart.disable)
    _log.info(f"[autostart] {'开启' if body['enabled'] else '关闭'} → ok={r.get('ok')} {r.get('error', '')}")
    return web.json_response(r, status=200 if r.get("ok") else 400)


async def main():
    app = web.Application(middlewares=[auth_middleware])
    # 控制台首页只是一个空壳 HTML（不含钥匙，数据都走 /api/），不用钥匙也能打开：
    # 设了 API_KEY 后，浏览器打开页面、遇到 401 再弹框要钥匙；监控探首页也照样是 200。
    app[PUBLIC_PAGES_KEY] = frozenset({"/"})
    app.router.add_get("/", _index_handler)
    app.router.add_get("/api/overview", _overview_handler)
    app.router.add_get("/api/config", settings_api.config_get_handler)
    app.router.add_post("/api/config", settings_api.config_post_handler)
    app.router.add_get("/api/help", settings_api.help_handler)
    app.router.add_post("/api/notify/test", settings_api.notify_test_handler)
    app.router.add_get("/api/health", _health_handler)
    app.router.add_get("/api/branding", _branding_get_handler)
    app.router.add_post("/api/branding", _branding_post_handler)
    app.router.add_get("/api/autostart", _autostart_get_handler)
    app.router.add_post("/api/autostart", _autostart_post_handler)
    # 服务启停：只有 Docker 版，转给 control 服务（dashboard 只读，原生部署隐藏）
    app.router.add_get("/api/services", _services_get_handler)
    app.router.add_post("/api/services/{name}/{action}", _services_action_handler)
    # 通用代理：/api/proxy/<mod>/<任意路径>，转发到三模块（GET/POST/DELETE/PUT）
    app.router.add_route("*", "/api/proxy/{mod}/{tail:.*}", _proxy_handler)

    # 先装退出处理再开端口：端口一通就可能收到 SIGTERM（docker stop、测试），
    # 晚装的话那一瞬间会被默认行为直接杀掉，收尾代码不跑（2026-11-14 CI 撞到）
    stop = install_stop_handler("dashboard", _log)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, config.LISTEN_HOST, config.DASHBOARD_PORT).start()
    _log.info(f"Dashboard 已启动：http://localhost:{config.DASHBOARD_PORT}")

    # 收到 SIGTERM / SIGINT 就退出；以前这里永远等不到，docker stop 只能干等 10 秒后硬杀
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
        _log.info("dashboard 已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("dashboard 收到 KeyboardInterrupt，正常退出")
