# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

from aiohttp import web

import config
import mover.state as state
from mover.manager import start
from mover.web.server import _build_mover_app
from mover.web.websocket import _broadcast_loop, _broadcast
from common.logger import get_logger
from common import run_state
from common.shutdown import install_stop_handler

_log = get_logger("mover")


async def main():
    state.set_broadcast_callback(_broadcast)
    # 恢复关机前的暂停开关（出厂默认：运行），必须在 start() 派发 pending 之前
    state.paused = run_state.restore("mover", "paused", False)
    _log.info(f"启动状态（RESTART_MODE={config.RESTART_MODE}）：搬运{'暂停' if state.paused else '运行'}")

    # 先装退出处理再开端口：端口一通就可能收到 SIGTERM（docker stop、测试），
    # 晚装的话那一瞬间会被默认行为直接杀掉，收尾代码不跑（2026-11-14 CI 撞到）
    stop = install_stop_handler("mover", _log)
    app = _build_mover_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, config.LISTEN_HOST, config.MOVER_PORT).start()
    _log.info(f"Mover Web 已启动：http://localhost:{config.MOVER_PORT}")
    asyncio.create_task(_broadcast_loop())
    await start()
    # 收到 SIGTERM / SIGINT 就退出；以前这里永远等不到，docker stop 只能干等 10 秒后硬杀
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
        _log.info("mover 已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("mover 收到 KeyboardInterrupt，正常退出")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log.error(f"mover 异常退出: {e}\n{tb}")
        from common.crash_notify import notify_crash_sync
        notify_crash_sync("mover", f"{e}\n{tb[:1500]}")
        raise
