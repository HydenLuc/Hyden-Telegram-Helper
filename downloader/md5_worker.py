# SPDX-License-Identifier: AGPL-3.0-or-later
"""MD5 内容去重 worker。

详见 docs/md5-dedup-design.md。

- _extract_fuid(message): 从 Telegram message 取 fuid_key（document.id / photo.id）
- _md5_sync(file_path): 同步分块计算 MD5（在 executor 跑）
- _compute_and_index(...): 协程，限流 2 并发，算 MD5 + 写索引 / 触发 finish toast
"""
import asyncio
import hashlib
import time
import uuid
from datetime import datetime
from pathlib import Path

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

import downloader.state as state
import downloader.storage as storage
from common.logger import get_logger

_log = get_logger("md5")

# Hole 4 / Q6: MD5 计算限并发，避免 CPU+IO 同时多个大文件压垮
_md5_semaphore = asyncio.Semaphore(2)

# 4 MB 分块读，平衡内存与 IO 调用次数
_MD5_CHUNK = 4 * 1024 * 1024

# Toast 倒计时窗口（秒）
TOAST_TTL_SECONDS = 10


def _extract_fuid(message) -> str | None:
    """document → 'd_<id>'；photo → 'p_<id>'；其他类型返回 None。"""
    media = getattr(message, "media", None)
    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc is not None and getattr(doc, "id", None) is not None:
            return f"d_{doc.id}"
    if isinstance(media, MessageMediaPhoto):
        photo = getattr(media, "photo", None)
        if photo is not None and getattr(photo, "id", None) is not None:
            return f"p_{photo.id}"
    return None


def _md5_sync(file_path: Path) -> str:
    """同步分块计算 MD5。仅在 run_in_executor 中调用。"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(_MD5_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _resolve_source_label(chat_id) -> str:
    if chat_id is None:
        return ""
    rec = state.watched.get(str(chat_id))
    if isinstance(rec, dict):
        return rec.get("name") or ""
    if isinstance(rec, str):
        return rec
    return ""


def _make_toast(*, trigger_source: str, duplicate_type: str,
                task_id: str, chat_id, message_id,
                filename: str, size_mb: float, source_label: str,
                matched_filename: str, matched_path: str, matched_finished_at: str,
                downloaded_path: str | None) -> dict:
    """构造 toast 记录。created_at + expires_at_epoch 由本函数计算。"""
    now = time.time()
    return {
        "toast_id":            str(uuid.uuid4()),
        "trigger_source":      trigger_source,
        "duplicate_type":      duplicate_type,
        "task_id":             task_id,
        "chat_id":             chat_id,
        "message_id":          message_id,
        "filename":            filename,
        "size_mb":             size_mb,
        "source_label":        source_label,
        "matched_filename":    matched_filename,
        "matched_path":        matched_path,
        "matched_finished_at": matched_finished_at,
        "downloaded_path":     downloaded_path,
        "created_at":          datetime.now().isoformat(),
        "expires_at_epoch":    now + TOAST_TTL_SECONDS,
    }


async def _compute_and_index(*, task_id: str, file_path: Path,
                              fuid_key: str | None,
                              filename: str, size: int,
                              chat_id, message_id,
                              source_label: str,
                              finished_at_iso: str) -> None:
    """异步算 MD5 + 写索引；命中已有索引则创建 finish toast。

    Hole 2: 文件被 mover 搬走 → FileNotFoundError 静默放弃，不入索引。
    """
    from downloader.web.websocket import _broadcast

    async with _md5_semaphore:
        loop = asyncio.get_running_loop()
        try:
            md5_hex = await loop.run_in_executor(None, _md5_sync, file_path)
        except FileNotFoundError:
            _log.info(f"[md5] {task_id} 文件已不存在（mover 搬走？），跳过索引")
            return
        except Exception as e:
            _log.warning(f"[md5] {task_id} 计算失败：{type(e).__name__}: {e}")
            return

        existing = state.content_index["md5"].get(md5_hex)
        if existing and existing.get("task_id") != task_id:
            # 命中：创建 finish toast；不写入新索引（保留首次记录）
            toast = _make_toast(
                trigger_source="finish",
                duplicate_type="md5",
                task_id=task_id,
                chat_id=chat_id,
                message_id=message_id,
                filename=filename,
                size_mb=round((size or 0) / 1048576, 1),
                source_label=source_label,
                matched_filename=existing.get("filename", ""),
                matched_path=existing.get("path", ""),
                matched_finished_at=existing.get("finished_at", ""),
                downloaded_path=str(file_path),
            )
            state.pending_toasts.append(toast)
            _log.info(f"[md5] {task_id} MD5 命中已有索引（与 {existing.get('filename')} 相同）→ 创建 finish toast")
            await _broadcast()
            return

        # 未命中：写入索引
        state.content_index["md5"][md5_hex] = {
            "task_id":     task_id,
            "filename":    filename,
            "path":        str(file_path),
            "size":        size or 0,
            "source_label": source_label,
            "finished_at": finished_at_iso,
        }
        if fuid_key:
            state.content_index["fuid"][fuid_key] = md5_hex
        storage.save_content_index(state.content_index, md5_key=md5_hex, fuid_key=fuid_key or None)
        _log.info(f"[md5] {task_id} 新增索引 md5={md5_hex[:8]}...{f' fuid={fuid_key}' if fuid_key else ''}")
