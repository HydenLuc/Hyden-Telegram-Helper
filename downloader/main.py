# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
from datetime import datetime, timezone

from aiohttp import web

import config
from downloader import state
from downloader import storage
from downloader.tg.client import client, start_client
import downloader.tg.handlers  # registers @client.on event handlers at import time
from downloader.web.server import _build_web_app
from downloader.web.websocket import _broadcast_loop
from downloader.extract_status import refresh_loop as _extract_status_loop
from downloader.disk_monitor import disk_check_loop as _disk_check_loop
from downloader.toast_manager import toast_monitor_loop as _toast_monitor_loop
from downloader.history.runner import cleanup_loop as _history_cleanup_loop
from common.logger import get_logger

_log = get_logger("downloader")


async def main():
    state._conn_gate = asyncio.Condition()

    # P1-5b: 加载持久化未完成任务与媒体组状态
    state.pending_tasks = storage.load_pending_tasks()
    state.grouped_state = storage.load_grouped_state()
    state.duplicate_queue = storage.load_duplicate_queue()
    state.content_index = storage.load_content_index()
    state.history_jobs = storage.load_history_jobs()
    if state.pending_tasks:
        _log.info(f"[downloader] 加载 {len(state.pending_tasks)} 个未完成任务（待恢复扫描）")
    if state.grouped_state:
        _log.info(f"[downloader] 加载 {len(state.grouped_state)} 个媒体组状态")
    if state.duplicate_queue:
        _log.info(f"[downloader] 加载 {len(state.duplicate_queue)} 条待确认重复下载")
    if state.content_index["md5"] or state.content_index["fuid"]:
        _log.info(f"[downloader] 加载 content_index：{len(state.content_index['md5'])} md5 / {len(state.content_index['fuid'])} fuid")
    if state.history_jobs:
        _log.info(f"[downloader] 加载 {len(state.history_jobs)} 个历史下载 job（running→paused 已自动恢复）")

    app    = _build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, config.LISTEN_HOST, config.WEB_PORT).start()
    _log.info(f"Web 监控已启动：http://localhost:{config.WEB_PORT}")

    t = asyncio.create_task(_broadcast_loop())
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)

    # P1-8 Phase 2: 周期同步 extract_status（mover + unzipper）
    t2 = asyncio.create_task(_extract_status_loop())
    state._pending_tasks.add(t2)
    t2.add_done_callback(state._pending_tasks.discard)

    # 磁盘空间监测（每 60s 刷新 state.disk_usage + 阈值告警）
    t3 = asyncio.create_task(_disk_check_loop())
    state._pending_tasks.add(t3)
    t3.add_done_callback(state._pending_tasks.discard)

    # MD5 dedup: toast 超时监测（每 1s 扫 pending_toasts）
    t4 = asyncio.create_task(_toast_monitor_loop())
    state._pending_tasks.add(t4)
    t4.add_done_callback(state._pending_tasks.discard)

    # 历史 job 自动清理（每 1h 跑一次）
    t5 = asyncio.create_task(_history_cleanup_loop())
    state._pending_tasks.add(t5)
    t5.add_done_callback(state._pending_tasks.discard)

    # ⚠️ 必须在 client.start() **之前**：start 一返回就开始派发更新，
    #    而 handle_media 读 bot_start_time；还是 None 的话 `date < None` 抛 TypeError，
    #    处理器崩掉 → 那条消息被静默丢掉。同 bot.py，详见那边的注释。
    state.bot_start_time = datetime.now(timezone.utc)

    await start_client()
    me = await client.get_me()
    _log.info(f"Userbot 已启动：{me.first_name} (@{me.username})")
    print(f"┌─ 自适应并发配置 ─────────────────────────────────────────")
    print(f"│  全局最大连接数   MAX_TOTAL_CONNECTIONS = {state.MAX_TOTAL_CONNECTIONS}")
    print(f"│  分块策略         <50MB=1连接，50-500MB=2，500MB-2GB=4，>2GB=6")
    print(f"│  分块请求大小     CHUNK_SIZE            = {state.CHUNK_SIZE // 1024} KB ({state.CHUNK_SIZE} B)")
    print(f"│  无进度超时       DOWNLOAD_TIMEOUT      = {config.DOWNLOAD_TIMEOUT}s")
    print(f"│  FloodWait 重试   FLOOD_RETRY_MAX       = {config.FLOOD_RETRY_MAX} 次（指数退避 5/10/20s）")
    print(f"└──────────────────────────────────────────────────────────")
    _log.info(f"监听 {len(state.watched)} 个聊天 | 命令：监听 / 取消监听 / 监听列表 / 搜索 / ID")

    # P1-5b: 启动恢复扫描（必须在 client.start 之后，需要 get_messages 重取 file_reference）
    from downloader.download.manager import recover_pending_tasks
    await recover_pending_tasks()

    try:
        await client.run_until_disconnected()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("downloader 收到 KeyboardInterrupt，正常退出")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log.error(f"downloader 异常退出: {e}\n{tb}")
        from common.crash_notify import notify_crash_sync
        notify_crash_sync("downloader", f"{e}\n{tb[:1500]}")
        raise
