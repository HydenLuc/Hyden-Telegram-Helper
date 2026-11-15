# SPDX-License-Identifier: AGPL-3.0-or-later
"""历史消息下载 job 执行器。

详见 docs/history-pull-design.md。

核心：
- _scan_semaphore(2): 同时运行 scan job 上限
- _history_semaphore(3): 同时排队的历史下载任务上限（流式 spawn）
- 状态机：running → paused/done/error；C 场景扫完 → ready_for_selection
"""
import asyncio
import uuid
from datetime import datetime, timedelta

from telethon.errors import FloodWaitError, FloodPremiumWaitError

import config
import downloader.state as state
import downloader.storage as storage
from downloader.tg.client import client
from downloader.utils import media_filename
from downloader.history.utils import is_downloadable_media, message_size
from downloader.md5_worker import _extract_fuid
from common.logger import get_logger

_log = get_logger("history")

# M9: 同时运行的 scan job 上限
_scan_semaphore = asyncio.Semaphore(2)

# M6: 同时排队的历史下载任务上限（流式控制 active_downloads 膨胀）
_history_semaphore = asyncio.Semaphore(3)

# 每多少条扫描触发一次 last_seen_id / 计数器持久化（与 chunk 边界对齐）
_PERSIST_EVERY = 100


# ── job 持久化辅助 ────────────────────────────────────────────────────────────

def _persist():
    """强制立即持久化全部 history_jobs。"""
    storage.save_history_jobs(state.history_jobs)


def _bump_updated(job: dict) -> None:
    job["updated_at"] = datetime.now().isoformat()


def _maybe_persist(job: dict) -> None:
    """每 _PERSIST_EVERY 条扫描触发一次持久化。"""
    if job["total_scanned"] % _PERSIST_EVERY == 0:
        _bump_updated(job)
        _persist()


# ── 公共预建索引（避免 O(N²) 查重）────────────────────────────────────────────

def _build_dedup_sets() -> tuple[set, set]:
    completed_set = {
        (r.get("chat_id"), r.get("message_id"))
        for r in state.completed_downloads
        if r.get("status") == "done" and r.get("chat_id") is not None
    }
    active_pending_set = {
        (r.get("chat_id"), r.get("message_id"))
        for r in list(state.active_downloads.values()) + list(state.pending_tasks.values())
        if r.get("chat_id") is not None
    }
    return completed_set, active_pending_set


# ── job 创建 ────────────────────────────────────────────────────────────────

async def create_job(scene: str, chat: str, *,
                     filter_type: str | None = None,
                     min_id: int | None = None,
                     max_id: int | None = None,
                     min_date: str | None = None,
                     max_date: str | None = None) -> dict:
    """创建并启动一个 history-pull job。

    返回 job dict（包含解析后的 chat_id、chat_name）。
    解析失败抛 ValueError（外层转 400）。
    """
    if scene not in ("A", "B", "C"):
        raise ValueError(f"invalid scene: {scene}")
    if scene == "B":
        if filter_type not in ("id", "date"):
            raise ValueError("scene B requires filter_type=id|date")
        if filter_type == "id" and (min_id is None and max_id is None):
            raise ValueError("scene B/id requires min_id or max_id")
        if filter_type == "date" and (min_date is None and max_date is None):
            raise ValueError("scene B/date requires min_date or max_date")

    # n2: 创建前 get_entity 校验
    try:
        entity = await client.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
    except Exception as e:
        raise ValueError(f"chat resolve failed: {type(e).__name__}: {e}")

    # 提取 chat_id（兼容 channel/chat/user）
    from telethon.utils import get_peer_id
    chat_id = get_peer_id(entity)
    chat_name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(chat_id)

    job_id = str(uuid.uuid4())
    now_iso = datetime.now().isoformat()
    job = {
        "job_id":           job_id,
        "scene":            scene,
        "chat_id":          chat_id,
        "chat_name":        chat_name,
        "status":           "running",
        "phase":            "scanning",
        "error_msg":        None,
        "last_seen_id":     0,
        "next_task_seq":    0,
        "total_scanned":    0,
        "total_queued":     0,
        "total_skipped":    0,
        "total_duplicates": 0,
        "created_at":       now_iso,
        "updated_at":       now_iso,
        "finished_at":      None,
        # 场景 B
        "filter_type":      filter_type,
        "min_id":           min_id,
        "max_id":           max_id,
        "min_date":         min_date,
        "max_date":         max_date,
        # 场景 C
        "scan_results":     [] if scene == "C" else None,
    }
    state.history_jobs[job_id] = job
    _persist()
    # spawn runner
    t = asyncio.create_task(run_job(job_id))
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)
    return job


