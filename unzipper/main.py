# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

from aiohttp import web

import config
import unzipper.manager
from unzipper.web.server import _build_unzipper_app
from unzipper.web.websocket import _broadcast_loop, _broadcast
from common.logger import get_logger
from common import run_state
import unzipper.state as _ustate
from common.shutdown import install_stop_handler

_log = get_logger("unzipper")


async def main():
    # 先装退出处理再开端口：端口一通就可能收到 SIGTERM（docker stop、测试），
    # 晚装的话那一瞬间会被默认行为直接杀掉，收尾代码不跑（2026-11-14 CI 撞到）
    stop = install_stop_handler("unzipper", _log)
    app    = _build_unzipper_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, config.LISTEN_HOST, config.UNZIPPER_PORT).start()
    _log.info(f"Unzipper Web 已启动：http://localhost:{config.UNZIPPER_PORT}")

    asyncio.create_task(_broadcast_loop())
    unzipper.manager.set_broadcast_callback(_broadcast)
    # 恢复关机前的暂停开关（出厂默认：运行），必须在 start() 起 watcher 之前
    _ustate.paused = run_state.restore("unzipper", "paused", False)
    _log.info(f"启动状态（RESTART_MODE={config.RESTART_MODE}）：解压{'暂停' if _ustate.paused else '运行'}")

    await unzipper.manager.start()

    # 收到 SIGTERM / SIGINT 就退出；以前这里永远等不到，docker stop 只能干等 10 秒后硬杀
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
        _log.info("unzipper 已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("unzipper 收到 KeyboardInterrupt，正常退出")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log.error(f"unzipper 异常退出: {e}\n{tb}")
        from common.crash_notify import notify_crash_sync
        notify_crash_sync("unzipper", f"{e}\n{tb[:1500]}")
        raise
