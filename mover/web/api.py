# SPDX-License-Identifier: AGPL-3.0-or-later
"""API handlers."""
import asyncio
import json
import os
from pathlib import Path

from aiohttp import web

import config
from common.open_folder import open_in_file_manager
import mover.state as state
from mover.manager import (
    clear_tasks,
    delete_task,
    get_task,
    list_tasks,
    pause as pause_mover,
    resume as resume_mover,
    retry as retry_task,
    submit,
)
from mover.web.templates import MOVER_HTML


def _json(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        status=status,
    )


async def _index_handler(request: web.Request) -> web.Response:
    html = MOVER_HTML.replace("__API_KEY__", config.API_KEY)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


_TARGET_BLACKLIST = (
    Path("/etc"), Path("/bin"), Path("/sbin"), Path("/usr"),
    Path("/sys"), Path("/proc"), Path("/dev"), Path("/boot"),
    Path("/lib"), Path("/lib64"), Path("/root"),
    # /var 2026-09-17 补：跟上面几个同类的系统目录，原来漏了。
    # 没有任何正当理由把媒体搬进 /var（staging 目录是建在 target 里面的，不碰这儿）。
    Path("/var"),
    # macOS 上 /etc、/var 的真身。写死进来，黑名单就不依赖「刚好跑在 macOS 上」：
    # 在 Linux 上它们不存在，resolve 不会把 /private/etc 映射回 /etc（2026-11-10 迁到 Linux 时补）。
    Path("/private/etc"), Path("/private/var"),
)


def _resolve_safe(p: Path) -> Path:
    """resolve 但不因为路径不存在/权限问题而抛异常。"""
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return p


# 黑名单的 resolve 版本。⚠️ 必须预先算好：**两边都要 resolve 才能比**。
# 2026-09-17 查明的真漏洞：原来只 resolve 目标、不 resolve 黑名单，而 macOS 上
# /etc → private/etc、/var → private/var、/tmp → private/tmp 都是软链，
# 于是 `/etc/dst` resolve 成 `/private/etc/dst`，跟黑名单里的 `/etc` 比不上 → **放行**。
# 所以在 macOS 上**这条黑名单从来没生效过**。
# 症状是 tests/integration/test_mover_api.py::test_blacklist_etc 长期红着 ——
# 那个「已知失败」一直在报一个真问题，只是被当成环境噪音了。
_TARGET_BLACKLIST_RESOLVED = tuple(_resolve_safe(p) for p in _TARGET_BLACKLIST)


def _is_blacklisted(p: Path) -> bool:
    # 原样和 resolve 后的都比一遍：前者挡「直接写 /etc/x」，
    # 后者挡「用软链或 ../ 绕进去」。
    candidates = {p, _resolve_safe(p)}
    for forbidden in set(_TARGET_BLACKLIST) | set(_TARGET_BLACKLIST_RESOLVED):
        for c in candidates:
            try:
                c.relative_to(forbidden)
                return True
            except ValueError:
                continue
    return False


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _target_allowed_roots() -> list[Path]:
    """搬运目标只能落在这些目录之下（2026-11-13 起白名单，开源准备）。

    以前只靠上面的系统目录黑名单：Windows（C:\\Windows）、macOS（/System、/Library）、
    Docker 里的 /state、/app 都没挡到，挡不全。现在先过白名单，黑名单留着当第二道。
    · 设了 DATA_ROOT：整个数据根都行（download / move / unzip 都在它下面）
    · 三个工作目录本身
    · MOVE_ALLOWED_ROOTS：要搬到别处的，自己在 .env 里加（逗号分隔的绝对路径）
    """
    roots = [config.DOWNLOAD_DIR, config.WATCH_PATH, config.OUTPUT_PATH]
    if config.DATA_ROOT:
        roots.append(Path(config.DATA_ROOT))
    for raw in os.getenv("MOVE_ALLOWED_ROOTS", "").split(","):
        if raw.strip() and Path(raw.strip()).is_absolute():
            roots.append(Path(raw.strip()))
    return [r for r in roots if r]


def _target_in_allowed_roots(target: Path) -> bool:
    return any(_is_under(target, r) for r in _target_allowed_roots())


def _source_in_allowed_roots(source: Path) -> bool:
    """source 必须在 DOWNLOAD_DIR 或 WATCH_PATH 范围内（防止任意文件被删/搬）。"""
    return _is_under(source, config.DOWNLOAD_DIR) or _is_under(source, config.WATCH_PATH)


async def _api_move(request: web.Request) -> web.Response:
    """POST /api/move — 发起搬运任务（异步，立即返回 task_id）。

    P2-11: 幂等性检查先于 source 存在性校验（成功后 source 已删除，重试同 task_id 应返回 already_moved）。
    """
    try:
        body = await request.json()
    except Exception:
        return _json({"ok": False, "error": "invalid JSON"}, 400)

    source = (body.get("source") or "").strip()
    target = (body.get("target") or "").strip()
    task_id = (body.get("task_id") or "").strip()

    if not source or not target or not task_id:
        return _json({"ok": False, "error": "source, target, task_id are required"}, 400)

    # 幂等性：同 task_id 已 done → 直接返回 already_moved，无需 source 存在
    existing = state.tasks.get(task_id)
    if existing and existing.get("status") == "done":
        return _json({"ok": True, "already_moved": True, "target_path": existing["target"]})

    if not Path(source).is_absolute():
        return _json({"ok": False, "error": "source must be an absolute path"}, 400)
    if not Path(target).is_absolute():
        return _json({"ok": False, "error": "target must be an absolute path"}, 400)
    if _is_blacklisted(Path(target)):
        return _json({"ok": False, "error": "target path is in system blacklist"}, 403)
    if not _target_in_allowed_roots(Path(target)):
        return _json({"ok": False, "error": "target path not in allowed directories "
                      "(must be under DATA_ROOT / the three work dirs, or add it to MOVE_ALLOWED_ROOTS)"}, 403)
    if not Path(source).exists():
        return _json({"ok": False, "error": "source path does not exist"}, 404)
    if not _source_in_allowed_roots(Path(source)):
        return _json({"ok": False, "error": "source path not in allowed directories"}, 403)

    result = await submit(source, target, task_id)
    return _json(result)


