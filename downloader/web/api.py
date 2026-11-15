# SPDX-License-Identifier: AGPL-3.0-or-later
import time
import asyncio
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import web
from telethon.tl.types import MessageMediaWebPage

import config
from common.open_folder import open_in_file_manager
import downloader.state as state
from common import run_state
import downloader.storage as storage
from common.env_writer import save_env_values
from common.path_utils import validate_path
from common.peer_sync import post_settings as peer_post_settings
from downloader.utils import sanitize, entity_display_name, unique_dir, unique_file, media_filename
from downloader.tg.client import client
from downloader.tg.metadata import _format_details_header, _format_media_entry
from downloader.web.websocket import _broadcast, _build_state
from downloader.web.templates import WEB_HTML


async def _index_handler(_request):
    html = WEB_HTML.replace('__API_KEY__', config.API_KEY)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def _api_search(request):
    if not await client.is_user_authorized():
        return web.json_response({"error": "未登录"}, status=403)
    q = request.rel_url.query.get("q", "").strip().lower()
    if not q:
        return web.json_response([])
    results = []
    async for dialog in client.iter_dialogs():
        if q in dialog.name.lower():
            results.append({"name": dialog.name, "id": dialog.id})
            if len(results) >= 30:
                break
    return web.json_response(results)


async def _api_watch_add(request):
    data = await request.json()
    cid  = str(data["id"])
    name = str(data["name"])
    # P1-5a Q2: 查重——已存在不报错，提示 already_watched
    if cid in state.watched:
        existing = state.watched[cid]
        existing_name = existing.get("name") if isinstance(existing, dict) else existing
        return web.json_response({
            "ok": True,
            "already_watched": True,
            "name": existing_name,
        })
    # P1-7: 新结构（含 watched_since、task_count、task_count_reset_at）
    # exempt: 全局暂停时是否仍监听该频道，新增默认 False
    state.watched[cid] = {
        "name": name,
        "watched_since": datetime.now().isoformat(),
        "task_count": 0,
        "task_count_reset_at": None,
        "exempt": False,
        # favorite: 纯标记，不影响下载行为，只用于前端置顶/筛选（2026-08-12）
        "favorite": False,
    }
    storage.save_watched(state.watched)
    await _broadcast()
    return web.json_response({"ok": True})


# ── P1-7 监听列表统计控制 ──────────────────────────────────────────────────────

async def _api_watch_reset_stats(_request):
    """POST /api/watch/reset-stats — 全部频道 task_count 归零。"""
    now_iso = datetime.now().isoformat()
    reset_count = 0
    for rec in state.watched.values():
        if isinstance(rec, dict):
            rec["task_count"] = 0
            rec["task_count_reset_at"] = now_iso
            reset_count += 1
    storage.save_watched(state.watched)
    await _broadcast()
    return web.json_response({"ok": True, "reset_count": reset_count})


async def _api_watch_cid_reset_stats(request):
    """POST /api/watch/{cid}/reset-stats — 单频道 task_count 归零。"""
    cid = request.match_info["cid"]
    rec = state.watched.get(cid)
    if not rec or not isinstance(rec, dict):
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    rec["task_count"] = 0
    rec["task_count_reset_at"] = datetime.now().isoformat()
    storage.save_watched(state.watched)
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_watch_cid_exempt(request):
    """POST /api/watch/{cid}/exempt — 切换该频道的「全局暂停例外」状态。

    body: {"exempt": true | false}
    详见 docs/exempt-channel-design.md
    """
    cid = request.match_info["cid"]
    if cid not in state.watched:
        return web.json_response({"ok": False, "error": "not in watch list"}, status=404)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(data.get("exempt"), bool):
        return web.json_response({"ok": False, "error": "exempt must be boolean"}, status=400)
    rec = state.watched[cid]
    if isinstance(rec, dict):
        rec["exempt"] = data["exempt"]
    storage.save_watched(state.watched)
    await _broadcast()
    return web.json_response({"ok": True, "cid": cid, "exempt": data["exempt"]})


async def _api_watch_cid_favorite(request):
    """POST /api/watch/{cid}/favorite — 标记/取消「喜爱」。

    body: {"favorite": true | false}
    ⚠️ 纯标记，**不影响下载行为**（跟 exempt 不同）——只给前端做置顶和筛选。
    老频道记录里没有这个键，读的时候一律 .get("favorite", False)。
    """
    cid = request.match_info["cid"]
    if cid not in state.watched:
        return web.json_response({"ok": False, "error": "not in watch list"}, status=404)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(data.get("favorite"), bool):
        return web.json_response({"ok": False, "error": "favorite must be boolean"}, status=400)
    rec = state.watched[cid]
    if isinstance(rec, dict):
        rec["favorite"] = data["favorite"]
    storage.save_watched(state.watched)
    await _broadcast()
    return web.json_response({"ok": True, "cid": cid, "favorite": data["favorite"]})


async def _api_watch_remove(request):
    cid = request.match_info["chat_id"]
    if cid in state.watched:
        del state.watched[cid]
        storage.save_watched(state.watched)
        await _broadcast()
        return web.json_response({"ok": True})
    return web.json_response({"ok": False}, status=404)


async def _api_auth(request):
    data  = await request.json()
    value = str(data.get("value", "")).strip()
    if state._auth_future and not state._auth_future.done():
        state._auth_future.set_result(value)
        return web.json_response({"ok": True})
    return web.json_response({"ok": False, "error": "现在没有在等验证码（可能已经登录成功，刷新页面看看）"}, status=400)


async def _api_auth_qr(_request):
    """网页登录：改用扫码登录（手机 Telegram → 设置 → 设备 → 扫描二维码）。"""
    from downloader.tg.client import client
    from downloader.tg.web_login import start_qr
    r = await start_qr(client)
    return web.json_response(r, status=200 if r["ok"] else 400)


async def _api_auth_resend(_request):
    """网页登录：重新发送验证码（Telegram 会按 next_type 换一种方式发）。"""
    if state._auth_step != "waiting_code":
        return web.json_response({"ok": False, "error": "现在没有在等验证码"}, status=400)
    from downloader.tg.client import client
    from downloader.tg.web_login import resend_code
    info = await resend_code(client, config.PHONE)
    return web.json_response({"ok": not info.get("error"), "auth_info": info})


async def _api_state(_request):
    return web.Response(text=_build_state(), content_type="application/json", charset="utf-8")


async def _api_open(request):
    data   = await request.json()
    target = data.get("path", "").strip()
    if not target:
        return web.json_response({"ok": False, "error": "path required"}, status=400)
    p = Path(target).resolve()
    allowed_roots = [config.DOWNLOAD_DIR.resolve(), config.WATCH_PATH.resolve()]
    if not any(_is_under(p, r) for r in allowed_roots):
        return web.json_response({"ok": False, "error": "path not allowed"}, status=403)
    if not p.exists():
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    ok, why = open_in_file_manager(p)
    if not ok:
        return web.json_response({"ok": False, "error": why}, status=501)
    return web.json_response({"ok": True})