# ── job 执行 ────────────────────────────────────────────────────────────────

async def run_job(job_id: str) -> None:
    """job 主循环：A/B 流式下载；C 仅扫描入 scan_results。"""
    from downloader.web.websocket import _broadcast
    job = state.history_jobs.get(job_id)
    if not job:
        return

    completed_set, active_pending_set = _build_dedup_sets()

    async with _scan_semaphore:
        # 二次检查（用户在 sem 等待期间可能 stop/delete）
        job = state.history_jobs.get(job_id)
        if not job or job["status"] != "running":
            return

        kwargs = {"reverse": True}
        # 断点续：min_id 取断点与用户指定 min_id 的最大值
        effective_min = job.get("last_seen_id") or 0
        if job["scene"] == "B" and job.get("filter_type") == "id":
            user_min = job.get("min_id") or 0
            effective_min = max(effective_min, user_min)
            if job.get("max_id"):
                kwargs["max_id"] = job["max_id"]
        if effective_min > 0:
            kwargs["min_id"] = effective_min

        # 日期模式
        client_min_date = None
        if job["scene"] == "B" and job.get("filter_type") == "date":
            if job.get("max_date"):
                try:
                    kwargs["offset_date"] = datetime.fromisoformat(job["max_date"])
                except Exception:
                    pass
            client_min_date = job.get("min_date")  # ISO 字符串

        try:
            async for msg in client.iter_messages(job["chat_id"], **kwargs):
                # 用户停止
                cur = state.history_jobs.get(job_id)
                if not cur or cur["status"] != "running":
                    break

                if not is_downloadable_media(msg):
                    continue
                # 客户端 min_date 过滤（B/date 场景）
                if client_min_date and msg.date.isoformat() < client_min_date:
                    # iter_messages reverse=True 是旧→新，遇到比 min_date 旧的应早跳
                    # 但我们保守 continue（可能旧消息夹杂）
                    continue

                cur["total_scanned"] += 1

                key = (cur["chat_id"], msg.id)
                if key in completed_set or key in active_pending_set:
                    cur["total_skipped"] += 1
                    cur["last_seen_id"] = max(cur["last_seen_id"], msg.id)
                    _maybe_persist(cur)
                    continue

                # fuid 查重
                fuid_key = _extract_fuid(msg)
                duplicate = False
                matched_filename = matched_path = None
                if fuid_key and fuid_key in state.content_index.get("fuid", {}):
                    md5_hex = state.content_index["fuid"][fuid_key]
                    existing = state.content_index.get("md5", {}).get(md5_hex)
                    if existing:
                        duplicate = True
                        matched_filename = existing.get("filename")
                        matched_path = existing.get("path")

                if cur["scene"] in ("A", "B"):
                    # M2/s1: A/B fuid 命中静默跳过 + 计数
                    if duplicate:
                        cur["total_duplicates"] += 1
                        cur["total_skipped"] += 1
                        cur["last_seen_id"] = max(cur["last_seen_id"], msg.id)
                        _maybe_persist(cur)
                        continue
                    # spawn download（M6 流式）
                    await _history_semaphore.acquire()
                    asyncio.create_task(_run_one_history_download(job_id, msg))
                    cur["total_queued"] += 1
                    cur["last_seen_id"] = max(cur["last_seen_id"], msg.id)
                    _maybe_persist(cur)
                else:
                    # C 场景：入 scan_results
                    try:
                        fname = media_filename(msg)
                    except Exception:
                        fname = ""
                    cur["scan_results"].append({
                        "message_id":       msg.id,
                        "filename":         fname,
                        "size_mb":          round(message_size(msg) / 1048576, 1),
                        "date":             msg.date.isoformat() if msg.date else "",
                        "duplicate":        duplicate,
                        "matched_filename": matched_filename,
                        "matched_path":     matched_path,
                        "selected":         False,
                    })
                    if duplicate:
                        cur["total_duplicates"] += 1
                    cur["last_seen_id"] = max(cur["last_seen_id"], msg.id)
                    _maybe_persist(cur)

        except (FloodWaitError, FloodPremiumWaitError) as e:
            cur = state.history_jobs.get(job_id)
            if cur:
                cur["status"] = "paused"
                cur["error_msg"] = f"FloodWait {e.seconds}s"
                _bump_updated(cur)
                _persist()
            await _broadcast()
            _log.warning(f"[history/{job_id[:8]}] FloodWait {e.seconds}s → paused")
            return
        except Exception as e:
            cur = state.history_jobs.get(job_id)
            if cur:
                cur["status"] = "error"
                cur["error_msg"] = f"{type(e).__name__}: {e}"
                _bump_updated(cur)
                _persist()
            await _broadcast()
            _log.error(f"[history/{job_id[:8]}] error: {type(e).__name__}: {e}")
            return

    # 正常结束
    cur = state.history_jobs.get(job_id)
    if not cur:
        return
    if cur["status"] == "running":
        if cur["scene"] == "C":
            cur["status"] = "ready_for_selection"
            cur["phase"] = "scanning"   # phase 维持，标记扫描已完成等用户操作
        else:
            cur["status"] = "done"
            cur["phase"] = "finished"
            cur["finished_at"] = datetime.now().isoformat()
    _bump_updated(cur)
    _persist()
    await _broadcast()
    _log.info(f"[history/{job_id[:8]}] 完成：扫描 {cur['total_scanned']} 排队 {cur['total_queued']} 跳过 {cur['total_skipped']}")


