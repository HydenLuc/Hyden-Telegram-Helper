# SPDX-License-Identifier: AGPL-3.0-or-later
"""跟 Docker Engine 说话 + 决定哪些容器能碰。

## 为什么单独一个服务（hyden 2026-11-11 定）

dashboard 的「服务启停」要能启停容器，就得有 Docker 的管理接口（docker.sock）。
可是**拿到 docker.sock 等于拿到这台机器的 root 权限**，而 dashboard 没有登录验证。
所以把这份权限关进一个只做三件事的小服务里：

  · 只认**本项目**的容器（跟自己同一个 compose 项目，按 compose 自动打的标签判断）
  · 只认 downloader / mover / unzipper / dashboard 四个服务名
  · 只做 查看 / 启动 / 停止 / 重启；dashboard 只能看不能动（它就是网页本身）

就算 dashboard 被人乱点，最多也只是把这几个容器停了，碰不到别的容器、也建不了新容器。
这个服务不映射任何端口，只在 compose 内部网络里给 dashboard 和下载器调。

只做 Docker 版：原生部署（start.sh / systemd）没有这个服务，面板直接隐藏。
"""
from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib.parse import quote

import aiohttp

DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")

# 面板上显示的服务（顺序就是显示顺序）
VISIBLE = ("downloader", "mover", "unzipper", "dashboard")
# 能启停的服务。dashboard 不在里面：停了网页立刻没了，用户会一头雾水
CONTROLLABLE = frozenset({"downloader", "mover", "unzipper"})
ACTIONS = frozenset({"start", "stop", "restart"})

LABEL_PROJECT = "com.docker.compose.project"
LABEL_SERVICE = "com.docker.compose.service"

# 停容器给多少秒宽限（够下载器把没落盘的状态写完）
STOP_TIMEOUT_S = 20


class DockerError(Exception):
    pass


async def docker_call(method: str, path: str, *, timeout: float = 40) -> tuple[int, Any]:
    """通过 unix socket 调 Docker Engine API。返回 (HTTP 状态码, JSON 或文本)。"""
    conn = aiohttp.UnixConnector(path=DOCKER_SOCK)
    try:
        async with aiohttp.ClientSession(connector=conn) as s:
            async with s.request(method, f"http://docker{path}",
                                 timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                text = await r.text()
                try:
                    return r.status, json.loads(text) if text else None
                except ValueError:
                    return r.status, text
    except (aiohttp.ClientError, OSError) as e:
        raise DockerError(f"连不上 Docker（{DOCKER_SOCK}）：{e}") from e


_project_cache: str | None = None


async def own_project() -> str:
    """本服务所在的 compose 项目名。容器的 hostname 默认就是容器 ID，拿它查自己。"""
    global _project_cache
    if _project_cache:
        return _project_cache
    status, data = await docker_call("GET", f"/containers/{socket.gethostname()}/json")
    if status != 200 or not isinstance(data, dict):
        raise DockerError(f"查不到自己所在的容器（HTTP {status}）")
    project = (data.get("Config", {}).get("Labels") or {}).get(LABEL_PROJECT)
    if not project:
        raise DockerError("自己的容器上没有 compose 项目标签，不知道该管哪些容器")
    _project_cache = project
    return project


def summarize(containers: list[dict], project: str) -> list[dict]:
    """把 Docker 返回的容器列表，筛成面板要的样子。只留本项目、只留 VISIBLE 里的服务。

    纯函数，方便测试：「别的项目的容器绝不能出现」就靠这里。
    """
    by_service: dict[str, dict] = {}
    for c in containers:
        labels = c.get("Labels") or {}
        if labels.get(LABEL_PROJECT) != project:
            continue
        svc = labels.get(LABEL_SERVICE)
        if svc not in VISIBLE:
            continue
        by_service[svc] = c

    out = []
    for svc in VISIBLE:
        c = by_service.get(svc)
        if c is None:
            out.append({"name": svc, "state": "missing", "status_text": "容器不存在",
                        "controllable": False, "container_id": None})
            continue
        raw = c.get("State", "")
        state = "running" if raw == "running" else ("starting" if raw == "restarting" else "stopped")
        out.append({
            "name": svc,
            "state": state,
            "status_text": c.get("Status", ""),
            "controllable": svc in CONTROLLABLE,
            "container_id": c.get("Id"),
        })
    return out


async def list_services() -> list[dict]:
    project = await own_project()
    filters = json.dumps({"label": [f"{LABEL_PROJECT}={project}"]})
    status, data = await docker_call("GET", f"/containers/json?all=1&filters={quote(filters, safe='')}")
    if status != 200 or not isinstance(data, list):
        raise DockerError(f"列容器失败（HTTP {status}）")
    return summarize(data, project)


def check_action(name: str, action: str) -> str | None:
    """校验能不能做。返回 None = 可以；否则返回拒绝原因。"""
    if action not in ACTIONS:
        return f"不支持的操作：{action}"
    if name not in VISIBLE:
        return f"未知服务：{name}"
    if name not in CONTROLLABLE:
        return f"{name} 不允许通过网页控制（它就是网页本身）"
    return None


async def do_action(name: str, action: str) -> dict:
    why = check_action(name, action)
    if why:
        return {"ok": False, "message": why, "http": 403 if "不允许" in why else 400}
    services = {s["name"]: s for s in await list_services()}
    target = services.get(name)
    if not target or not target["container_id"]:
        return {"ok": False, "message": f"{name} 的容器不存在", "http": 404}
    query = f"?t={STOP_TIMEOUT_S}" if action in ("stop", "restart") else ""
    status, data = await docker_call("POST", f"/containers/{target['container_id']}/{action}{query}",
                                     timeout=STOP_TIMEOUT_S + 20)
    # 204 = 成功；304 = 本来就是那个状态（已经在跑 / 已经停了），也算成功
    if status in (204, 304):
        word = {"start": "已启动", "stop": "已停止", "restart": "已重启"}[action]
        note = "（本来就是这个状态）" if status == 304 else ""
        return {"ok": True, "message": f"{name} {word}{note}", "http": 200}
    detail = data.get("message") if isinstance(data, dict) else data
    return {"ok": False, "message": f"Docker 拒绝了：{detail}", "http": 502}