async def _retry_one_task(task_id: str) -> dict:
    """单条 retry 的核心逻辑（_api_retry 与批量 retry-all-failed 共用）。

    返回 {"ok": bool, ...}（成功或具体错误描述）。
    """
    from downloader.download.manager import download_one, _recompute_group_status

    if not task_id:
        return {"ok": False, "error": "task_id required"}

    # 防并发：task_id 已在 active_downloads（正在下载，或启动恢复扫描已抢先接管）
    # 时不再重复启动，否则两个 download_one 并发写同一批 .partN 会互相破坏。
    if task_id in state.active_downloads:
        return {"ok": False, "error": "任务正在下载中，无需重试"}

    # 数据源优先：pending_tasks (P1-5b 失败保留) > completed_downloads (老记录回退)
    pending_rec   = state.pending_tasks.get(task_id)
    completed_rec = None

    if pending_rec:
        chat_id    = pending_rec["chat_id"]
        message_id = pending_rec["message_id"]
        save_path  = Path(pending_rec["save_path"])
        grouped_id = pending_rec.get("grouped_id")
        label_hint = None
    else:
        completed_rec = next(
            (r for r in state.completed_downloads if r.get("task_id") == task_id), None
        )
        if not completed_rec:
            return {"ok": False, "error": "记录不存在"}
        chat_id    = completed_rec.get("chat_id", 0)
        message_id = completed_rec.get("message_id", 0)
        if not (chat_id and message_id):
            return {"ok": False, "error": "原始记录缺少 chat_id / message_id，无法重试"}
        # 沿用原 save_path（不再创建 retry_* 目录）
        if completed_rec.get("path"):
            save_path = Path(completed_rec["path"])
        elif completed_rec.get("dir") and completed_rec.get("filename"):
            save_path = Path(completed_rec["dir"]) / completed_rec["filename"]
        else:
            return {"ok": False, "error": "原始记录缺少 path/dir，无法重试"}
        grouped_id = completed_rec.get("grouped_id")
        label_hint = completed_rec.get("label")

    # 重取 message（防 file_reference 过期）
    try:
        msg = await client.get_messages(chat_id, ids=message_id)
    except Exception as e:
        return {"ok": False, "error": f"获取消息失败: {e}"}
    if msg is None or not msg.media:
        return {"ok": False, "error": "消息不存在或已无媒体内容"}

    # 确保父目录存在（用户可能删过原目录）
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # 清掉该 task_id 的全部旧历史记录（成功后会作为新 done 重新写入）。
    # 注意必须两个分支都删：失败时 _finish 会写一条 error 进 completed_downloads，
    # 同时 P1-5b 又在 pending_tasks 保留记录——此前只在 completed_rec 分支删除，
    # 走 pending 分支重试后旧 error 记录残留，列表就一直显示"失败"。
    stale = [r for r in state.completed_downloads if r.get("task_id") == task_id]
    if stale:
        for r in stale:
            state.completed_downloads.remove(r)
        storage.save_completed(state.completed_downloads)

    # 同步 grouped_state：file 状态从 error 重置为 downloading（如有 entry）
    gs_key = f"{chat_id}_{grouped_id}" if grouped_id else task_id
    group  = state.grouped_state.get(gs_key)
    if group and task_id in group.get("files", {}):
        group["files"][task_id]["status"] = "downloading"
        new_status, completed_at = _recompute_group_status(group)
        group["status"]       = new_status
        group["completed_at"] = completed_at
        storage.save_grouped_state(state.grouped_state, key=gs_key)

    # P1-5c: 决定续传 vs 重头 + 累加 retry_count
    can_resume = False
    if pending_rec is not None:
        can_resume = (
            pending_rec.get("downloaded_bytes", 0) > 0
            and not pending_rec.get("last_resume_failed", False)
        )
        # 累加 retry_count（崩溃恢复不计；这里是用户主动重试）
        pending_rec["retry_count"] = pending_rec.get("retry_count", 0) + 1
        if not can_resume:
            # 重头：清进度 + 删 .partN
            pending_rec["downloaded_bytes"] = 0
            for p in save_path.parent.glob(f"{save_path.name}.part*"):
                try: p.unlink()
                except OSError: pass
        storage.save_pending_tasks(state.pending_tasks, key=task_id)

    # 复用 task_id 启动 download_one（它会覆盖 pending_tasks[task_id]，但保留 retry_count 等字段）
    label = label_hint or f"retry/{save_path.name}"
    t = asyncio.create_task(download_one(
        task_id, msg, save_path, label,
        chat_id=chat_id, message_id=message_id,
        resume=can_resume,
    ))
    state.task_outer_tasks[task_id] = t
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)
    return {"ok": True, "task_id": task_id, "save_path": str(save_path)}


async def _api_retry(request):
    """POST /api/retry — 单条重试。详见 _retry_one_task。"""
    data    = await request.json()
    task_id = str(data.get("task_id", "")).strip()
    if not task_id:
        return web.json_response({"ok": False, "error": "task_id required"}, status=400)
    result = await _retry_one_task(task_id)
    await _broadcast()
    if result.get("ok"):
        return web.json_response(result)
    # 错误码：找不到记录 → 404，其他 → 400
    err = result.get("error", "")
    status = 404 if "记录不存在" in err or "消息不存在" in err else 400
    return web.json_response(result, status=status)


async def _api_retry_all_failed(_request):
    """POST /api/retry-all-failed — 扫 completed_downloads 所有 error/timeout 任务批量重试。

    串行 spawn（不限流；download_one 内部的 _conn_gate 会控制并发）。
    返回 {ok, total, queued, skipped: [{task_id, error}, ...]}。
    """
    # 收集快照（避免在迭代时 list 被 _retry_one_task 修改）
    failed = [
        r for r in list(state.completed_downloads)
        if r.get("status") in ("error", "timeout")
    ]
    queued = 0
    skipped: list[dict] = []
    for rec in failed:
        tid = rec.get("task_id")
        if not tid:
            skipped.append({"task_id": "(missing)", "error": "task_id missing"})
            continue
        # 跳过已经在进行的任务（譬如用户先点了单条 retry）
        if tid in state.active_downloads:
            skipped.append({"task_id": tid, "error": "已在下载中"})
            continue
        result = await _retry_one_task(tid)
        if result.get("ok"):
            queued += 1
        else:
            skipped.append({"task_id": tid, "error": result.get("error", "unknown")})
    await _broadcast()
    return web.json_response({
        "ok":      True,
        "total":   len(failed),
        "queued":  queued,
        "skipped": skipped,
    })


