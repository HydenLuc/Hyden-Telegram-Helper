# SPDX-License-Identifier: AGPL-3.0-or-later
"""Docker 部署：容器「活着但不健康」时自动重启（2026-11-13，hyden 定：交给 control 服务做）。

为什么需要：Docker 的 `restart: unless-stopped` 只管进程退出；进程卡死但没退出时，
healthcheck 会把容器标成 unhealthy，可 Docker **自己不会重启它**（compose 没有这个选项）。
2026-08-18 作者的 Mac 上就出过：四个服务全在跑、端口全在听，下载器卡死一个字节都下不动。

以前这件事靠宿主机上另写的 systemd timer 脚本，只有作者自己的服务器有。放进 control 之后，任何人 `docker compose up` 都自带这层保护。

规则：
  · 只看**本项目**、VISIBLE 里的四个服务（跟启停面板同一套筛选，碰不到别的容器）
  · 只处理 Docker 判成 unhealthy 的：healthcheck 连续失败 retries 次（默认 3 分钟）才会到这一步，
    启动宽限期 start_period 内也不会被判 unhealthy —— 防抖交给 Docker
  · 被人停掉的容器不是 running，Docker 不给它判健康，这里自然不会去拉起来
  · 同一个服务重启后 COOLDOWN_S 内不再动它；一小时内超过 MAX_PER_HOUR 次就停手，
    记错误 + 发通知：重启治不好的毛病，越重启越糟（比如反复中断下载）
  · AUTOHEAL=false 可以整个关掉
"""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import quote

import config
from common.logger import get_logger
from control import docker_api as d

_log = get_logger("control")

COOLDOWN_S = 600
MAX_PER_HOUR = 3
WINDOW_S = 3600


class Healer:
    """记每个服务的自动重启时间，决定这次能不能重启。纯逻辑，方便测试。"""

    def __init__(self, cooldown_s: float = COOLDOWN_S, max_per_hour: int = MAX_PER_HOUR):
        self.cooldown_s = cooldown_s
        self.max_per_hour = max_per_hour
        self.history: dict[str, list[float]] = {}
        self.gave_up: set[str] = set()

    def decide(self, name: str, now: float) -> tuple[bool, str]:
        recent = [t for t in self.history.get(name, []) if now - t < WINDOW_S]
        self.history[name] = recent
        if recent and now - recent[-1] < self.cooldown_s:
            return False, "cooldown"
        if len(recent) >= self.max_per_hour:
            return False, "too_many"
        return True, ""

    def record(self, name: str, now: float) -> None:
        self.history.setdefault(name, []).append(now)
        self.gave_up.discard(name)

    def recovered(self, name: str) -> None:
        """服务恢复健康：下次再出问题时，「已放弃」的通知可以重新发。"""
        self.gave_up.discard(name)


async def find_unhealthy() -> list[tuple[str, str]]:
    """本项目里 Docker 标成 unhealthy 的服务 → [(服务名, 容器 ID)]。"""
    project = await d.own_project()
    filters = json.dumps({"label": [f"{d.LABEL_PROJECT}={project}"], "health": ["unhealthy"]})
    status, data = await d.docker_call("GET", f"/containers/json?filters={quote(filters, safe='')}")
    if status != 200 or not isinstance(data, list):
        raise d.DockerError(f"查容器健康状态失败（HTTP {status}）")
    out = []
    for c in data:
        labels = c.get("Labels") or {}
        svc = labels.get(d.LABEL_SERVICE)
        if labels.get(d.LABEL_PROJECT) == project and svc in d.VISIBLE and c.get("Id"):
            out.append((svc, c["Id"]))
    return out


async def _notify(text: str) -> None:
    try:
        from common.crash_notify import notify_crash
        await notify_crash("control", text)
    except Exception as e:          # 通知是可选的，失败不影响自动重启
        _log.warning(f"[autoheal] 发通知失败：{e}")


async def heal_once(healer: Healer, now: float | None = None) -> list[str]:
    """查一轮、该重启的重启。返回这轮重启了哪些服务。"""
    now = time.monotonic() if now is None else now
    unhealthy = await find_unhealthy()
    bad = {svc for svc, _ in unhealthy}
    for name in list(healer.gave_up):
        if name not in bad:
            healer.recovered(name)

    restarted = []
    for svc, cid in unhealthy:
        ok, why = healer.decide(svc, now)
        if not ok:
            if why == "too_many" and svc not in healer.gave_up:
                healer.gave_up.add(svc)
                msg = (f"{svc} 一小时内已自动重启 {healer.max_per_hour} 次仍不健康，停止自动重启，"
                       f"需要人看一下（docker logs tghelper-{svc}）")
                _log.error(f"[autoheal] {msg}")
                await _notify(msg)
            continue
        status, data = await d.docker_call("POST", f"/containers/{cid}/restart?t={d.STOP_TIMEOUT_S}",
                                           timeout=d.STOP_TIMEOUT_S + 20)
        healer.record(svc, now)
        if status in (204, 304):
            _log.warning(f"[autoheal] {svc} 健康检查连续失败，已自动重启")
            await _notify(f"{svc} 健康检查连续失败（进程活着但没响应），已自动重启")
            restarted.append(svc)
        else:
            detail = data.get("message") if isinstance(data, dict) else data
            _log.error(f"[autoheal] 重启 {svc} 失败：HTTP {status} {detail}")
    return restarted


async def run(stop: asyncio.Event) -> None:
    if not config.AUTOHEAL:
        _log.info("[autoheal] 已关闭（AUTOHEAL=false），不健康的容器不会被自动重启")
        return
    interval = max(15, config.AUTOHEAL_INTERVAL)
    _log.info(f"[autoheal] 已开启：每 {interval} 秒检查一次，不健康的容器自动重启")
    healer = Healer()
    while not stop.is_set():
        try:
            await heal_once(healer)
        except d.DockerError as e:
            _log.error(f"[autoheal] {e}")
        except Exception:
            _log.exception("[autoheal] 检查出错")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