# ── 单条历史下载（被 _scan_semaphore 限流后 spawn）──────────────────────────

async def _run_one_history_download(job_id: str, msg) -> None:
    """启动一条历史消息的下载，下载完成（即 spawn 完成）后 release semaphore。

    注意：这里 release 的时机是 spawn 完成（download_one 接管），不是文件下载完成。
    实际下载耗时由 `_conn_gate`（MAX_TOTAL_CONNECTIONS=20）和 download_one 内部控制。
    `_history_semaphore` 限制的是"排队中的历史任务数"，避免 active_downloads 膨胀。
    """
    from downloader.web.api import _start_api_download
    job = state.history_jobs.get(job_id)
    try:
        if not job:
            return
        seq = job["next_task_seq"]
        job["next_task_seq"] += 1
        # s2: 立即持久化 seq 防撞名
        _bump_updated(job)
        _persist()

        try:
            await _start_api_download(
                msg, job["chat_id"], msg.id,
                task_id_tag=f"hist_{job_id[:8]}",
                task_id_seq=seq,
                source="history",
            )
        except Exception as e:
            _log.warning(f"[history/{job_id[:8]}] spawn 失败 msg_id={msg.id}: {type(e).__name__}: {e}")
    finally:
        _history_semaphore.release()


# ── 控制操作 ────────────────────────────────────────────────────────────────

async def stop_job(job_id: str) -> bool:
    """请求停止 job。runner 在下一个 chunk 边界检查到后退出。"""
    job = state.history_jobs.get(job_id)
    if not job:
        return False
    if job["status"] not in ("running",):
        return False
    job["status"] = "paused"
    job["error_msg"] = None
    _bump_updated(job)
    _persist()
    return True


async def rescan_job(job_id: str) -> bool:
    """重置 last_seen_id + scan_results，重新启动扫描。"""
    job = state.history_jobs.get(job_id)
    if not job:
        return False
    if job["status"] not in ("paused", "done", "error", "ready_for_selection"):
        return False
    job["last_seen_id"] = 0
    job["total_scanned"] = 0
    job["total_queued"] = 0
    job["total_skipped"] = 0
    job["total_duplicates"] = 0
    job["error_msg"] = None
    job["finished_at"] = None
    if job["scene"] == "C":
        job["scan_results"] = []
    job["status"] = "running"
    job["phase"] = "scanning"
    _bump_updated(job)
    _persist()
    t = asyncio.create_task(run_job(job_id))
    state._pending_tasks.add(t)
    t.add_done_callback(state._pending_tasks.discard)
    return True