async def _api_status(request):
    """GET /api/status[?slim=1|completed][&limit=N]

    ⚠️ 默认返回全量（含 active + completed 两个大列表）。队列达到数万条时序列化出 22MB，
    downloader 正忙时要几十秒，dashboard 拉它会超时 → 前端拿到 "data": null（2026-08-13 事故）。

    三档，按调用方需要挑（**别再无脑写死 slim=1**）：
      · 不带         两个列表全给。只有确实要全量历史时才用。
      · slim=1       两个列表都不给，只给计数。手机端轮询用。
      · slim=completed  **只砍 completed（5000 条 5MB），保留 active** ——
                     网页端「正在下载」要的就是 active，砍掉它列表就永远是空的。
                     ⚠️ 2026-08-13 dashboard 无条件写死 slim=1，导致网页端下载列表
                     恒空，排查了很久才发现（2026-08-14 修）。
      · limit=N      配合上面用，active 最多返回 N 条（真实总数看 active_count，
                     另给 active_truncated 标记）。队列有数万条时列表本身就有几 MB。
    """
    _slim_q = request.rel_url.query.get("slim") or ""
    slim = _slim_q == "1"                       # 两个列表都砍
    drop_completed = slim or _slim_q == "completed"
    try:
        limit = max(0, int(request.rel_url.query.get("limit", "0")))
    except ValueError:
        limit = 0
    total_speed = sum(t.get("speed", 0.0) for t in state.active_downloads.values())
    # P1-5b: pending 任务数 + grouped_state 汇总
    grouped_summary = {
        "total_groups": len(state.grouped_state),
        "done_groups":  sum(
            1 for g in state.grouped_state.values() if g.get("status") == "done"
        ),
    }
    if slim:
        _active_list, _active_truncated = [], False
    else:
        _all_active = list(state.active_downloads.values())
        # 下载中/限流的排前面，排队的在后 —— 截断时先保住用户真正在看的那些
        _all_active.sort(key=lambda t: 0 if t.get("status") in
                         ("downloading", "flood_wait", "paused") else 1)
        _active_truncated = bool(limit and len(_all_active) > limit)
        _active_list = _all_active[:limit] if limit else _all_active

    return web.json_response({
        "active":                 _active_list,
        "active_count":           len(state.active_downloads),
        "active_truncated":       _active_truncated,
        # ⚠️ 这两个计数**必须由服务端给**，前端不能自己数 active 列表 ——
        # `slim=1` 会把列表整个剥空、`limit=N` 会截断，前端数出来的是 0 或残值。
        # 2026-08-21 实测踩到两次：dashboard 首页「正在下载」和安卓 App 的
        # 「进行中」都恒显示 0，而实际有 6~8 个在传。
        # 这就是项目约定「瘦身必须下沉到数据产生端」那条的同一个坑。
        # ⚠️ pending 里混着三种东西，别当成「排队中」一个数看（2026-09-17 hyden 反馈）：
        #   · 正在下载/等连接的     → 在 active_downloads 里
        #   · 真·排队等着轮到的     → 不在 active、retry_count == 0
        #   · **搁置的（下过但失败了）** → 不在 active、retry_count > 0
        # 第三种最坑：`recover_pending_tasks` **只在启动时跑一次**（bot.py），
        # 跑完还失败的就留在 pending_tasks 里，**没有任何周期任务会再碰它们**。
        # 界面上它们混在「队列」里看着像在排队，实际一个多月都不会动
        # ——2026-09-17 实测 11 个这样的任务，全都下到 99%+ 卡住。
        "stalled_count":          sum(
            1 for tid, t in state.pending_tasks.items()
            if tid not in state.active_downloads and (t.get("retry_count") or 0) > 0
        ),
        "downloading_count":      sum(
            1 for t in state.active_downloads.values()
            if t.get("status") in ("downloading", "flood_wait", "paused")
        ),
        "waiting_count":          sum(
            1 for t in state.active_downloads.values()
            if t.get("status") == "waiting"
        ),
        "completed":              [] if drop_completed else state.completed_downloads,
        "completed_total":        len(state.completed_downloads),
        "watched":                state.watched,
        "total_speed":            total_speed,
        "paused":                 state.monitoring_paused,
        "exempt_paused":          state.exempt_paused,
        "is_docker":              config.IS_DOCKER,   # 前端据此决定显不显示「⏹ 停止」
        "saved_paused":           state.saved_paused,
        "account_name":           state.account_name,   # 控制网页标题「<名字> TGhelper」用
        "pending":                len(state.pending_tasks),
        "grouped_state_summary":  grouped_summary,
        "disk_usage":             state.disk_usage,
        "duplicate_count":        len(state.duplicate_queue),
        "pending_toasts_count":   len(state.pending_toasts),
        "content_index_size":     {
            "md5":  len(state.content_index.get("md5", {})),
            "fuid": len(state.content_index.get("fuid", {})),
        },
    })


# ── P1-8: /api/history 分页 + 排序 + 筛选 ──────────────────────────────────────

_HISTORY_SORT_KEYS = {
    "filename":       lambda r: (r.get("filename") or "").lower(),
    "filesize":       lambda r: r.get("total") or 0,
    "status":         lambda r: r.get("status") or "",
    "finished_at":    lambda r: r.get("finished_at") or 0,
    "queued_at":      lambda r: r.get("queued_at") or 0,
    "extract_status": lambda r: r.get("extract_status") or "",
}


async def _api_history(request):
    """GET /api/history — 已完成任务分页 + 排序 + 筛选。

    参数：
      limit         默认 50，最大 200
      offset        默认 0
      sort_by       filename / filesize / status / finished_at（默认）/ queued_at
      sort_order    asc / desc（默认 desc）
      filter_status 可选，逗号分隔的 extract_status 值（v1 字段不存在时跳过该记录）
    """
    q = request.rel_url.query
    try:
        limit = max(1, min(int(q.get("limit", "50")), 200))
        offset = max(0, int(q.get("offset", "0")))
    except ValueError:
        return web.json_response(
            {"ok": False, "error": "limit / offset must be integers"}, status=400
        )

    sort_by = q.get("sort_by", "finished_at")
    if sort_by not in _HISTORY_SORT_KEYS:
        return web.json_response(
            {"ok": False, "error": f"invalid sort_by: {sort_by}"}, status=400
        )

    sort_order = q.get("sort_order", "desc")
    if sort_order not in ("asc", "desc"):
        return web.json_response(
            {"ok": False, "error": "sort_order must be asc or desc"}, status=400
        )

    filter_status_raw = q.get("filter_status", "").strip()
    filter_set = (
        {s.strip() for s in filter_status_raw.split(",") if s.strip()}
        if filter_status_raw else None
    )

    items = list(state.completed_downloads)

    # P1-8 Phase 2: 筛选（extract_status 真正生效；空字段记为 not_archive 以保证非压缩包仍可被筛选）
    if filter_set:
        items = [r for r in items if (r.get("extract_status") or "not_archive") in filter_set]

    # 排序
    items.sort(key=_HISTORY_SORT_KEYS[sort_by], reverse=(sort_order == "desc"))

    total = len(items)
    page  = items[offset : offset + limit]

    return web.json_response({
        "ok":     True,
        "items":  page,
        "total":  total,
        "offset": offset,
        "limit":  limit,
    })


