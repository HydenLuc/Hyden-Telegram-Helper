# SPDX-License-Identifier: AGPL-3.0-or-later
import re
from pathlib import Path
from telethon.tl.types import (
    MessageMediaDocument, MessageMediaPhoto,
    DocumentAttributeFilename, DocumentAttributeVideo, DocumentAttributeAudio,
    PeerChannel, PeerUser, PeerChat,
    MessageEntityHashtag, MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention,
)


def _format_details_header(message) -> str:
    def peer_str(peer) -> str:
        if isinstance(peer, PeerChannel): return f"频道  ID={peer.channel_id}"
        if isinstance(peer, PeerUser):    return f"用户  ID={peer.user_id}"
        if isinstance(peer, PeerChat):    return f"群组  ID={peer.chat_id}"
        return str(peer)

    L = []
    def w(label, value): L.append(f"{label:<14}{value}")
    def sec(title):      L.extend(["", f"# {title}"])

    sec("基本信息")
    w("消息ID:",    message.id)
    w("发送时间:",  message.date)
    w("文字内容:",  message.message or "（无）")
    w("媒体组ID:",  message.grouped_id or "（无）")
    w("浏览数:",    message.views    or 0)
    w("转发数:",    message.forwards or 0)

    sec("发送者")
    if message.from_id:
        w("发送者:",    peer_str(message.from_id))
    else:
        w("发送者:",    "（匿名 / 频道身份发送）")

    fwd = message.fwd_from
    if fwd:
        sec("转发来源")
        w("转发时间:",  fwd.date)
        if fwd.from_id:
            w("原始来源:",  peer_str(fwd.from_id))
        if getattr(fwd, "from_name", None):
            w("来源名称:",  fwd.from_name)
        if getattr(fwd, "channel_post", None):
            w("原始消息ID:", fwd.channel_post)
        if getattr(fwd, "post_author", None):
            w("帖子作者:",  fwd.post_author)

    if message.entities:
        sec("实体标签")
        txt = message.message or ""
        for ent in message.entities:
            snippet = txt[ent.offset: ent.offset + ent.length]
            if isinstance(ent, MessageEntityHashtag):
                w("Hashtag:",   snippet)
            elif isinstance(ent, MessageEntityUrl):
                w("URL:",       snippet)
            elif isinstance(ent, MessageEntityTextUrl):
                w("链接文字:",  f"{snippet}  →  {ent.url}")
            elif isinstance(ent, MessageEntityMention):
                w("@提及:",     snippet)
            else:
                w(f"{type(ent).__name__}:", snippet)

    L.extend(["", "# 媒体文件列表"])
    return "\n".join(L)


def _format_media_entry(message, file_index: int, filename: str) -> str:
    I = "  "
    lines = [f"\n文件{file_index}:"]

    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        orig_name = None
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                orig_name = attr.file_name
                break
        lines.append(f"{I}文件名:     {orig_name or filename}")
        lines.append(f"{I}大小:       {doc.size / 1048576:.2f} MB")
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                lines.append(f"{I}时长:       {attr.duration} 秒")
                lines.append(f"{I}分辨率:     {attr.w}×{attr.h}")
                if attr.round_message:
                    lines.append(f"{I}视频类型:   圆形视频消息")
            elif isinstance(attr, DocumentAttributeAudio):
                lines.append(f"{I}时长:       {attr.duration} 秒")
                if getattr(attr, "title", None):
                    lines.append(f"{I}标题:       {attr.title}")
                if getattr(attr, "performer", None):
                    lines.append(f"{I}艺术家:     {attr.performer}")
    elif isinstance(message.media, MessageMediaPhoto):
        lines.append(f"{I}文件名:     {filename}")
        photo = message.media.photo
        if hasattr(photo, "sizes") and photo.sizes:
            largest = max(
                (s for s in photo.sizes if hasattr(s, "w")),
                key=lambda s: s.w * s.h, default=None,
            )
            if largest:
                lines.append(f"{I}分辨率:     {largest.w}×{largest.h}")
    else:
        lines.append(f"{I}文件名:     {filename}")

    lines.append(f"{I}原始消息ID: {message.id}")
    return "\n".join(lines)


def _update_detail_counts(detail_path: Path, views: int, fwds: int):
    try:
        content = detail_path.read_text(encoding="utf-8")
        content = re.sub(r'(浏览数:\s+)\d+', lambda m: m.group(1) + str(views), content, count=1)
        content = re.sub(r'(转发数:\s+)\d+', lambda m: m.group(1) + str(fwds),  content, count=1)
        detail_path.write_text(content, encoding="utf-8")
    except Exception:
        pass
