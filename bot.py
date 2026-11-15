# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

import config
from downloader import state
from downloader import storage
from downloader.tg.client import client, start_client
import downloader.tg.handlers  # registers @client.on event handlers at import time
from downloader.web.server import _build_web_app
from downloader.web.websocket import _broadcast_loop
from downloader.disk_monitor import disk_check_loop as _disk_check_loop
from downloader.toast_manager import toast_monitor_loop as _toast_monitor_loop
from downloader.extract_status import refresh_loop as _extract_status_loop
from downloader.history.runner import cleanup_loop as _history_cleanup_loop
from common.logger import get_logger
from common import run_state

_log = get_logger("bot")


async def main():
    state._conn_gate = asyncio.Condition()

    # P1-5b: 加载持久化未完成任务与媒体组状态
    state.pending_tasks = storage.load_pending_tasks()
    state.grouped_state = storage.load_grouped_state()
    state.duplicate_queue = storage.load_duplicate_queue()
    state.content_index = storage.load_content_index()
    state.history_jobs = storage.load_history_jobs()
    if state.pending_tasks:
        print(f"[downloader] 加载 {len(state.pending_tasks)} 个未完成任务（待恢复扫描）")
    if state.grouped_state:
        print(f"[downloader] 加载 {len(state.grouped_state)} 个媒体组状态")
    if state.duplicate_queue:
        print(f"[downloader] 加载 {len(state.duplicate_queue)} 条待确认重复下载")
    if state.content_index["md5"] or state.content_index["fuid"]:
        print(f"[downloader] 加载 content_index：{len(state.content_index['md5'])} md5 / {len(state.content_index['fuid'])} fuid")
    if state.history_jobs:
        print(f"[downloader] 加载 {len(state.history_jobs)} 个历史下载 job（running→paused 已自动恢复）")

    app    = _build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, config.LISTEN_HOST, config.WEB_PORT).start()
    print(f"Web 监控已启动：http://localhost:{config.WEB_PORT}")

    t = asyncio.create_task(_broadcast_loop())
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)

    # 磁盘空间监测（每 60s 刷新 state.disk_usage + 阈值告警）
    t_disk = asyncio.create_task(_disk_check_loop())
    state._pending_tasks.add(t_disk)
    t_disk.add_done_callback(state._pending_tasks.discard)

    # MD5 dedup: toast 超时监测（每 1s 扫 pending_toasts）
    t_toast = asyncio.create_task(_toast_monitor_loop())
    state._pending_tasks.add(t_toast)
    t_toast.add_done_callback(state._pending_tasks.discard)

    # P1-8 Phase 2: 解压状态周期同步（每 5s 查 mover/unzipper 刷新 completed_downloads）
    t_extract = asyncio.create_task(_extract_status_loop())
    state._pending_tasks.add(t_extract)
    t_extract.add_done_callback(state._pending_tasks.discard)

    # 历史 job 自动清理（每 1h 跑一次；删除 done/error/cancelled 且超 HISTORY_JOB_KEEP_DAYS 天的）
    t_hcleanup = asyncio.create_task(_history_cleanup_loop())
    state._pending_tasks.add(t_hcleanup)
    t_hcleanup.add_done_callback(state._pending_tasks.discard)

    # ⚠️ 下面三行必须在 client.start() **之前**，别挪到后面。
    #    client.start() 一返回 Telethon 就开始派发更新（包括离线期间的积压），
    #    而 handle_media 会读 bot_start_time 和这两个暂停开关。写在后面有窗口：
    #      · bot_start_time 还是 None → `date < None` 抛 TypeError
    #        → 处理器崩掉 → **那条消息被静默丢掉**（2026-08-19 实际发生过一次）
    #      · 两个暂停开关还是 False → 积压媒体会被真的开下，
    #        「启动默认全部暂停」的保证就是个空话（正是 2026-08-06 队列涨到 1800+ 的成因）
    #    窗口不小：原来这两处之间还夹着一次 `await client.get_me()` 网络往返。
    #
    # 两个暂停开关：2026-11-13 起默认「恢复成关机前的样子」（hyden 要求：断电 / 重开程序
    # 都回到上次的运行状态），见 common/run_state.py。
    # 出厂默认仍是两个都暂停：第一次装好、或 RESTART_MODE=PAUSED 时用它。
    # 两个都要管：只管全局的话例外频道会在重启后立刻开下（2026-08-06 队列涨到 1800+）。
    state.bot_start_time = datetime.now(timezone.utc)
    state.monitoring_paused = run_state.restore("downloader", "monitoring_paused", True)
    state.exempt_paused = run_state.restore("downloader", "exempt_paused", True)
    # 收藏开关是持久化的：沿用上次的选择；设置里没有就按暂停（2026-11-10）
    state.saved_paused = bool(storage.load_settings().get("saved_paused", True))

    await start_client()   # 有终端在终端输验证码，没终端（后台 / Docker）在网页输
    me = await client.get_me()
    state.account_name = (me.first_name or me.username or "").strip()
    print(f"Userbot 已启动：{me.first_name} (@{me.username})")
    print(f"┌─ 自适应并发配置 ─────────────────────────────────────────")
    print(f"│  全局最大连接数   MAX_TOTAL_CONNECTIONS = {state.MAX_TOTAL_CONNECTIONS}")
    print(f"│  分块策略         <50MB=1连接，50-500MB=2，500MB-2GB=4，>2GB=6")
    print(f"│  分块请求大小     CHUNK_SIZE            = {state.CHUNK_SIZE // 1024} KB ({state.CHUNK_SIZE} B)")
    print(f"│  无进度超时       DOWNLOAD_TIMEOUT      = {config.DOWNLOAD_TIMEOUT}s")
    print(f"│  FloodWait 重试   FLOOD_RETRY_MAX       = {config.FLOOD_RETRY_MAX} 次（指数退避 5/10/20s）")
    print(f"└──────────────────────────────────────────────────────────")
    print(f"监听 {len(state.watched)} 个聊天 | 命令：监听 / 取消监听 / 监听列表 / 搜索 / ID")

    _on = lambda paused: "暂停" if paused else "运行"
    _log.info(f"启动状态（RESTART_MODE={config.RESTART_MODE}）：全局监听{_on(state.monitoring_paused)}、"
              f"例外频道{_on(state.exempt_paused)}、收藏{_on(state.saved_paused)}")

    # ⚠️ 2026-08-12 起 unzipper 不再在这里启动——它已拆成独立容器（`python -m unzipper.main`）。
    # 原因：合并只是图省事（unzipper 不依赖 downloader/telethon），但共享事件循环意味着
    # 下载忙时解压和 dashboard 一起被拖慢，且改任何一处都要停全部。

    # P1-5b: 启动恢复扫描（必须在 client.start 之后，需要 get_messages 重取 file_reference）
    # 不受 monitoring_paused 影响；fire-and-forget 后台跑，避免阻塞主流程（曾是 await，
    # 实测 ~1000 个 hist 任务串行 get_messages 耗时数分钟，期间 unzipper 无法上线）
    from downloader.download.manager import recover_pending_tasks, stalled_retry_loop
    t_recover = asyncio.create_task(recover_pending_tasks())
    # 搁置任务的周期性重试。⚠️ 没有它，恢复扫描跑完还失败的任务就永远没人管了
    # ——2026-09-17 之前 11 个大文件任务因此在队列里躺了一个多月。
    t_stalled = asyncio.create_task(stalled_retry_loop())
    state._pending_tasks.add(t_stalled)
    t_stalled.add_done_callback(state._pending_tasks.discard)
    state._pending_tasks.add(t_recover)
    t_recover.add_done_callback(state._pending_tasks.discard)

    # 收到 SIGTERM/SIGINT 时把合并写里没落盘的状态刷出去再退。
    # ⚠️ 2026-08-13 停机时实测容器是 exit 137（SIGKILL）——原来根本没有信号处理器，
    #    docker compose stop 的宽限期白等，最后靠 SIGKILL 收场。
    _stopping = asyncio.Event()

    def _on_signal(sig):
        _log.info(f"收到 {sig.name}，落盘未保存状态后退出")
        _stopping.set()

    loop = asyncio.get_running_loop()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(_sig, _on_signal, _sig)
        except (NotImplementedError, RuntimeError):
            pass    # Windows / 非主线程：退化成原来的行为

    try:
        await asyncio.wait(
            [asyncio.create_task(client.run_until_disconnected()),
             asyncio.create_task(_stopping.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        try:
            await asyncio.wait_for(storage.flush_now(), timeout=30)
        except Exception as e:
            _log.error(f"退出前落盘失败: {e}")
            storage.flush_now_sync()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("bot 收到 KeyboardInterrupt，正常退出")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log.error(f"bot 异常退出: {e}\n{tb}")
        # bot 进程持有 Telethon client，但崩溃后已无 event loop 复用；
        # 走 Bot API（若 .env 配 BOT_TOKEN）或 sync fallback。
        from common.crash_notify import notify_crash_sync
        notify_crash_sync("bot", f"{e}\n{tb[:1500]}")
        raise