async def _api_pause(_request):
    """P1-5a Q4: 软暂停监听。不影响已排队/正在下载的任务。"""
    state.monitoring_paused = True
    run_state.save("downloader", monitoring_paused=True)
    await _broadcast()
    return web.json_response({"ok": True, "paused": True})


async def _api_resume(_request):
    """P1-5a Q4: 恢复监听。"""
    state.monitoring_paused = False
    run_state.save("downloader", monitoring_paused=False)
    await _broadcast()
    return web.json_response({"ok": True, "paused": False})


async def _api_exempt_pause(_request):
    """暂停例外频道的监听（2026-08-06）。

    例外频道本来是「全局暂停也照收」，想让它们停下来以前只能逐个改 exempt 状态、
    事后还得记着改回来。这个开关让例外频道也能一键停/开，不动 exempt 本身。
    """
    state.exempt_paused = True
    run_state.save("downloader", exempt_paused=True)
    await _broadcast()
    return web.json_response({"ok": True, "exempt_paused": True})


async def _api_exempt_resume(_request):
    """恢复例外频道的监听。"""
    state.exempt_paused = False
    run_state.save("downloader", exempt_paused=False)
    await _broadcast()
    return web.json_response({"ok": True, "exempt_paused": False})


def _set_saved_paused(value: bool) -> None:
    """改收藏开关并落盘（downloader_settings.json 的 saved_paused 键）。"""
    state.saved_paused = value
    settings = storage.load_settings()
    settings["saved_paused"] = value
    storage.save_settings(settings)


async def _api_saved_pause(_request):
    """暂停「我的收藏」的下载（2026-11-10）。只管收藏，不动另外两个开关。"""
    _set_saved_paused(True)
    await _broadcast()
    return web.json_response({"ok": True, "saved_paused": True})


async def _api_saved_resume(_request):
    """恢复「我的收藏」的下载。"""
    _set_saved_paused(False)
    await _broadcast()
    return web.json_response({"ok": True, "saved_paused": False})


# ── 硬停自己 ─────────────────────────────────────────────────────────────────
#
# 网页上的「⏹ 停止 downloader」按钮走这里。跟软暂停（monitoring_paused）不一样：
# 那个只是让 handle_media 不接消息，进程还在。这里是把整个下载器停掉。
#
# 只做 Docker 版（hyden 2026-11-11 定）：请 control 服务把下载器容器停掉。
# 不能只给自己发 SIGTERM：容器的 restart: unless-stopped 会马上把它拉起来；
# 只有通过 Docker 停（docker stop），它才会一直停着，直到有人再点「启动」。
#
# 原生部署返回 501：原生的停止方式是 ./stop.sh 或 systemd。
# 2026-11-11 之前这里是 macOS launchctl 版：在 Docker 里 launchctl 不存在，
# 异常被吞掉却照样回 ok:true —— 界面显示「已停止」，实际根本没停。

# 停止请求延迟多久发（先让响应写回给浏览器，否则还没写完自己就被停了，
# 前端会拿到 Connection reset 以为失败）。单测可以改成 0。
_STOP_DELAY_S = 0.3


async def _api_downloader_stop(_request):
    """POST /api/downloader/stop — 停掉下载器容器（经 control 服务）。"""
    from common import control_client
    from common.logger import get_logger
    log = get_logger("downloader")

    if not config.IS_DOCKER:
        return web.json_response({"ok": False, "message": control_client.NATIVE_REASON}, status=501)

    # 先确认控制服务连得上，连不上就如实报错 —— 绝不能再「回 ok 但其实没停」
    status, body = await control_client.call("GET", "/api/services", timeout=10)
    if status != 200 or not body.get("ok"):
        return web.json_response(
            {"ok": False, "message": body.get("message") or f"控制服务异常（HTTP {status}）"},
            status=503)

    async def _delayed():
        await asyncio.sleep(_STOP_DELAY_S)
        st, b = await control_client.call("POST", "/api/services/downloader/stop", timeout=60)
        # 正常情况下走到这里之前自己就已经被停了；能打出这行说明停止失败
        log.error(f"[stop] 请控制服务停止下载器失败：HTTP {st} {b.get('message')}")

    asyncio.get_running_loop().create_task(_delayed())
    log.info("[stop] 收到 /api/downloader/stop —— 稍后请控制服务停掉下载器容器")
    return web.json_response({
        "ok": True,
        "stopping": True,
        "message": "已发起停止；页面即将失联。要恢复请去 dashboard 设置页「服务启停」点启动。",
    })


async def _start_api_download(msg, chat_id: int, message_id: int, *,
                              skip_md5_index: bool = False,
                              task_id_tag: str = "api",
                              task_id_seq: int | None = None,
                              source: str = "realtime") -> dict:
    """从已取的 message 启动一次 /api/download 模式下载（孤立 unique_dir）。

    参数：
      skip_md5_index=True：跳过 fuid 查重（toast「直接下载」/ duplicate-queue 重新下载）
      task_id_tag: 后缀标签，默认 "api"。历史下载传 "hist_<job_short>"
      task_id_seq: 后缀序号；提供时 task_id = f"{cid}_{mid}_{tag}_{seq}"（确保唯一）
                   不提供时 task_id = f"{cid}_{mid}_{tag}{int(time.time())}"
      source: "realtime" | "history"，传给 download_one 持久化
    返回 {"task_id", "filename", "save_dir"}。
    """
    from downloader.download.manager import download_one
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        entity      = await client.get_entity(chat_id)
        source_name = sanitize(entity_display_name(entity), f"chat_{chat_id}")
    except Exception:
        source_name = f"chat_{chat_id}"

    raw_text    = (msg.message or "").strip()
    suffix      = sanitize(raw_text[:10], "未命名文件夹") if raw_text else "未命名文件夹"
    save_dir    = unique_dir(config.DOWNLOAD_DIR / source_name / f"{ts}_{suffix}")
    save_dir.mkdir(parents=True, exist_ok=True)

    if msg.message:
        (save_dir / "文字信息.txt").write_text(msg.message, encoding="utf-8")

    file_path   = unique_file(save_dir / media_filename(msg))
    detail_path = save_dir / "消息详情.txt"
    header = _format_details_header(msg)
    entry  = _format_media_entry(msg, 1, file_path.name)
    detail_path.write_text(header + "\n" + entry + "\n", encoding="utf-8")

    if task_id_seq is not None:
        task_id = f"{chat_id}_{message_id}_{task_id_tag}_{task_id_seq}"
    else:
        # 兼容旧路径：toast「直接下载」用 _dup，普通手动用 _api
        suffix_tag = "_dup" if skip_md5_index else "_api"
        # 如果调用方传了 task_id_tag（非默认），按 tag 拼
        if task_id_tag != "api":
            task_id = f"{chat_id}_{message_id}_{task_id_tag}_{int(time.time())}"
        else:
            task_id = f"{chat_id}_{message_id}{suffix_tag}{int(time.time())}"
    label   = f"{source_name}/{save_dir.name}"

    t = asyncio.create_task(download_one(task_id, msg, file_path, label,
                                         chat_id=chat_id, message_id=message_id,
                                         source=source))
    # 让 _finish 知道这个任务跳过 MD5 索引（避免「直接下载」自我命中）
    if skip_md5_index:
        # download_one 会在入函数时同步写 active_downloads；create_task 调度后立即返回，
        # 但 download_one 内部的 await 在第一个事件循环 yield 之前会先写。我们在创建后等
        # 一次 sleep(0) 让其完成同步初始化，然后打标记。
        async def _mark_skip():
            await asyncio.sleep(0)
            rec = state.active_downloads.get(task_id)
            if rec is not None:
                rec["skip_md5_index"] = True
        asyncio.create_task(_mark_skip())
    state.task_outer_tasks[task_id] = t
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)
    return {"task_id": task_id, "filename": file_path.name, "save_dir": str(save_dir)}


