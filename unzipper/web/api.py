# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
from datetime import datetime
from pathlib import Path

from aiohttp import web

import config
from common import run_state
from common.open_folder import open_in_file_manager
from unzipper.web.websocket import _build_state, _broadcast
from unzipper.web.templates import UNZIPPER_HTML
import unzipper.manager as manager
import unzipper.state as state
import unzipper.storage as storage
from unzipper.extractor import HAS_7Z
from unzipper.storage import save_history
from common.env_writer import save_env_values
from common.path_utils import validate_path
from common.peer_sync import post_settings as peer_post_settings


# ── UI ─────────────────────────────────────────────────────────────────────────

async def _index_handler(_request):
    html = UNZIPPER_HTML.replace('__API_KEY__', config.API_KEY)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


# ── Existing endpoints ─────────────────────────────────────────────────────────

async def _api_state(_request):
    return web.Response(text=_build_state(), content_type="application/json", charset="utf-8")


async def _api_confirm(request):
    id_ = request.match_info["id"].zfill(4)
    ok  = await manager.confirm_multipart(id_)
    if ok:
        await _broadcast()
        return web.json_response({"ok": True})
    return web.json_response({"ok": False, "error": f"ID {id_} not found"}, status=404)


async def _api_retry(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "无效 JSON"}, status=400)
    name = (data or {}).get("name", "").strip()
    if not name:
        return web.json_response({"ok": False, "error": "缺少 name"}, status=400)
    ok = await manager.retry_failed(name)
    if ok:
        await _broadcast()
        return web.json_response({"ok": True})
    return web.json_response(
        {"ok": False, "error": "未找到可重试的失败记录，或归档已不在失败目录"}, status=404)


async def _api_open(request):
    data   = await request.json()
    target = data.get("path", "").strip()
    if not target:
        return web.json_response({"ok": False, "error": "path required"}, status=400)
    p = Path(target).resolve()
    allowed_roots = [config.OUTPUT_PATH.resolve(), config.WATCH_PATH.resolve()]
    if not any(_is_under(p, r) for r in allowed_roots):
        return web.json_response({"ok": False, "error": "path not allowed"}, status=403)
    if not p.exists():
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    ok, why = open_in_file_manager(p)
    if not ok:
        return web.json_response({"ok": False, "error": why}, status=501)
    return web.json_response({"ok": True})


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


# ── 2.1 GET /api/health ────────────────────────────────────────────────────────

async def _api_health(_request):
    return web.json_response({
        "ok":                   True,
        "status":               "busy" if state.current_tasks else "idle",
        "running_tasks":        len(state.current_tasks),
        "queue_depth":          manager.queue_depth(),
        "pending_count":        len(state.pending_multipart),
        "watch_path":           str(config.WATCH_PATH)  if config.WATCH_PATH  else None,
        "output_path":          str(config.OUTPUT_PATH) if config.OUTPUT_PATH else None,
        "passwords_count":      len(state.passwords),
        "has_7z":               HAS_7Z,
        "paused":               state.paused,
    })


# ── P1-5a Q4 软暂停 ───────────────────────────────────────────────────────────

async def _api_pause(_request):
    """POST /api/pause — 暂停 watcher 入队（已运行任务不受影响）。"""
    state.paused = True
    run_state.save("unzipper", paused=True)
    await _broadcast()
    return web.json_response({"ok": True, "paused": True})


async def _api_resume(_request):
    """POST /api/resume — 恢复，并扫描 WATCH_PATH 下未处理的归档（dedup）。"""
    state.paused = False
    run_state.save("unzipper", paused=False)
    submitted = 0
    if config.WATCH_PATH and config.WATCH_PATH.exists():
        # dedup：跳过 current_tasks（解压中）和 pending_multipart（待确认）的源路径
        in_progress_paths = {
            str(t.get("path", "")) for t in state.current_tasks.values()
        } | {
            str(rec.get("path", "")) for rec in state.pending_multipart.values()
        }
        from unzipper.utils import ARCHIVE_EXTS
        for entry in config.WATCH_PATH.iterdir():
            # skip dot-prefixed (.mover_staging_* etc.)
            if any(p.startswith('.') for p in entry.parts):
                continue
            # skip files already being processed
            if str(entry) in in_progress_paths:
                continue
            if entry.is_file():
                name = entry.name.lower()
                if not (name.endswith('.7z.001') or entry.suffix.lower() in ARCHIVE_EXTS):
                    continue
                await manager.submit(entry)
                submitted += 1
            # 文件夹任务在 v1 不做扫描补提交（用户可手动调 /api/submit）
    await _broadcast()
    return web.json_response({"ok": True, "paused": False, "rescanned": submitted})


# ── 2.2 POST /api/submit ───────────────────────────────────────────────────────