async def _api_tasks_list(request: web.Request) -> web.Response:
    """GET /api/tasks — 查询任务列表，支持 status/limit/offset 过滤。"""
    status = request.rel_url.query.get("status") or None
    try:
        limit = min(int(request.rel_url.query.get("limit", 20)), 100)
        offset = int(request.rel_url.query.get("offset", 0))
    except ValueError:
        return _json({"ok": False, "error": "invalid limit or offset"}, 400)

    items, total = await list_tasks(status=status, limit=limit, offset=offset)
    return _json({"ok": True, "items": items, "total": total, "limit": limit, "offset": offset})


async def _api_tasks_get(request: web.Request) -> web.Response:
    """GET /api/tasks/{task_id} — 查询单个任务状态。"""
    task_id = request.match_info["task_id"]
    task = await get_task(task_id)
    if task is None:
        return _json({"ok": False, "error": "task not found"}, 404)
    return _json({"ok": True, **task})


async def _api_tasks_delete(request: web.Request) -> web.Response:
    """DELETE /api/tasks/{task_id} — 删除历史记录（不影响文件）。"""
    task_id = request.match_info["task_id"]
    deleted = await delete_task(task_id)
    if not deleted:
        return _json({"ok": False, "error": "task not found"}, 404)
    return _json({"ok": True})


async def _api_tasks_retry(request: web.Request) -> web.Response:
    """POST /api/tasks/{task_id}/retry — 重试失败任务。"""
    task_id = request.match_info["task_id"]
    result = await retry_task(task_id)
    if not result["ok"]:
        error = result["error"]
        if "not found" in error or "no longer exists" in error:
            return _json(result, 404)
        return _json(result, 400)
    return _json(result)


async def _api_tasks_clear(request: web.Request) -> web.Response:
    """POST /api/tasks/clear — 清空历史记录（不影响文件）。

    可选 JSON body {"statuses": ["done"]} / {"statuses": ["failed"]}；
    不传 body 保持旧行为（done + failed 全清）。
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    statuses = data.get("statuses") or ["done", "failed"]
    if not isinstance(statuses, list) or any(x not in ("done", "failed") for x in statuses):
        return _json({"ok": False, "error": "statuses must be a list of 'done'/'failed'"}, status=400)
    deleted = await clear_tasks(tuple(statuses))
    return _json({"ok": True, "deleted": deleted})


async def _api_health(request: web.Request) -> web.Response:
    """GET /api/health — 健康检查。"""
    tasks = list(state.tasks.values())
    running = sum(1 for t in tasks if t["status"] == "copying")
    queue_depth = sum(1 for t in tasks if t["status"] == "pending")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    return _json({
        "ok":            True,
        "status":        "busy" if running > 0 else "idle",
        "running_tasks": running,
        "queue_depth":   queue_depth,
        "total_tasks":   len(tasks),
        "failed_tasks":  failed,
        "mover_port":    config.MOVER_PORT,
        "max_concurrent": config.MOVER_MAX_CONCURRENT,
        "paused":        state.paused,
    })


async def _api_open(request: web.Request) -> web.Response:
    """POST /api/open — 打开本地目录（限制为当前活跃任务 target 的父目录）。"""
    try:
        body = await request.json()
    except Exception:
        return _json({"ok": False, "error": "invalid JSON"}, 400)

    target = (body.get("path") or "").strip()
    if not target:
        return _json({"ok": False, "error": "path required"}, 400)

    p = Path(target).resolve()
    # 集合点路径 = 活跃任务 target 的父目录（与 UI 中 target-list 显示的聚合一致）
    allowed = {Path(t["target"]).resolve().parent
               for t in state.tasks.values()
               if t.get("status") in ("pending", "copying") and t.get("target")}
    if p not in allowed:
        return _json({"ok": False, "error": "path not allowed"}, 403)
    if not p.exists():
        return _json({"ok": False, "error": "not found"}, 404)
    ok, why = open_in_file_manager(p)
    if not ok:
        return _json({"ok": False, "error": why}, 501)
    return _json({"ok": True})


async def _api_pause(request: web.Request) -> web.Response:
    """POST /api/pause — P1-5a Q4 软暂停。"""
    await pause_mover()
    return _json({"ok": True, "paused": True})


async def _api_resume(request: web.Request) -> web.Response:
    """POST /api/resume — P1-5a Q4 恢复。扫描 pending 任务按 created_at 触发。"""
    await resume_mover()
    return _json({"ok": True, "paused": False})
