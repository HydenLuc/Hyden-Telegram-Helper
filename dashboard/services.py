# SPDX-License-Identifier: AGPL-3.0-or-later
"""dashboard「服务启停」面板的后端：转给控制服务（只做 Docker 版）。

## 历史

2026-09-28 第一版是 macOS launchctl 封装，只在作者自己的 Mac 上能用（plist 名字写死）。
2026-11-10 改用 Docker 部署后，面板一直显示「未知」、点了没反应。
2026-11-11 hyden 定：**依赖 Docker 的功能只做 Docker 版**，原生部署隐藏这个面板。

## 现在

  · Docker：dashboard 自己不碰 docker.sock，转给同一个 compose 里的 control 服务
    （权限为什么要关在那里，见 control/docker_api.py 开头）
  · 原生部署：返回 supported=False，前端把整张卡片藏起来。
    原生部署启停用 ./start.sh / ./stop.sh 或 systemd。
"""
from __future__ import annotations

import config
from common import control_client
from common.control_client import NATIVE_REASON


async def list_services() -> tuple[int, dict]:
    """返回 (HTTP 状态码, 给前端的 JSON)。"""
    if not config.IS_DOCKER:
        return 200, {"supported": False, "reason": NATIVE_REASON, "services": []}
    status, body = await control_client.call("GET", "/api/services", timeout=15)
    body["supported"] = True
    return status, body


async def act(name: str, action: str) -> tuple[int, dict]:
    if not config.IS_DOCKER:
        return 501, {"ok": False, "message": NATIVE_REASON}
    return await control_client.call("POST", f"/api/services/{name}/{action}", timeout=60)
