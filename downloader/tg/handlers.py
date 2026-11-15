# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import asyncio
import time
from datetime import datetime

from telethon import events
from telethon.tl.types import MessageMediaWebPage, MessageMediaDocument
from telethon.utils import get_peer_id

import downloader.state as state
import downloader.storage as storage
import config
from downloader.utils import sanitize, entity_display_name, unique_dir, unique_file, media_filename
from downloader.tg.client import client
from downloader.tg.metadata import _format_details_header, _format_media_entry, _update_detail_counts
from downloader.web.websocket import _broadcast
from common.logger import get_logger

_log = get_logger("downloader")


# 网页登录（验证码 / 两步验证密码）在 downloader/tg/web_login.py


# ── Telegram commands ──────────────────────────────────────────────────────────

@client.on(events.NewMessage(pattern=r"^ID$", outgoing=True))
async def cmd_id(event):
    chat = await event.get_chat()
    await event.reply(f"当前聊天\n名字：{entity_display_name(chat)}\nID：{event.chat_id}")


@client.on(events.NewMessage(pattern=r"^搜索\s+(.+)$", outgoing=True))
async def cmd_search(event):
    keyword = event.pattern_match.group(1).strip().lower()
    await event.reply("🔍 搜索中…")
    matches = []
    async for dialog in client.iter_dialogs():
        if keyword in dialog.name.lower():
            matches.append((dialog.name, dialog.id))
    if not matches:
        await event.reply(f"未找到包含「{keyword}」的聊天")
        return
    lines = [f"找到 {len(matches)} 个结果："]
    for name, cid in matches:
        lines.append(f"• {name}\n  ID：{cid}")
    await event.reply("\n".join(lines))


@client.on(events.NewMessage(pattern=r"^监听\s+(\S+)$", outgoing=True))
async def cmd_watch(event):
    raw    = event.pattern_match.group(1)
    target = int(raw) if re.fullmatch(r"-?\d+", raw) else raw
    try:
        entity       = await client.get_entity(target)
        cid          = str(get_peer_id(entity))
        name         = entity_display_name(entity)
        # P1-5a Q2: 查重——已存在则提示
        if cid in state.watched:
            existing = state.watched[cid]
            existing_name = existing.get("name") if isinstance(existing, dict) else existing
            await event.reply(f"⚠️ 已在监听列表中：{existing_name}（id: {cid}）")
            return
        # P1-7: 新结构（含 watched_since、task_count、task_count_reset_at）
        # exempt: 全局暂停时是否仍监听该频道，新增默认 False
        state.watched[cid] = {
            "name": name,
            "watched_since": datetime.now().isoformat(),
            "task_count": 0,
            "task_count_reset_at": None,
            "exempt": False,
        }
        storage.save_watched(state.watched)
        await event.reply(f"✅ 已添加监听：{name}（id: {cid}）")
    except Exception as e:
        await event.reply(f"❌ 找不到目标 {raw}：{e}")


@client.on(events.NewMessage(pattern=r"^取消监听\s+(\S+)$", outgoing=True))
async def cmd_unwatch(event):
    raw          = event.pattern_match.group(1)
    target       = int(raw) if re.fullmatch(r"-?\d+", raw) else raw
    removed_rec = None
    if str(target) in state.watched:
        removed_rec = state.watched.pop(str(target))
    else:
        try:
            entity       = await client.get_entity(target)
            cid          = str(get_peer_id(entity))
            removed_rec = state.watched.pop(cid, None)
        except Exception:
            pass
    if removed_rec:
        # P1-7: removed_rec 可能是 dict（新格式）或 str（迁移前的旧格式）
        removed_name = removed_rec.get("name") if isinstance(removed_rec, dict) else removed_rec
        storage.save_watched(state.watched)
        await event.reply(f"✅ 已移除监听：{removed_name}")
    else:
        await event.reply(f"❌ 未找到监听目标：{target}")


@client.on(events.NewMessage(pattern=r"^监听列表$", outgoing=True))
async def cmd_list(event):
    if not state.watched:
        await event.reply("监听列表为空")
        return
    lines = [f"共监听 {len(state.watched)} 个聊天："]
    for cid, rec in state.watched.items():
        # P1-7: rec 可能是 dict（新格式）或 str（迁移前老条目）
        name = rec.get("name") if isinstance(rec, dict) else rec
        lines.append(f"• {name}（id: {cid}）")
    await event.reply("\n".join(lines))


# ── Media handler ──────────────────────────────────────────────────────────────

