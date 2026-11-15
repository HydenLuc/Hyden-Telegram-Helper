# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import re
from pathlib import Path
from telethon.tl.types import (
    User, Chat, Channel,
    MessageMediaDocument, MessageMediaPhoto,
    DocumentAttributeFilename,
)
from telethon.utils import get_extension

# 路径分隔符 + Windows 不允许的字符 + 全部控制字符（0x00-0x1F、0x7F）。
# 控制字符以前只拦了 \n\r\t：频道名 / 文件名里夹一个 \x0b 之类，Linux 能建，
# 搬到 Windows / SMB 共享上就打不开（2026-11-11 补）。
IS_WINDOWS = os.name == "nt"   # 测试里 monkeypatch 这个

ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')

# Windows 保留设备名：不分大小写，带不带扩展名都不行（"CON.txt" "nul.mp4" 一样建不出来）。
_WIN_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    | {"COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}
)


def _windows_safe(name: str) -> str:
    """只在 Windows 上做的两条修正（2026-11-11）：
    ① 去掉末尾的点和空格——Windows 会**悄悄吞掉**它们，"频道名..." 建出来是 "频道名"，
       程序记的路径和磁盘上的对不上，之后找文件全找不到；
    ② 保留设备名前面加 "_"。

    为什么不在 Linux / macOS 上也做：这两种名字在那边完全合法，而频道名以 "..." 结尾很常见。
    改了的话已有的部署里同一个频道会突然换一个文件夹名，新旧下载分成两处。
    """
    name = name.rstrip(" .")
    if name.split(".", 1)[0].strip().upper() in _WIN_RESERVED:
        name = "_" + name
    return name


# 截断工具搬到 common/pathlimits.py 了（2026-08-19）——unzipper 也要用同一套，
# 两处各留一份迟早分叉。这里 re-export，调用点不用改。
# 为什么是 200 字节、exFAT 为什么特殊，见那个模块的注释。
from common.pathlimits import (   # noqa: F401  （re-export 给现有调用点）
    MAX_NAME_BYTES,
    truncate_bytes,
    truncate_filename,
)


def sanitize(text: str, fallback: str) -> str:
    cleaned = ILLEGAL_RE.sub(' ', text).strip()
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    cleaned = truncate_bytes(cleaned)   # 目录名也要截：频道名同样可能超长
    if IS_WINDOWS:
        cleaned = _windows_safe(cleaned)   # 截断之后再做：截断可能留下新的末尾空格 / 点
    return cleaned if cleaned else fallback


def entity_display_name(entity) -> str:
    if isinstance(entity, User):
        parts = [p for p in (entity.first_name, entity.last_name) if p]
        return " ".join(parts) or entity.username or str(entity.id)
    if isinstance(entity, (Chat, Channel)):
        return entity.title or str(entity.id)
    return str(entity.id)


def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 0
    while True:
        candidate = path.parent / f"{path.name}_{counter:04d}"
        if not candidate.exists():
            return candidate
        counter += 1


def unique_file(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 0
    while True:
        candidate = path.parent / f"{path.stem}_{counter:04d}{path.suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _sanitize_filename(name: str, fallback: str) -> str:
    """file_name 由发送方在消息里自带、完全不可信：可能塞 ../ 或绝对路径逃出
    DOWNLOAD_DIR。先用 sanitize() 去掉 \\/:*?"<>| 等分隔符/非法字符，再去首尾
    空格/点（防裸 ".."/"." 被当作上级目录引用），清空则回退默认名。"""
    cleaned = sanitize(name, fallback).strip(" .")
    if cleaned in ("", ".", ".."):
        return fallback
    # sanitize 已按字节截过，但那是不保扩展名的粗截；这里再按「保留扩展名」重截一次。
    # 顺序不能反：得先去掉非法字符，长度才算得准。
    cleaned = truncate_filename(cleaned)
    if IS_WINDOWS:
        # 重截之后再修一次：截断可能在末尾留下新的空格 / 点
        cleaned = _windows_safe(cleaned) or fallback
    return cleaned


def media_filename(message) -> str:
    if isinstance(message.media, MessageMediaDocument):
        ext = get_extension(message.media.document) or ".bin"
        fallback = f"file_{message.id}{ext}"
        for attr in message.media.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return _sanitize_filename(attr.file_name, fallback)
        return fallback
    if isinstance(message.media, MessageMediaPhoto):
        return f"photo_{message.id}.jpg"
    return f"media_{message.id}"
