# SPDX-License-Identifier: AGPL-3.0-or-later
"""TGhelper 控制服务：只负责启停本项目的几个容器（只在 Docker 部署里有）。

为什么要单独一个服务、权限怎么收窄，见 control/docker_api.py 开头。

接口（只在 compose 内部网络可达，不映射端口）：
  GET  /api/services                       四个服务的状态
  POST /api/services/{name}/{start|stop|restart}

另外在后台跑「不健康自动重启」（control/autoheal.py，AUTOHEAL=false 可关）。
"""
import asyncio

from aiohttp import web

import config
from common.auth import auth_middleware
from common.logger import get_logger
from common.shutdown import install_stop_handler
from control import autoheal, docker_api

_log = get_logger("control")


async def _list_handler(_request: web.Request) -> web.Response:
    try:
        services = await docker_api.list_services()
    except docker_api.DockerError as e:
        _log.error(f"[control] 列服务失败：{e}")
        return web.json_response({"ok": False, "message": str(e)}, status=502)
    return web.json_response({"ok": True, "services": services})


async def _action_handler(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    action = request.match_info["action"]
    try:
        r = await docker_api.do_action(name, action)
    except docker_api.DockerError as e:
        _log.error(f"[control] {action} {name} 失败：{e}")
        return web.json_response({"ok": False, "message": str(e)}, status=502)
    _log.info(f"[control] {action} {name} → {r['message']}")
    return web.json_response({"ok": r["ok"], "message": r["message"]}, status=r["http"])


async def _health(_request):
    """GET /api/health — Docker 健康检查用（2026-11-13）。"""
    return web.json_response({"ok": True})


async def main():
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/api/health", _health)
    app.router.add_get("/api/services", _list_handler)
    app.router.add_post("/api/services/{name}/{action}", _action_handler)

    stop = install_stop_handler("control", _log)   # 先装再开端口，见 mover/main.py 同处说明
    runner = web.AppRunner(app)
    await runner.setup()
    # 容器里必须绑 0.0.0.0，同一个 compose 网络里的 dashboard / 下载器才连得上；
    # compose 里不映射端口，所以宿主机和局域网都访问不到它
    await web.TCPSite(runner, "0.0.0.0", config.CONTROL_PORT).start()
    _log.info(f"控制服务已启动：内部端口 {config.CONTROL_PORT}（Docker socket {docker_api.DOCKER_SOCK}）")

    heal = asyncio.create_task(autoheal.run(stop))
    try:
        await stop.wait()
    finally:
        heal.cancel()
        await runner.cleanup()
        _log.info("control 已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("control 收到 KeyboardInterrupt，正常退出")