def _current_self_id():
    """当前登录账号的 user id；未知时返回 None。

    用 Telethon 的 `client._self_id`：它在 connect() 时就从 session 读出来了，
    **早于**开始派发更新，所以启动瞬间也不会有「还不知道自己是谁」的空档。
    而且 Telethon 把「发给自己的消息强制判成 outgoing」用的也是它——两边口径天然一致。
    """
    return getattr(client, "_self_id", None)


def _is_saved_messages(chat_id, is_private: bool) -> bool:
    """是不是「我的收藏」（Saved Messages = 和自己的私聊，chat_id 就是自己的 user id）。"""
    sid = _current_self_id()
    return sid is not None and is_private and chat_id == sid


def _passes_listen_gate(chat_id, *, out: bool, is_private: bool) -> bool:
    """实时监听的三道闸：消息方向 / 暂停开关 / 监听列表。返回 True = 放行。

    ## 「我的收藏」走自己的开关（2026-09-24 定例外，2026-11-10 加开关）

    收藏不看两个暂停开关，也不看监听列表，只看它自己的 `state.saved_paused`。
    2026-09-24 ~ 11-10 之间它没有任何开关（服务在跑就一直收），
    结果清空监听列表、两个暂停都开着时它仍在往盘上写，「关监听」只能停整个进程。
    hyden 11-10 定：保留例外，但单独给它一个开关（dashboard 频道页「收藏暂停」）。
    这样做的原因是两个坑叠在一起，让收藏悄悄停了好几天：

    ① **启动默认两个暂停都开**（见 bot.py），而收藏标的是 exempt → 归 exempt_paused 管，
       重启后没人去点恢复，它就一直停着。
    ② **Telethon 把「发给自己、且不是转发」的消息强制判成 outgoing**
       （telethon/tl/custom/message.py 的 _finish_init）。原来 handler 挂的是
       `NewMessage(incoming=True)`，所以只有**转发**进收藏的能下，**直接上传**的一律被丢。
       现在 handler 不再按方向过滤，改在这里判：非收藏的 outgoing 照旧丢掉，
       保持原来「只收别人发来的」语义（你在别的聊天里自己发的媒体不会被下载）。

    bot 自己只回文字、从不发媒体，所以放开收藏的 outgoing 不会出现「下载自己发的东西」的死循环。
    **将来若要让 bot 往收藏发文件，必须先在这里排除掉，否则会自己下自己。**
    """
    if _is_saved_messages(chat_id, is_private):
        return not state.saved_paused
    if out:
        return False

    cid_str = str(chat_id)
    if cid_str not in state.watched:
        return False

    # P1-5a Q4 软暂停：暂停时不接受新媒体（用户命令 cmd_* 不受影响）
    # 两个开关各管一半：例外频道看 exempt_paused，其余看 monitoring_paused。
    # 这样想让例外频道停下来时，不必再去逐个改它们的 exempt 状态（2026-08-06）。
    # 详见 docs/exempt-channel-design.md
    is_exempt = state.watched.get(cid_str, {}).get("exempt", False)
    return not (state.exempt_paused if is_exempt else state.monitoring_paused)