async def _api_submit(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    raw = data.get("path", "").strip()
    if not raw:
        return web.json_response({"ok": False, "error": "path required"}, status=400)

    p = Path(raw)
    if not p.is_absolute():
        return web.json_response({"ok": False, "error": "path must be absolute"}, status=400)
    p = p.resolve()
    if not p.exists():
        return web.json_response({"ok": False, "error": "path does not exist"}, status=404)

    # Must not be inside OUTPUT_PATH
    if config.OUTPUT_PATH:
        try:
            p.relative_to(config.OUTPUT_PATH.resolve())
            return web.json_response(
                {"ok": False, "error": "path is inside OUTPUT_PATH — refusing to process output directory"},
                status=400,
            )
        except ValueError:
            pass

    result = await manager.submit(p)
    return web.json_response({"ok": True, **result})


# ── 2.3 GET /api/pending ───────────────────────────────────────────────────────

async def _api_pending(_request):
    items = [
        {"id": id_, "name": rec["name"], "kind": rec.get("kind", "multipart"), "path": str(rec["path"])}
        for id_, rec in state.pending_multipart.items()
    ]
    return web.json_response({"ok": True, "items": items})


# ── 2.4 GET /api/history ───────────────────────────────────────────────────────

async def _api_history(request):
    try:
        limit  = min(int(request.rel_url.query.get("limit",  "20")), 100)
        offset = max(int(request.rel_url.query.get("offset", "0")),  0)
    except ValueError:
        return web.json_response({"ok": False, "error": "limit and offset must be integers"}, status=400)

    filter_status = request.rel_url.query.get("status", "")
    filter_kind   = request.rel_url.query.get("kind",   "")

    items = list(reversed(state.history))
    if filter_status:
        items = [h for h in items if h.get("status") == filter_status]
    if filter_kind:
        items = [h for h in items if h.get("kind") == filter_kind]

    total = len(items)
    page  = items[offset: offset + limit]
    return web.json_response({"ok": True, "items": page, "total": total, "limit": limit, "offset": offset})


# ── 2.5 DELETE /api/history ────────────────────────────────────────────────────

async def _api_history_delete(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    original_len = len(state.history)

    if data.get("all"):
        state.history.clear()
    elif "before" in data:
        try:
            cutoff = datetime.fromisoformat(data["before"])
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid ISO datetime for 'before'"}, status=400)
        state.history[:] = [
            h for h in state.history
            if datetime.fromisoformat(h.get("finished_at", "9999-01-01")) >= cutoff
        ]
    elif "status" in data:
        wanted = data["status"] if isinstance(data["status"], list) else [data["status"]]
        state.history[:] = [h for h in state.history if h.get("status") not in wanted]
    elif "indexes" in data:
        idxs = set(data["indexes"])
        state.history[:] = [h for i, h in enumerate(state.history) if i not in idxs]
    else:
        return web.json_response({"ok": False, "error": "body must contain 'all', 'before', 'status', or 'indexes'"}, status=400)

    deleted = original_len - len(state.history)
    save_history(state.history)
    return web.json_response({"ok": True, "deleted": deleted})


# ── 2.7 Concurrency management ────────────────────────────────────────────────

async def _api_concurrency_get(_request):
    return web.json_response({
        "ok":                   True,
        "max_concurrent_tasks": state.max_concurrent_tasks,
        "running":              len(state.current_tasks),
    })


async def _api_concurrency_post(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    n = data.get("max")
    if not isinstance(n, int) or n < 1:
        return web.json_response({"ok": False, "error": "max must be a positive integer"}, status=400)
    await manager.set_max_concurrent(n)
    return web.json_response({
        "ok":                   True,
        "max_concurrent_tasks": state.max_concurrent_tasks,
    })


# ── P1-6 Output path management ────────────────────────────────────────────────

def _build_settings_response() -> dict:
    settings = storage.load_settings()
    return {
        "ok": True,
        "watch_path":           str(config.WATCH_PATH),
        "output_path":          str(config.OUTPUT_PATH),
        "default_watch_path":   str(config.DEFAULT_WATCH_PATH),
        "default_output_path":  str(config.DEFAULT_OUTPUT_PATH),
        "watch_path_history":   settings["path_history"].get("watch_path", []),
        "output_path_history":  settings["path_history"].get("output_path", []),
        "use_last_path":        settings.get("use_last_path", True),
    }


async def _sync_downloader_watch_path(new_path: str) -> None:
    await peer_post_settings(
        config.WEB_PORT, config.API_KEY,
        {"watch_path": new_path},
        host=config.WEB_HOST,
        label="unzipper→downloader",
    )


async def _api_settings_get(_request):
    return web.json_response(_build_settings_response())


async def _api_settings_post(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    settings = storage.load_settings()
    env_updates: dict[str, str] = {}
    requires_restart = False

    if "watch_path" in data:
        new_path, err = validate_path(data["watch_path"])
        if err:
            return web.json_response({"ok": False, "error": f"watch_path: {err}"}, status=400)
        old_path = str(config.WATCH_PATH)
        if str(new_path) != old_path:
            storage.add_path_to_history(settings, "watch_path", old_path)
            config.WATCH_PATH = new_path
            env_updates["WATCH_PATH"] = str(new_path)
            requires_restart = True  # watcher 不支持热重启，需要 restart 服务

    if "output_path" in data:
        new_path, err = validate_path(data["output_path"])
        if err:
            return web.json_response({"ok": False, "error": f"output_path: {err}"}, status=400)
        old_path = str(config.OUTPUT_PATH)
        if str(new_path) != old_path:
            storage.add_path_to_history(settings, "output_path", old_path)
            config.OUTPUT_PATH = new_path
            env_updates["OUTPUT_PATH"] = str(new_path)

    if "use_last_path" in data:
        settings["use_last_path"] = bool(data["use_last_path"])

    if env_updates:
        save_env_values(config.ENV_FILE, env_updates)
    storage.save_settings(settings)

    if "watch_path" in data and data.get("sync_downloader") and "WATCH_PATH" in env_updates:
        asyncio.create_task(_sync_downloader_watch_path(str(config.WATCH_PATH)))

    await _broadcast()
    resp = _build_settings_response()
    if requires_restart:
        resp["requires_restart"] = True
        resp["restart_reason"] = "watch_path 需重启 unzipper 后生效（watchdog 不支持热切换监听目录）"
    return web.json_response(resp)


# ── P1-8 Phase 2: 解压状态查询 ────────────────────────────────────────────────

async def _api_extract_status(request):
    """POST /api/extract-status — 批量查询多个文件名的解压状态。

    Body: {"filenames": ["a.zip", "b.rar"]}
    Response: {filename: {"status": "...", "output_path": "...", "finished_at": "..."} | null}

    状态值：extracting / pending_extract / extracted / extract_failed / null（未知）
    匹配键：filename basename。理由见 docs/pagination-design.md "同名文件冲突"。
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    filenames = body.get("filenames", [])
    if not isinstance(filenames, list):
        return web.json_response({"ok": False, "error": "filenames must be a list"}, status=400)

    result: dict = {}
    for fname in filenames:
        if not isinstance(fname, str):
            continue
        # 1) current_tasks (extracting)
        hit = next((t for t in state.current_tasks.values() if t.get("name") == fname), None)
        if hit:
            result[fname] = {"status": "extracting", "output_path": None, "finished_at": None}
            continue
        # 2) pending_multipart (pending_extract)
        hit = next((rec for rec in state.pending_multipart.values() if rec.get("name") == fname), None)
        if hit:
            result[fname] = {"status": "pending_extract", "output_path": None, "finished_at": None}
            continue
        # 3) history（最新一条 match）
        hist = next((h for h in reversed(state.history) if h.get("name") == fname), None)
        if hist:
            s = "extracted" if hist.get("status") == "done" else "extract_failed"
            result[fname] = {
                "status": s,
                "output_path": hist.get("out_dir") if s == "extracted" else None,
                "finished_at": hist.get("finished_at"),
            }
            continue
        result[fname] = None
    return web.json_response(result)


# ── 2.6 Password management ────────────────────────────────────────────────────

async def _api_passwords_get(_request):
    return web.json_response({"ok": True, "passwords": state.passwords})


async def _api_passwords_add(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    pw = data.get("password", "")
    if not pw:
        return web.json_response({"ok": False, "error": "password required"}, status=400)
    # P1-pwd: 后端拒绝换行符（即使现在存 JSON 不再受逗号限制，换行仍会破坏 UI 显示）
    if "\n" in pw or "\r" in pw:
        return web.json_response(
            {"ok": False, "error": "password cannot contain newline characters"}, status=400
        )
    if pw in state.passwords:
        return web.json_response({"ok": False, "error": "password already exists"}, status=409)

    state.passwords.append(pw)
    storage.save_passwords(state.passwords)
    return web.json_response({"ok": True, "passwords": state.passwords})


async def _api_passwords_remove(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    pw = data.get("password", "")
    if not pw:
        return web.json_response({"ok": False, "error": "password required"}, status=400)
    if pw not in state.passwords:
        return web.json_response({"ok": False, "error": "password not found"}, status=404)

    state.passwords.remove(pw)
    storage.save_passwords(state.passwords)
    return web.json_response({"ok": True, "passwords": state.passwords})


async def _api_passwords_reorder(request):
    """P1-pwd: 全量重排（拖拽 / 字典序排序后调用）。仅允许排列；不允许新增/删除。"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    new_order = data.get("passwords")
    if not isinstance(new_order, list) or not all(isinstance(p, str) for p in new_order):
        return web.json_response(
            {"ok": False, "error": "passwords must be a list of strings"}, status=400
        )
    if sorted(new_order) != sorted(state.passwords):
        return web.json_response(
            {"ok": False, "error": "reorder must contain exactly the same passwords"},
            status=400,
        )
    state.passwords[:] = list(new_order)
    storage.save_passwords(state.passwords)
    return web.json_response({"ok": True, "passwords": state.passwords})


# ── P2-4 取消解压任务 ────────────────────────────────────────────────────

async def _api_cancel(request):
    """POST /api/cancel/{task_id} — 取消正在解压的任务，回滚输出目录。"""
    task_id = request.match_info["task_id"]
    if task_id not in state.current_tasks:
        return web.json_response({"ok": False, "error": "task not found"}, status=404)
    ok = await manager.cancel_task(task_id)
    if not ok:
        return web.json_response({"ok": False, "error": "cancel failed"}, status=500)
    return web.json_response({"ok": True})

