# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dashboard 模块：单页监控聚合 + 设置面板。

- `GET /`              返回 HTML 单页
- `GET /api/overview`  后端代理：并发拉取三模块状态，统一返回
- `GET /api/config`    读取可编辑配置（白名单）+ 部署模式
- `POST /api/config`   校验并写入 .env（重启后生效）

后端代理设计避开 CORS：浏览器只调 dashboard 同源 API。
"""
import asyncio
import os
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

import config
from dashboard.templates import DASHBOARD_HTML
from dashboard import services as svc_ctl
from common.auth import auth_middleware
from common.env_writer import save_env_values
from common.logger import get_logger
from common.shutdown import install_stop_handler

_log = get_logger("dashboard")

# ── 设置页可编辑字段白名单（凭证/端口/监听地址永不开放编辑） ─────────────
#    "path" 路径 | ("int", min, max) 整数区间 | "bool" | ("enum", [...]) 枚举
_EDITABLE_FIELDS: dict[str, Any] = {
    "DATA_ROOT":             "path",
    "DOWNLOAD_DIR":          "path",
    "WATCH_PATH":            "path",
    "OUTPUT_PATH":           "path",
    "MAX_TOTAL_CONNECTIONS": ("int", 1, 100),
    "MAX_CONCURRENT_TASKS":  ("int", 1, 20),
    "MOVER_MAX_CONCURRENT":  ("int", 1, 20),
    "DOWNLOAD_TIMEOUT":      ("int", 10, 3600),
    "AUTO_MOVE":             "bool",
    "LOG_LEVEL":             ("enum", ["DEBUG", "INFO", "WARNING", "ERROR"]),
    "RESTART_MODE":          ("enum", ["RESUME", "PAUSED"]),   # 见 common/run_state.py
}
_PATH_FIELDS = ("DATA_ROOT", "DOWNLOAD_DIR", "WATCH_PATH", "OUTPUT_PATH")


def _resolve_dirs(env: dict[str, str]) -> dict[str, Path]:
    """按 config.py 相同优先级（显式 > DATA_ROOT 派生 > 内置默认）计算三个生效目录。"""
    data_root = (env.get("DATA_ROOT") or "").strip()
    if data_root:
        dmz = Path(data_root) / "telegramDMZ"
        defaults = {"DOWNLOAD_DIR": dmz / "download",
                    "WATCH_PATH":   dmz / "move",
                    "OUTPUT_PATH":  dmz / "unzip"}
    else:
        defaults = {"DOWNLOAD_DIR": config.DEFAULT_DOWNLOAD_DIR,
                    "WATCH_PATH":   config.DEFAULT_WATCH_PATH,
                    "OUTPUT_PATH":  config.DEFAULT_OUTPUT_PATH}
    return {k: Path(env[k]) if (env.get(k) or "").strip() else defaults[k]
            for k in ("DOWNLOAD_DIR", "WATCH_PATH", "OUTPUT_PATH")}


def _validate_dirs_disjoint(dirs: dict[str, Path]) -> str | None:
    """三个目录互不重叠（相等或互为父子都不行）。返回错误信息或 None。"""
    items = [(k, p.expanduser().resolve()) for k, p in dirs.items()]
    for i, (k1, p1) in enumerate(items):
        for k2, p2 in items[i + 1:]:
            if p1 == p2 or p1.is_relative_to(p2) or p2.is_relative_to(p1):
                return f"{k1} 与 {k2} 目录重叠（{p1} ↔ {p2}），会触发重复检测和误触发解压"
    return None


async def _config_get_handler(_request: web.Request) -> web.Response:
    values = {k: os.getenv(k, "") for k in _EDITABLE_FIELDS}
    return web.json_response({
        "docker": config.IS_DOCKER,
        "env_file": str(config.ENV_FILE),
        "values": values,
        "effective_dirs": {
            "DOWNLOAD_DIR": str(config.DOWNLOAD_DIR),
            "WATCH_PATH":   str(config.WATCH_PATH),
            "OUTPUT_PATH":  str(config.OUTPUT_PATH),
        },
        "restart_hint": "docker compose restart" if config.IS_DOCKER
                        else "./stop.sh && ./start.sh",
    })


async def _config_post_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效 JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "请求体必须是对象"}, status=400)

    updates: dict[str, str] = {}
    for key, raw in body.items():
        if key not in _EDITABLE_FIELDS:
            return web.json_response({"error": f"字段不允许修改：{key}"}, status=400)
        spec = _EDITABLE_FIELDS[key]
        val = str(raw).strip()
        if spec == "path":
            if config.IS_DOCKER:
                return web.json_response(
                    {"error": "Docker 部署下数据目录由宿主机映射决定：请修改宿主 .env 的 "
                              "HOST_DATA_ROOT 后执行 docker compose up -d"}, status=400)
        elif spec == "bool":
            if val.lower() not in ("true", "false"):
                return web.json_response({"error": f"{key} 只能是 true/false"}, status=400)
            val = val.lower()
        elif isinstance(spec, tuple) and spec[0] == "int":
            try:
                n = int(val)
            except ValueError:
                return web.json_response({"error": f"{key} 必须是整数"}, status=400)
            if not (spec[1] <= n <= spec[2]):
                return web.json_response(
                    {"error": f"{key} 需在 {spec[1]}~{spec[2]} 之间"}, status=400)
        elif isinstance(spec, tuple) and spec[0] == "enum":
            val = val.upper()
            if val not in spec[1]:
                return web.json_response(
                    {"error": f"{key} 只能是 {'/'.join(spec[1])}"}, status=400)
        updates[key] = val

    if not updates:
        return web.json_response({"error": "没有可保存的字段"}, status=400)

    # 路径互斥校验：用"保存后将生效"的值模拟一遍派生
    if any(k in _PATH_FIELDS for k in updates):
        merged = {k: os.getenv(k, "") for k in _PATH_FIELDS}
        merged.update({k: v for k, v in updates.items() if k in _PATH_FIELDS})
        err = _validate_dirs_disjoint(_resolve_dirs(merged))
        if err:
            return web.json_response({"error": err}, status=400)

    try:
        save_env_values(config.ENV_FILE, updates)
    except Exception as e:
        _log.error(f"[dashboard] 写入 .env 失败: {e}")
        return web.json_response({"error": f"写入 .env 失败：{e}"}, status=500)

    _log.info(f"[dashboard] 设置已保存：{', '.join(sorted(updates))}")
    return web.json_response({
        "saved": sorted(updates),
        "need_restart": True,
        "restart_hint": "docker compose restart" if config.IS_DOCKER
                        else "./stop.sh && ./start.sh",
    })


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
    app.router.add_get("/", _index_handler)
    app.router.add_get("/api/overview", _overview_handler)
    app.router.add_get("/api/config", _config_get_handler)
    app.router.add_post("/api/config", _config_post_handler)
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