# ⚠️ 这里故意不写 incoming=True：方向过滤挪进了 _passes_listen_gate，
#    否则「我的收藏」里直接上传的文件（被 Telethon 判成 outgoing）永远进不来。
@client.on(events.NewMessage())
async def handle_media(event):
    from downloader.download.manager import download_one

    if not _passes_listen_gate(event.chat_id, out=bool(event.message.out),
                               is_private=bool(event.is_private)):
        return

    # 兜底：bot_start_time 正常在 client.start() 之前就赋好了（见 bot.py 的注释），
    # 这里的 None 判断是防止将来有人再把赋值挪到 start 之后——那会让本函数抛
    # TypeError 而 Telethon 只打一条 ERROR，消息就被静默丢了，非常难发现。
    # 收藏也要过这道：服务停着时发进收藏的东西，重启时不会被当积压补下（「服务在跑」才听）。
    if state.bot_start_time is None or event.message.date < state.bot_start_time:
        return
    message = event.message
    if not message.media or isinstance(message.media, MessageMediaWebPage):
        return

    # ── P1-5b: 单条 dedup + grouped_state 维护（在所有 gate 之后）─────────────
    # gs_key 与下方 group_key 不同：
    #   - gs_key（grouped_state 索引）单条消息 fallback 到 task_id
    #   - group_key（_group_dirs 多文件归并目录索引）单条消息为 None
    task_id = f"{event.chat_id}_{message.id}"
    gs_key = (
        f"{event.chat_id}_{message.grouped_id}"
        if message.grouped_id else task_id
    )

    # F6: REPLACE 原静默 skip → 加入 duplicate_queue（同 chat_id+message_id 已存在
    #      于 active_downloads / pending_tasks / completed_downloads 任一池子时触发）
    if _is_duplicate(event.chat_id, message.id):
        _enqueue_duplicate(event, message, task_id)
        return

    # MD5 dedup: fuid 快速查（下载前）；命中 → toast，等用户决定
    from downloader.md5_worker import _extract_fuid, _make_toast, _resolve_source_label
    fuid_key = _extract_fuid(message)
    if fuid_key and fuid_key in state.content_index.get("fuid", {}):
        md5_hex = state.content_index["fuid"][fuid_key]
        existing = state.content_index.get("md5", {}).get(md5_hex)
        if existing:
            try:
                fname = media_filename(message)
            except Exception:
                fname = ""
            from telethon.tl.types import MessageMediaDocument as _Doc
            size = (message.media.document.size or 0) if isinstance(message.media, _Doc) else 0
            toast = _make_toast(
                trigger_source="handle_media",
                duplicate_type="fuid",
                task_id=task_id,
                chat_id=event.chat_id,
                message_id=message.id,
                filename=fname,
                size_mb=round(size / 1048576, 1),
                source_label=_resolve_source_label(event.chat_id),
                matched_filename=existing.get("filename", ""),
                matched_path=existing.get("path", ""),
                matched_finished_at=existing.get("finished_at", ""),
                downloaded_path=None,
            )
            state.pending_toasts.append(toast)
            _log.info(f"[md5/fuid] {task_id} 命中 fuid={fuid_key}（与 {existing.get('filename')} 相同）→ toast")
            await _broadcast()
            return

    # grouped_state 维护：新 task_id 加入组（即使整组之前 done 也允许，避免延迟到达消息丢失）
    now_iso = datetime.now().isoformat()
    if gs_key not in state.grouped_state:
        state.grouped_state[gs_key] = {
            "status": "downloading",
            "total_files": 0,
            "done_files": 0,
            "task_ids": [],
            "files": {},
            "first_seen_at": now_iso,
            "completed_at": None,
        }
    group = state.grouped_state[gs_key]
    if task_id not in group["task_ids"]:
        group["task_ids"].append(task_id)
        group["total_files"] = len(group["task_ids"])
        # 新 task_id 加入：整组 status 退回 downloading（即使之前为 done 也清空 completed_at）
        if group["status"] == "done":
            group["status"] = "downloading"
            group["completed_at"] = None
    if task_id not in group["files"]:
        group["files"][task_id] = {
            "status": "downloading",
            "save_path": None,        # 由 download_one 后续填入
            "expected_size": None,
        }
    storage.save_grouped_state(state.grouped_state, key=gs_key)

    # P1-7: 频道 task_count +1（触发即计，不分成功失败）
    cid_str = str(event.chat_id)
    watched_rec = state.watched.get(cid_str)
    if isinstance(watched_rec, dict):
        watched_rec["task_count"] = watched_rec.get("task_count", 0) + 1
        storage.save_watched(state.watched)

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    now       = time.time()
    group_key = f"{event.chat_id}_{message.grouped_id}" if message.grouped_id else None

    # 清理过期缓存
    expired = [k for k, rec in state._group_dirs.items() if now - rec["ts"] > state.GROUP_DIR_TTL]
    for k in expired:
        del state._group_dirs[k]

    if group_key and group_key in state._group_dirs:
        # ── 同组后续消息：复用目录，追加媒体条目 ─────────────────────────────
        rec         = state._group_dirs[group_key]
        save_dir    = rec["dir"]
        source_name = save_dir.parent.name
        rec["ts"]   = now

        new_views = message.views    or 0
        new_fwds  = message.forwards or 0
        if new_views > rec["max_views"] or new_fwds > rec["max_fwds"]:
            rec["max_views"] = max(rec["max_views"], new_views)
            rec["max_fwds"]  = max(rec["max_fwds"],  new_fwds)
            _update_detail_counts(rec["detail"], rec["max_views"], rec["max_fwds"])

        if message.message and rec["no_text"]:
            try:
                content = rec["detail"].read_text(encoding="utf-8")
                content = re.sub(r'(文字内容:\s+)（无）',
                                 lambda m: m.group(1) + message.message, content, count=1)
                rec["detail"].write_text(content, encoding="utf-8")
            except Exception:
                pass
            if not (save_dir / "文字信息.txt").exists():
                (save_dir / "文字信息.txt").write_text(message.message, encoding="utf-8")
            rec["no_text"] = False

        rec["count"] += 1
        file_path = unique_file(save_dir / media_filename(message))
        entry = _format_media_entry(message, rec["count"], file_path.name)
        with rec["detail"].open("a", encoding="utf-8") as f:
            f.write(entry + "\n")

    else:
        # ── 新消息（首条或无组）：新建目录和详情文件 ──────────────────────────
        chat        = await event.get_chat()
        source_name = sanitize(entity_display_name(chat), f"未知来源_{ts}")
        raw_text    = (message.message or "").strip()
        suffix      = sanitize(raw_text[:10], "未命名文件夹") if raw_text else "未命名文件夹"
        folder_name = f"{ts}_{suffix}"
        save_dir    = unique_dir(config.DOWNLOAD_DIR / source_name / folder_name)
        save_dir.mkdir(parents=True, exist_ok=True)

        if message.message:
            (save_dir / "文字信息.txt").write_text(message.message, encoding="utf-8")

        file_path   = unique_file(save_dir / media_filename(message))
        detail_path = save_dir / "消息详情.txt"
        header = _format_details_header(message)
        entry  = _format_media_entry(message, 1, file_path.name)
        detail_path.write_text(header + "\n" + entry + "\n", encoding="utf-8")

        if group_key:
            state._group_dirs[group_key] = {
                "dir":       save_dir,
                "ts":        now,
                "detail":    detail_path,
                "count":     1,
                "max_views": message.views    or 0,
                "max_fwds":  message.forwards or 0,
                "no_text":   not bool(message.message),
            }

    # P1-5b: task_id 已在函数顶部计算（dedup 时），此处不重复
    label   = f"{source_name}/{save_dir.name}"
    _log.info(f"\n[排队] {label} → {file_path.name}")
    task = asyncio.create_task(download_one(task_id, message, file_path, label,
                                            chat_id=event.chat_id, message_id=message.id))
    state.task_outer_tasks[task_id] = task
    state._pending_tasks.add(task)
    task.add_done_callback(state._pending_tasks.discard)


