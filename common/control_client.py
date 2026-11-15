# SPDX-License-Identifier: AGPL-3.0-or-later
"""调 control 服务（只在 Docker 部署里有，负责启停本项目容器；见 control/docker_api.py）。

dashboard 的「服务启停」面板和下载器页的「⏹ 停止」按钮都走这里。
"""
from __future__ import annotations

import aiohttp

import config

NATIVE_REASON = "原生部署不支持网页启停，请用 ./start.sh / ./stop.sh（或 systemd）"


async def call(method: str, path: str, timeout: float = 30) -> tuple[int, dict]:
    """返回 (HTTP 状态码, JSON dict)。连不上时返回 503 + 原因，不抛异常。"""
    url = f"http://{config.CONTROL_HOST}:{config.CONTROL_PORT}{path}"
    headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
    try:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                try:
                    body = await r.json(content_type=None)
                except Exception:  # noqa: BLE001
                    body = {"ok": False, "message": (await r.text())[:300]}
                if not isinstance(body, dict):
                    body = {"ok": False, "message": str(body)}
                return r.status, body
    except (aiohttp.ClientError, OSError, TimeoutError) as e:
        return 503, {"ok": False,
                     "message": f"连不上控制服务（{config.CONTROL_HOST}:{config.CONTROL_PORT}）：{e}"}