async def _api_download(request):
    data       = await request.json()
    chat_id    = data.get("chat_id")
    message_id = data.get("message_id")
    if not (chat_id and message_id):
        return web.json_response({"ok": False, "error": "chat_id and message_id required"}, status=400)

    chat_id    = int(chat_id)
    message_id = int(message_id)

    try:
        msg = await client.get_messages(chat_id, ids=message_id)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"获取消息失败: {e}"}, status=500)

    if msg is None or not msg.media or isinstance(msg.media, MessageMediaWebPage):
        return web.json_response({"ok": False, "error": "消息不存在或无媒体内容"}, status=404)

    # MD5 dedup: fuid 快速查（下载前）
    from downloader.md5_worker import _extract_fuid, _make_toast, _resolve_source_label
    fuid_key = _extract_fuid(msg)
    if fuid_key and fuid_key in state.content_index.get("fuid", {}):
        md5_hex = state.content_index["fuid"][fuid_key]
        existing = state.content_index.get("md5", {}).get(md5_hex)
        if existing:
            from telethon.tl.types import MessageMediaDocument as _Doc
            try:
                fname = media_filename(msg)
            except Exception:
                fname = ""
            size = (msg.media.document.size or 0) if isinstance(msg.media, _Doc) else 0
            placeholder_task_id = f"{chat_id}_{message_id}"
            toast = _make_toast(
                trigger_source="api_download",
                duplicate_type="fuid",
                task_id=placeholder_task_id,
                chat_id=chat_id,
                message_id=message_id,
                filename=fname,
                size_mb=round(size / 1048576, 1),
                source_label=_resolve_source_label(chat_id),
                matched_filename=existing.get("filename", ""),
                matched_path=existing.get("path", ""),
                matched_finished_at=existing.get("finished_at", ""),
                downloaded_path=None,
            )
            state.pending_toasts.append(toast)
            await _broadcast()
            return web.json_response({
                "ok": True,
                "duplicate_pending": True,
                "toast_id": toast["toast_id"],
            })

    result = await _start_api_download(msg, chat_id, message_id)
    await _broadcast()
    return web.json_response({"ok": True, **result})


async def _api_completed_clear(request):
    state.completed_downloads.clear()
    storage.save_completed(state.completed_downloads)
    await _broadcast()
    return web.json_response({"ok": True})


# ── F6: 重复下载队列 API ────────────────────────────────────────────────────

async def _api_dq_list(_request):
    return web.json_response({
        "ok": True,
        "queue": state.duplicate_queue,
        "count": len(state.duplicate_queue),
    })


async def _api_dq_clear(_request):
    n = len(state.duplicate_queue)
    state.duplicate_queue = []
    storage.save_duplicate_queue(state.duplicate_queue)
    await _broadcast()
    return web.json_response({"ok": True, "removed": n})


async def _api_dq_delete(request):
    tid = request.match_info["task_id"]
    before = len(state.duplicate_queue)
    state.duplicate_queue = [d for d in state.duplicate_queue if d.get("task_id") != tid]
    if len(state.duplicate_queue) == before:
        return web.json_response({"ok": False, "error": "not in queue"}, status=404)
    storage.save_duplicate_queue(state.duplicate_queue)
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_dq_download(request):
    """触发重新下载：复用 _start_api_download，task_id 后缀 _dup{ts}。"""
    tid = request.match_info["task_id"]
    entry = next((d for d in state.duplicate_queue if d.get("task_id") == tid), None)
    if not entry:
        return web.json_response({"ok": False, "error": "not in queue"}, status=404)

    chat_id = int(entry["chat_id"])
    message_id = int(entry["message_id"])

    try:
        msg = await client.get_messages(chat_id, ids=message_id)
    except Exception as e:
        return web.json_response(
            {"ok": False, "error": f"获取消息失败: {e}"}, status=500
        )
    if msg is None or not msg.media or isinstance(msg.media, MessageMediaWebPage):
        return web.json_response(
            {"ok": False, "error": "消息不存在或无媒体内容"}, status=404
        )

    result = await _start_api_download(msg, chat_id, message_id, skip_md5_index=True)

    # 移出队列
    state.duplicate_queue = [d for d in state.duplicate_queue if d.get("task_id") != tid]
    storage.save_duplicate_queue(state.duplicate_queue)

    await _broadcast()
    return web.json_response({
        "ok": True,
        "new_task_id": result["task_id"],
        "filename": result["filename"],
        "save_dir": result["save_dir"],
    })


# ── MD5 dedup: /api/toast/* 端点 ────────────────────────────────────────────

def _find_toast(toast_id: str) -> dict | None:
    return next((t for t in state.pending_toasts if t.get("toast_id") == toast_id), None)


def _remove_toast(toast_id: str) -> None:
    state.pending_toasts = [
        t for t in state.pending_toasts if t.get("toast_id") != toast_id
    ]


async def _api_toasts_list(_request):
    return web.json_response({
        "ok": True,
        "toasts": state.pending_toasts,
        "count": len(state.pending_toasts),
    })


async def _api_toast_queue(request):
    """加入 duplicate_queue + 移出 pending_toasts。"""
    from downloader.toast_manager import _enqueue_from_toast
    tid = request.match_info["toast_id"]
    toast = _find_toast(tid)
    if not toast:
        return web.json_response({"ok": False, "error": "toast not found"}, status=404)
    inserted = _enqueue_from_toast(toast)
    if inserted:
        storage.save_duplicate_queue(state.duplicate_queue)
    _remove_toast(tid)
    await _broadcast()
    return web.json_response({"ok": True, "queued": inserted})