# ── F6: 重复下载检测与入队 ────────────────────────────────────────────────────

def _is_duplicate(chat_id: int, message_id: int) -> bool:
    """按字段扫描三池：active_downloads / pending_tasks / completed_downloads。

    覆盖手动 /api/download（task_id 带 _api{ts} 后缀）的 in-progress 场景。
    completed 中只有 status=done 才算重复（error/timeout 允许 watch 自动重试）。
    """
    for rec in state.active_downloads.values():
        if rec.get("chat_id") == chat_id and rec.get("message_id") == message_id:
            return True
    for rec in state.pending_tasks.values():
        if rec.get("chat_id") == chat_id and rec.get("message_id") == message_id:
            return True
    for rec in state.completed_downloads:
        if (rec.get("chat_id") == chat_id
                and rec.get("message_id") == message_id
                and rec.get("status") == "done"):
            return True
    return False


def _enqueue_duplicate(event, message, task_id: str) -> None:
    """加入 duplicate_queue。队列内按 task_id 自身去重。"""
    # 队列内去重
    if any(d.get("task_id") == task_id for d in state.duplicate_queue):
        _log.info(f"[duplicate] {task_id} 已在待确认队列，忽略此次触发")
        return

    # 推断字段
    try:
        filename = media_filename(message)
    except Exception:
        filename = ""

    size = 0
    if isinstance(message.media, MessageMediaDocument):
        size = (message.media.document.size or 0)
    size_mb = round(size / 1048576, 1)

    cid_str = str(event.chat_id)
    source_label = ""
    rec = state.watched.get(cid_str)
    if isinstance(rec, dict):
        source_label = rec.get("name") or ""

    previous_status = "unknown"
    last_at = None
    if task_id in state.active_downloads:
        previous_status = state.active_downloads[task_id].get("status", "downloading")
    elif task_id in state.pending_tasks:
        previous_status = "queued"
    else:
        for r in state.completed_downloads:
            if r.get("task_id") == task_id and r.get("status") == "done":
                previous_status = "done"
                last_at = r.get("finished_at")
                break

    state.duplicate_queue.append({
        "task_id":            task_id,
        "chat_id":            event.chat_id,
        "message_id":         message.id,
        "filename":           filename,
        "size_mb":            size_mb,
        "source_label":       source_label,
        "last_downloaded_at": last_at,
        "previous_status":    previous_status,
        "queued_at":          datetime.now().isoformat(),
        "grouped_id":         message.grouped_id,
    })
    storage.save_duplicate_queue(state.duplicate_queue)
    _log.info(f"[duplicate] {task_id} 加入待确认队列（previous={previous_status}）")