async def download_selected(job_id: str, message_ids: list[int]) -> dict:
    """C 场景：用户勾选后启动下载。"""
    job = state.history_jobs.get(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    if job["scene"] != "C":
        return {"ok": False, "error": "only scene=C supports download-selected"}
    if job["status"] not in ("ready_for_selection", "done", "paused"):
        return {"ok": False, "error": f"job status={job['status']} not eligible"}

    selected_msgs = [r for r in (job.get("scan_results") or []) if r["message_id"] in set(message_ids)]
    if not selected_msgs:
        return {"ok": False, "error": "no matching scan_results"}

    job["phase"] = "downloading"
    queued = 0
    try:
        # 标记 selected
        for r in (job.get("scan_results") or []):
            if r["message_id"] in set(message_ids):
                r["selected"] = True

        for r in selected_msgs:
            try:
                msg = await client.get_messages(job["chat_id"], ids=r["message_id"])
            except Exception as e:
                _log.warning(f"[history/{job_id[:8]}] get_messages {r['message_id']} 失败: {e}")
                continue
            if msg is None or not getattr(msg, "media", None):
                continue
            await _history_semaphore.acquire()
            seq = job["next_task_seq"]
            job["next_task_seq"] += 1
            asyncio.create_task(_run_one_history_download_from_dl(job_id, msg, seq))
            queued += 1

        # s4: 启动后立即 done，下载完成情况各自走 active/completed
        job["status"] = "done"
        job["phase"] = "finished"
        job["finished_at"] = datetime.now().isoformat()
    finally:
        _bump_updated(job)
        _persist()

    return {"ok": True, "queued": queued}


async def _run_one_history_download_from_dl(job_id: str, msg, seq: int) -> None:
    """download_selected 路径的 spawn helper：seq 已传入，外层管理。"""
    from downloader.web.api import _start_api_download
    try:
        await _start_api_download(
            msg, msg.chat_id if hasattr(msg, "chat_id") and msg.chat_id else state.history_jobs[job_id]["chat_id"], msg.id,
            task_id_tag=f"hist_{job_id[:8]}",
            task_id_seq=seq,
            source="history",
        )
    except Exception as e:
        _log.warning(f"[history/{job_id[:8]}] download_selected spawn 失败 msg_id={msg.id}: {type(e).__name__}: {e}")
    finally:
        _history_semaphore.release()


async def delete_job(job_id: str) -> bool:
    """删除 job。running 的先 stop（实际短暂 paused 等下个 chunk 边界），然后删字典。

    已 spawn 的下载任务不受影响（在 active_downloads 中独立完成）。
    """
    job = state.history_jobs.get(job_id)
    if not job:
        return False
    if job["status"] == "running":
        job["status"] = "paused"
        job["error_msg"] = "删除前自动停止"
        _bump_updated(job)
        _persist()
        # 不等待，直接删；runner 下次 chunk 边界看到 paused 就 break
    state.history_jobs.pop(job_id, None)
    _persist()
    return True


# ── 启动恢复入口 ────────────────────────────────────────────────────────────

def get_summary_payload() -> list[dict]:
    """生成给 WS payload 用的摘要（不含 scan_results 完整列表，仅 count）。"""
    out = []
    for job in state.history_jobs.values():
        d = {k: v for k, v in job.items() if k != "scan_results"}
        d["scan_results_count"] = len(job.get("scan_results") or [])
        out.append(d)
    out.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return out


# ── 自动清理过期 job ──────────────────────────────────────────────────────────

CLEANUP_INTERVAL = 3600   # 每小时跑一次

def _cleanup_old_jobs_once() -> int:
    """删除 status ∈ {done, error, cancelled} 且 finished_at 早于 N 天前的 job。

    返回删除数量。`finished_at` 字段缺失或解析失败时跳过该 job（保守不删）。
    """
    keep_days = max(1, getattr(config, "HISTORY_JOB_KEEP_DAYS", 30))
    cutoff = datetime.now() - timedelta(days=keep_days)
    to_remove: list[str] = []
    for job_id, job in list(state.history_jobs.items()):
        if not isinstance(job, dict):
            continue
        if job.get("status") not in ("done", "error", "cancelled"):
            continue
        fin = job.get("finished_at")
        if not fin:
            continue
        try:
            ts = datetime.fromisoformat(fin)
        except Exception:
            continue
        if ts < cutoff:
            to_remove.append(job_id)
    for job_id in to_remove:
        state.history_jobs.pop(job_id, None)
    if to_remove:
        try:
            storage.save_history_jobs(state.history_jobs)
        except Exception as e:
            _log.warning(f"[history-cleanup] 持久化失败: {e}")
        _log.info(f"[history-cleanup] 清理 {len(to_remove)} 个过期 history job (>{keep_days} 天)")
    return len(to_remove)


async def cleanup_loop() -> None:
    """周期任务：每 CLEANUP_INTERVAL 秒清理一次过期 history job。"""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            _cleanup_old_jobs_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.error(f"[history-cleanup] 循环异常: {type(e).__name__}: {e}")