async def _api_toast_skip(request):
    """fuid 场景：丢弃；finish 场景：删文件 + 删 completed 记录（mover 已搬走则跳过删文件）。"""
    tid = request.match_info["toast_id"]
    toast = _find_toast(tid)
    if not toast:
        return web.json_response({"ok": False, "error": "toast not found"}, status=404)

    src = toast.get("trigger_source")
    removed_file = False
    removed_record = False
    if src == "finish":
        dp = toast.get("downloaded_path")
        if dp:
            try:
                Path(dp).unlink()
                removed_file = True
            except FileNotFoundError:
                pass  # mover 已搬走
            except Exception as e:
                from common.logger import get_logger
                get_logger("downloader").warning(f"[toast/skip] 删除文件失败 {dp}: {e}")
        target_tid = toast.get("task_id")
        if target_tid:
            before = len(state.completed_downloads)
            state.completed_downloads = [
                r for r in state.completed_downloads if r.get("task_id") != target_tid
            ]
            if len(state.completed_downloads) != before:
                storage.save_completed(state.completed_downloads)
                removed_record = True

    _remove_toast(tid)
    await _broadcast()
    return web.json_response({
        "ok": True,
        "trigger_source": src,
        "removed_file": removed_file,
        "removed_completed_record": removed_record,
    })


async def _api_toast_download(request):
    """fuid 场景：启动「直接下载」，绕过查重；finish 场景拒绝。"""
    tid = request.match_info["toast_id"]
    toast = _find_toast(tid)
    if not toast:
        return web.json_response({"ok": False, "error": "toast not found"}, status=404)
    if toast.get("trigger_source") == "finish":
        return web.json_response({"ok": False, "error": "download not applicable for finish toast"}, status=400)

    chat_id = int(toast.get("chat_id"))
    message_id = int(toast.get("message_id"))
    try:
        msg = await client.get_messages(chat_id, ids=message_id)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"获取消息失败: {e}"}, status=500)
    if msg is None or not msg.media or isinstance(msg.media, MessageMediaWebPage):
        return web.json_response({"ok": False, "error": "消息不存在或无媒体内容"}, status=404)

    result = await _start_api_download(msg, chat_id, message_id, skip_md5_index=True)
    _remove_toast(tid)
    await _broadcast()
    return web.json_response({"ok": True, **result})


async def _api_toast_keep(request):
    """finish 场景：no-op，仅移出 pending_toasts。"""
    tid = request.match_info["toast_id"]
    toast = _find_toast(tid)
    if not toast:
        return web.json_response({"ok": False, "error": "toast not found"}, status=404)
    if toast.get("trigger_source") != "finish":
        return web.json_response({"ok": False, "error": "keep only applicable for finish toast"}, status=400)
    _remove_toast(tid)
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_toast_open_matched(request):
    """打开 matched_path 所在文件夹（finish 场景「查看重复」）。失败不删除 toast。"""
    tid = request.match_info["toast_id"]
    toast = _find_toast(tid)
    if not toast:
        return web.json_response({"ok": False, "error": "toast not found"}, status=404)
    matched = toast.get("matched_path") or ""
    if not matched:
        return web.json_response({"ok": False, "error": "matched_path is empty"}, status=400)
    parent = Path(matched).parent
    if not parent.exists():
        return web.json_response({"ok": False, "error": f"原文件目录不存在：{parent}"}, status=404)
    ok, why = open_in_file_manager(parent)
    if not ok:
        return web.json_response({"ok": False, "error": why}, status=501)
    return web.json_response({"ok": True, "opened": str(parent)})


async def _api_toast_delete(request):
    """前端兜底：强制删除 toast，不触发任何副作用。"""
    tid = request.match_info["toast_id"]
    toast = _find_toast(tid)
    if not toast:
        return web.json_response({"ok": False, "error": "toast not found"}, status=404)
    _remove_toast(tid)
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_history_clear_failed(_request):
    """DELETE /api/history/failed — 仅清除 error/timeout 记录。

    同步移除对应 pending_tasks 条目，否则启动恢复会把已删除的失败任务
    重新排队（僵尸复活）。只删记录不删文件。
    """
    before  = len(state.completed_downloads)
    removed = [r for r in state.completed_downloads if r.get("status") in ("error", "timeout")]
    state.completed_downloads = [
        r for r in state.completed_downloads if r.get("status") not in ("error", "timeout")
    ]
    storage.save_completed(state.completed_downloads)
    pend_removed = 0
    for r in removed:
        tid = r.get("task_id")
        if tid and tid in state.pending_tasks:
            del state.pending_tasks[tid]
            pend_removed += 1
            # 逐个标脏。批量删也别图省事只在末尾存一次——不传 key 就是整表重写。
            storage.save_pending_tasks(state.pending_tasks, key=tid)
    await _broadcast()
    return web.json_response({
        "ok": True,
        "deleted": before - len(state.completed_downloads),
        "pending_removed": pend_removed,
    })


async def _api_history_clear_done(_request):
    """DELETE /api/history/done — 仅清除 status=done，保留 error / timeout。"""
    before = len(state.completed_downloads)
    state.completed_downloads = [
        r for r in state.completed_downloads if r.get("status") != "done"
    ]
    after = len(state.completed_downloads)
    storage.save_completed(state.completed_downloads)
    await _broadcast()
    return web.json_response({
        "ok": True,
        "removed": before - after,
        "remaining": after,
    })


# ── F4B: 移动整组文件夹（走 mover）────────────────────────────────────────────

def _is_under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _resolve_group_folder(gs_key: str) -> Path | None:
    """从 grouped_state 推导该 group 在磁盘上的文件夹路径。"""
    group = state.grouped_state.get(gs_key)
    if not group:
        return None
    if group.get("status") != "done":
        return None
    files = group.get("files", {})
    for f in files.values():
        sp = f.get("save_path")
        if sp:
            folder = Path(sp).parent
            return folder if folder.exists() else None
    return None


def _validate_move_target(folder: Path, target_dir: Path) -> str | None:
    """返回 None 表示通过；否则返回错误描述。

    folder == target_dir 或互相包含都拒绝；mover 端会再做黑名单。
    """
    if not target_dir.is_absolute():
        return "target_dir must be absolute"
    try:
        if folder.resolve() == target_dir.resolve():
            return "target_dir must differ from source folder"
    except OSError:
        pass
    if _is_under(folder, target_dir) or _is_under(target_dir, folder):
        return "target_dir must not contain or be inside source folder"
    return None


def _remove_completed_by_gs_key(gs_key: str) -> int:
    """从 completed_downloads 中删除该 gs_key 关联的所有记录，返回删除数量。"""
    from downloader.download.manager import _gs_key_for
    before = len(state.completed_downloads)
    state.completed_downloads = [
        r for r in state.completed_downloads if _gs_key_for(r) != gs_key
    ]
    removed = before - len(state.completed_downloads)
    if removed:
        storage.save_completed(state.completed_downloads)
    return removed


