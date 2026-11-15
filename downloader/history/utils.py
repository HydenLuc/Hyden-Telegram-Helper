# SPDX-License-Identifier: AGPL-3.0-or-later
"""历史消息下载的辅助工具：媒体类型判断、消息大小推断。

详见 docs/history-pull-design.md §3。
"""
from telethon.tl.types import (
    MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage,
    DocumentAttributeSticker, DocumentAttributeAnimated, DocumentAttributeAudio,
)


def is_downloadable_media(message) -> bool:
    """是否值得下载（排除 sticker / gif / voice / 链接卡片 / 纯文字）。"""
    if not getattr(message, "media", None):
        return False
    media = message.media
    if isinstance(media, MessageMediaWebPage):
        return False
    if isinstance(media, MessageMediaPhoto):
        return True
    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc is None:
            return False
        attrs = {type(a) for a in (doc.attributes or [])}
        if DocumentAttributeSticker in attrs:
            return False
        if DocumentAttributeAnimated in attrs:    # GIF
            return False
        for a in (doc.attributes or []):
            if isinstance(a, DocumentAttributeAudio) and getattr(a, "voice", False):
                return False
        return True
    return False


def message_size(message) -> int:
    """推断消息媒体的字节大小。photo 没有可靠 size 字段，返回 0。"""
    media = getattr(message, "media", None)
    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc is not None:
            return getattr(doc, "size", 0) or 0
    return 0
