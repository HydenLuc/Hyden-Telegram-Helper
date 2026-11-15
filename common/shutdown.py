# SPDX-License-Identifier: AGPL-3.0-or-later
"""收到退出信号（SIGTERM / SIGINT）时让主循环优雅退出。

## 为什么需要（2026-11-11）

在 Docker 里 Python 是容器的 1 号进程。Linux 对 1 号进程有个特殊规则：
**没有专门装处理器的信号会被直接忽略**——默认的「收到 SIGTERM 就退出」对它不生效。
以前只有 bot.py 装了处理器，mover / unzipper / dashboard 都没有，于是 `docker stop`
发出 SIGTERM 后它们毫无反应，干等 10 秒宽限期，最后被 SIGKILL 硬杀，
`finally` 里的收尾（关 Web 服务、落盘）一行都没执行。

compose 里另加了 `init: true`（容器里由 tini 当 1 号进程转发信号）作为第二层保险；
但不能只靠它——原生部署（start.sh / systemd）和别人自己写的 compose 都没有这一层。

## 用法

    stop = install_stop_handler("mover", log)
    ...                      # 启动服务
    try:
        await stop.wait()    # 代替以前的 asyncio.Event().wait()（永远等不到）
    finally:
        await runner.cleanup()

Windows 的默认事件循环（Proactor）不支持 add_signal_handler，会退回 Python 默认行为：
Ctrl+C 照样抛 KeyboardInterrupt、各模块的 `except KeyboardInterrupt` 照样接得住。
"""
from __future__ import annotations

import asyncio
import signal


def install_stop_handler(name: str, log) -> asyncio.Event:
    """在当前运行中的事件循环上装 SIGTERM / SIGINT 处理器，返回一个「该退出了」事件。

    必须在 async 函数里调（要拿到正在运行的事件循环）。
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal(sig: signal.Signals) -> None:
        if stop.is_set():
            return
        log.info(f"{name} 收到 {sig.name}，开始退出")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except (NotImplementedError, RuntimeError):
            # Windows Proactor 循环 / 不在主线程：退回默认行为（见模块注释）
            pass
    return stop
