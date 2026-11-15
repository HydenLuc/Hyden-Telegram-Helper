# SPDX-License-Identifier: AGPL-3.0-or-later
"""Toast 后端定时任务：每 1s 扫 pending_toasts，超时按 trigger_source 默认行为兜底。

详见 docs/md5-dedup-design.md §5.3。

- fuid_pending（handle_media / api_download）超时默认 → 加入 duplicate_queue
- finish 超时默认 → no-op 保留（仅移出 pending_toasts）
"""
import asyncio
import time
from datetime import datetime

import downloader.state as state
import downloader.storage as storage
from common.logger import get_logger

_log = get_logger("toast")

CHECK_INTERVAL = 1.0  # 秒


def _enqueue_from_toast(toast: dict) -> bool:
    """把 toast 字段映射到 duplicate_queue 条目。
    复用 F6 的 task_id 去重；返回 True 表示新插入，False 表示已存在。
    """
    task_id = toast.get("task_id")
    if not task_id:
        return False
    if any(d.get("task_id") == task_id for d in state.duplicate_queue):
        return False
    entry = {
        "task_id":             task_id,
        "chat_id":             toast.get("chat_id"),
        "message_id":          toast.get("message_id"),
        "filename":            toast.get("filename", ""),
        "size_mb":             toast.get("size_mb", 0.0),
        "source_label":        toast.get("source_label", ""),
        "last_downloaded_at":  toast.get("matched_finished_at"),
        "previous_status":     "done",
        "queued_at":           datetime.now().isoformat(),
        "grouped_id":          None,
        # MD5 dedup 新字段
        "duplicate_type":      toast.get("duplicate_type"),
        "matched_filename":    toast.get("matched_filename", ""),
        "matched_path":        toast.get("matched_path", ""),
        "matched_finished_at": toast.get("matched_finished_at", ""),
    }
    state.duplicate_queue.append(entry)
    return True


async def _expire_pending_toasts() -> None:
    """单次扫描：处理所有过期 toast。"""
    if not state.pending_toasts:
        return
    now = time.time()
    expired = [t for t in state.pending_toasts if t.get("expires_at_epoch", 0) < now]
    if not expired:
        return

    queue_dirty = False
    for toast in expired:
        src = toast.get("trigger_source")
        # 移出 pending_toasts
        state.pending_toasts = [
            t for t in state.pending_toasts
            if t.get("toast_id") != toast.get("toast_id")
        ]
        if src in ("handle_media", "api_download"):
            if _enqueue_from_toast(toast):
                queue_dirty = True
            _log.info(f"[toast] {toast.get('toast_id','')[:8]} 超时默认入队（{src}/{toast.get('duplicate_type')}）")
        else:  # finish
            _log.info(f"[toast] {toast.get('toast_id','')[:8]} 超时默认保留（finish/md5）")

    if queue_dirty:
        storage.save_duplicate_queue(state.duplicate_queue)

    # 任何过期变化都广播
    from downloader.web.websocket import _broadcast
    await _broadcast()


async def toast_monitor_loop() -> None:
    """周期任务入口。被 main 调度为后台 task。"""
    _log.info(f"toast 监测启动（每 {CHECK_INTERVAL}s 扫描 pending_toasts）")
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)
            await _expire_pending_toasts()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.error(f"toast 监测循环异常：{type(e).__name__}: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