async def _watch_movegrp(mover_task_id: str, gs_key: str) -> None:
    """轮询 mover 直到任务终态，成功则清理 completed_downloads + 广播。"""
    from common.logger import get_logger
    _log = get_logger("downloader")
    url = f"http://{config.MOVER_HOST}:{config.MOVER_PORT}/api/tasks/{mover_task_id}"
    deadline = time.time() + 3600  # 最长 1 小时
    last_status = None
    while time.time() < deadline:
        await asyncio.sleep(2)
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
                headers={'X-API-Key': config.API_KEY},
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
        except Exception:
            continue
        task = data.get("task") or data
        if not isinstance(task, dict):
            continue
        st = task.get("status")
        if st == last_status:
            continue
        last_status = st
        if st == "done":
            n = _remove_completed_by_gs_key(gs_key)
            _log.info(f"[move-group] mover task {mover_task_id} 完成，清理 {n} 条 completed 记录")
            await _broadcast()
            return
        if st == "failed":
            err = task.get("error") or "(unknown)"
            _log.warning(f"[move-group] mover task {mover_task_id} 失败：{err}")
            await _broadcast()
            return
    _log.warning(f"[move-group] watcher 超时（1h）退出 {mover_task_id}")


async def _api_history_move_group(request):
    """POST /api/history/move-group — 通过 mover 把整组下载文件夹搬到 target_dir。"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    gs_key = (data.get("gs_key") or "").strip()
    target_dir = (data.get("target_dir") or "").strip()
    if not gs_key or not target_dir:
        return web.json_response(
            {"ok": False, "error": "gs_key and target_dir required"}, status=400
        )

    folder = _resolve_group_folder(gs_key)
    if not folder:
        return web.json_response(
            {"ok": False, "error": "group not found, not done, or folder missing"},
            status=404,
        )
    if not _is_under(folder, config.DOWNLOAD_DIR):
        return web.json_response(
            {"ok": False, "error": "source folder is outside DOWNLOAD_DIR"},
            status=403,
        )

    target_path = Path(target_dir).expanduser()
    err = _validate_move_target(folder, target_path)
    if err:
        return web.json_response({"ok": False, "error": err}, status=400)

    mover_task_id = f"movegrp_{gs_key}"
    payload = {
        "source": str(folder),
        "target": str(target_path),
        "task_id": mover_task_id,
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5),
            headers={'X-API-Key': config.API_KEY},
        ) as session:
            async with session.post(
                f"http://{config.MOVER_HOST}:{config.MOVER_PORT}/api/move", json=payload,
            ) as resp:
                mover_resp = await resp.json()
    except Exception as e:
        return web.json_response(
            {"ok": False, "error": f"mover unreachable: {e}"}, status=502
        )

    if not mover_resp.get("ok"):
        return web.json_response(
            {"ok": False, "error": f"mover rejected: {mover_resp.get('error')}"},
            status=502,
        )

    # 成功提交：写入路径历史
    settings = storage.load_settings()
    storage.add_path_to_history(settings, "move_target", str(target_path))
    storage.save_settings(settings)

    # 已完成（同 task_id 重复提交）—— 立即清理 completed
    if mover_resp.get("already_moved"):
        n = _remove_completed_by_gs_key(gs_key)
        await _broadcast()
        return web.json_response({
            "ok": True,
            "already_moved": True,
            "removed_completed": n,
            "mover_task_id": mover_task_id,
            "source_folder": str(folder),
            "target_dir": str(target_path),
        })

    # 启动 watcher 协程
    t = asyncio.create_task(_watch_movegrp(mover_task_id, gs_key))
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)

    return web.json_response({
        "ok": True,
        "mover_task_id": mover_task_id,
        "source_folder": str(folder),
        "target_dir": str(target_path),
    })


async def _api_completed_delete(request):
    task_id = request.match_info["task_id"]
    rec = next((r for r in state.completed_downloads if r.get("task_id") == task_id), None)
    if rec is None:
        return web.json_response({"ok": False, "error": "记录不存在"}, status=404)
    state.completed_downloads.remove(rec)
    storage.save_completed(state.completed_downloads)
    await _broadcast()
    return web.json_response({"ok": True})


def _build_settings_response() -> dict:
    settings = storage.load_settings()
    return {
        "ok": True,
        "max_total_connections": state.MAX_TOTAL_CONNECTIONS,
        "chunk_size":            state.CHUNK_SIZE,
        "download_dir":          str(config.DOWNLOAD_DIR),
        "watch_path":            str(config.WATCH_PATH),
        "default_download_dir":  str(config.DEFAULT_DOWNLOAD_DIR),
        "default_watch_path":    str(config.DEFAULT_WATCH_PATH),
        "download_dir_history":  settings["path_history"].get("download_dir", []),
        "watch_path_history":    settings["path_history"].get("watch_path", []),
        "move_target_history":   settings["path_history"].get("move_target", []),
        "use_last_path":         settings.get("use_last_path", True),
    }


async def _api_settings_get(_request):
    return web.json_response(_build_settings_response())


async def _sync_unzipper_watch_path(new_path: str) -> None:
    """Fire-and-forget: 同步 watch_path 到 unzipper。"""
    await peer_post_settings(
        config.UNZIPPER_PORT, config.API_KEY,
        {"watch_path": new_path},
        host=config.UNZIPPER_HOST,
        label="downloader→unzipper",
    )


async def _api_settings_post(request):
    data = await request.json()

    # ── numeric settings (existing) ──
    if "max_total_connections" in data or "chunk_size" in data:
        mtc    = max(1, min(int(data.get("max_total_connections", state.MAX_TOTAL_CONNECTIONS)), 64))
        cs_raw = int(data.get("chunk_size", state.CHUNK_SIZE))
        cs     = min(1048576, max(4096, (cs_raw // 4096) * 4096))
        state.MAX_TOTAL_CONNECTIONS = mtc
        state.CHUNK_SIZE            = cs
        if state._conn_gate:
            async with state._conn_gate:
                state._conn_gate.notify_all()
        save_env_values(config.ENV_FILE, {
            "MAX_TOTAL_CONNECTIONS": str(mtc),
            "CHUNK_SIZE":            str(cs),
        })

    # ── path settings (P1-6) ──
    settings = storage.load_settings()
    env_updates: dict[str, str] = {}

    if "download_dir" in data:
        new_path, err = validate_path(data["download_dir"])
        if err:
            return web.json_response({"ok": False, "error": f"download_dir: {err}"}, status=400)
        old_path = str(config.DOWNLOAD_DIR)
        if str(new_path) != old_path:
            storage.add_path_to_history(settings, "download_dir", old_path)
            config.DOWNLOAD_DIR = new_path
            env_updates["DOWNLOAD_DIR"] = str(new_path)

    if "watch_path" in data:
        new_path, err = validate_path(data["watch_path"])
        if err:
            return web.json_response({"ok": False, "error": f"watch_path: {err}"}, status=400)
        old_path = str(config.WATCH_PATH)
        if str(new_path) != old_path:
            storage.add_path_to_history(settings, "watch_path", old_path)
            config.WATCH_PATH = new_path
            env_updates["WATCH_PATH"] = str(new_path)

    if "use_last_path" in data:
        settings["use_last_path"] = bool(data["use_last_path"])

    if env_updates:
        save_env_values(config.ENV_FILE, env_updates)
    storage.save_settings(settings)

    if "watch_path" in data and data.get("sync_unzipper") and "WATCH_PATH" in env_updates:
        asyncio.create_task(_sync_unzipper_watch_path(str(config.WATCH_PATH)))

    await _broadcast()
    return web.json_response(_build_settings_response())


async def _api_task_pause(request):
    task_id = request.match_info["task_id"]
    if task_id not in state.active_downloads:
        return web.json_response({"ok": False, "error": "任务不存在"}, status=404)
    ctrl = state.task_controls.get(task_id)
    if not ctrl or not ctrl.get("pause_event"):
        return web.json_response({"ok": False, "error": "该任务不支持暂停（小文件单连接下载）"}, status=400)
    ctrl["pause_event"].clear()
    rec = state.active_downloads[task_id]
    rec["status"] = "paused"
    rec["speed"]  = 0.0
    if rec.get("chunks"):
        for chunk in rec["chunks"]:
            chunk["speed"] = 0.0
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_task_resume(request):
    task_id = request.match_info["task_id"]
    if task_id not in state.active_downloads:
        return web.json_response({"ok": False, "error": "任务不存在"}, status=404)
    ctrl = state.task_controls.get(task_id)
    if not ctrl or not ctrl.get("pause_event"):
        return web.json_response({"ok": False, "error": "该任务不支持暂停"}, status=400)
    ctrl["pause_event"].set()
    state.active_downloads[task_id]["status"] = "downloading"
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_task_cancel(request):
    task_id = request.match_info["task_id"]
    if task_id not in state.active_downloads:
        return web.json_response({"ok": False, "error": "任务不存在"}, status=404)
    ctrl = state.task_controls.get(task_id)
    if ctrl:
        ctrl["cancel_flag"] = True
        if ctrl.get("pause_event"):
            ctrl["pause_event"].set()   # unblock if paused
        dl_task = ctrl.get("dl_task")
        if dl_task and not dl_task.done():
            dl_task.cancel()
        else:
            # waiting or flood_wait state — cancel the outer download_one task
            outer = state.task_outer_tasks.get(task_id)
            if outer and not outer.done():
                outer.cancel()
    state.active_downloads[task_id]["status"] = "cancelling"
    await _broadcast()
    return web.json_response({"ok": True})


# ── 历史消息下载（history-pull）API ──────────────────────────────────────────
# 详见 docs/history-pull-design.md

async def _api_hp_start(request):
    """POST /api/history-pull/start — 创建并启动一个 history job。

    body: {scene, chat, filter_type?, min_id?, max_id?, min_date?, max_date?, resume?, force?}
    """
    from downloader.history.runner import create_job
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    scene = (data.get("scene") or "").strip().upper()
    chat = (data.get("chat") or "").strip()
    if not scene or not chat:
        return web.json_response({"ok": False, "error": "scene and chat required"}, status=400)
    if scene not in ("A", "B", "C"):
        return web.json_response({"ok": False, "error": "scene must be A|B|C"}, status=400)

    filter_type = data.get("filter_type")
    if scene == "B":
        if filter_type not in ("id", "date"):
            return web.json_response({"ok": False, "error": "scene B requires filter_type=id|date"}, status=400)

    # 同 chat + 同 scene 已有 running/paused/ready_for_selection job？
    resume = bool(data.get("resume", False))
    force = bool(data.get("force", False))
    try:
        from telethon.utils import get_peer_id
        # 预解析 chat_id 用于查重（但实际 entity 解析在 create_job 内做一次）
        prefetch_entity = await client.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
        prefetch_cid = get_peer_id(prefetch_entity)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"chat resolve failed: {e}"}, status=404)

    if not force:
        existing = next(
            (j for j in state.history_jobs.values()
             if j.get("chat_id") == prefetch_cid and j.get("scene") == scene
             and j.get("status") in ("running", "paused", "ready_for_selection")),
            None,
        )
        if existing:
            if resume and existing["status"] == "paused":
                # 复用旧 job：重启 runner
                from downloader.history.runner import run_job
                existing["status"] = "running"
                existing["error_msg"] = None
                storage.save_history_jobs(state.history_jobs)
                t = asyncio.create_task(run_job(existing["job_id"]))
                state._pending_tasks.add(t)
                t.add_done_callback(state._pending_tasks.discard)
                await _broadcast()
                return web.json_response({
                    "ok": True, "job_id": existing["job_id"],
                    "chat_id": existing["chat_id"], "chat_name": existing["chat_name"],
                    "resumed": True,
                })
            return web.json_response({
                "ok": False,
                "error": f"existing {scene} job for this chat (status={existing['status']}); pass resume=true to continue or force=true to create new",
                "existing_job_id": existing["job_id"],
            }, status=409)

    try:
        job = await create_job(
            scene=scene, chat=chat,
            filter_type=filter_type,
            min_id=data.get("min_id"),
            max_id=data.get("max_id"),
            min_date=data.get("min_date"),
            max_date=data.get("max_date"),
        )
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)

    await _broadcast()
    return web.json_response({
        "ok": True, "job_id": job["job_id"],
        "chat_id": job["chat_id"], "chat_name": job["chat_name"],
    })


async def _api_hp_list(request):
    """GET /api/history-pull/jobs — 列出 jobs；可带 ?include=scan_results&job_id=xxx 拿全量。"""
    q = request.rel_url.query
    if q.get("include") == "scan_results" and q.get("job_id"):
        job = state.history_jobs.get(q["job_id"])
        if not job:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        return web.json_response({"ok": True, "job": job})
    # 默认摘要
    from downloader.history.runner import get_summary_payload
    return web.json_response({"ok": True, "jobs": get_summary_payload()})


async def _api_hp_stop(request):
    """POST /api/history-pull/{job_id}/stop"""
    from downloader.history.runner import stop_job
    job_id = request.match_info["job_id"]
    ok = await stop_job(job_id)
    if not ok:
        return web.json_response({"ok": False, "error": "not found or not running"}, status=404)
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_hp_rescan(request):
    """POST /api/history-pull/{job_id}/rescan — 重置 last_seen_id + scan_results。"""
    from downloader.history.runner import rescan_job
    job_id = request.match_info["job_id"]
    ok = await rescan_job(job_id)
    if not ok:
        return web.json_response({"ok": False, "error": "not found or not eligible"}, status=400)
    await _broadcast()
    return web.json_response({"ok": True})


async def _api_hp_download_selected(request):
    """POST /api/history-pull/{job_id}/download-selected — 仅 C 场景。"""
    from downloader.history.runner import download_selected
    job_id = request.match_info["job_id"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    message_ids = data.get("message_ids") or []
    if not isinstance(message_ids, list):
        return web.json_response({"ok": False, "error": "message_ids must be a list"}, status=400)
    result = await download_selected(job_id, [int(m) for m in message_ids])
    await _broadcast()
    if not result.get("ok"):
        return web.json_response(result, status=400)
    return web.json_response(result)


async def _api_hp_delete(request):
    """DELETE /api/history-pull/{job_id}"""
    from downloader.history.runner import delete_job
    job_id = request.match_info["job_id"]
    ok = await delete_job(job_id)
    if not ok:
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    await _broadcast()
    return web.json_response({"ok": True})

