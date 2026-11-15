# SPDX-License-Identifier: AGPL-3.0-or-later
"""路径分量长度限制：截断工具 + 事后修复。

## 为什么要有这个（2026-08-13 事故）

ZFS / ext4 / XFS / APFS 的单个路径分量上限都是 **255 字节**（不是字符）。
中文 UTF-8 占 3 字节，所以 85 个中文字就到顶。

**exFAT 不一样**：它按 255 个 UTF-16 单元算，一个中文字只占 1 个单元 ——
同一个名字在 exFAT 上能到 700+ 字节，搬到 ZFS 上就建不出来。
2026-08-13 迁移时就是这么炸的：旧机器 exFAT 盘上有个 **288 字节**的乱码目录名
（unzipper 解压 GBK 压缩包时被当 CP437 解出来的），rsync 到 NAS（ZFS）时
mkdir 失败，rsync 只打了一行 `Skipping any contents from this failed directory`
就跳过了**其下 23 个文件 / 21 MB**，**退出码还是 0**。不翻日志根本发现不了。

## 这个模块管什么

- `truncate_bytes` / `truncate_filename`：截断单个分量（downloader 一直在用）
- `fix_long_names`：**事后**扫一棵目录树，把超长的分量改名。
  给 unzipper 用 —— 解压出来的名字来自压缩包内部，不经过 downloader 的任何清洗。

## 为什么 unzipper 只能事后修，不能事前防

`7z x` 没有「解压时改名」的选项。压缩包里那个 288 字节的条目，
7z 会照原样去创建，在 ZFS 上直接 ENAMETOOLONG。
所以做两件事：
  ① 解压前用 `7z l` 扫一遍，发现超长条目就**先告警**（免得后面失败成一个谜）
  ② 解压后走 `fix_long_names` 把落了盘的超长名字改短（防下游的 rsync/备份再踩）
"""
import os
import unicodedata
from pathlib import Path

# 单个路径分量的字节上限。留 55 字节余量给 `_0001` 这类去重后缀和扩展名。
MAX_NAME_BYTES = 200

# 文件系统的硬上限，仅用于日志里说明「为什么 200」
FS_NAME_LIMIT_BYTES = 255


def truncate_bytes(text: str, limit: int = MAX_NAME_BYTES) -> str:
    """按 UTF-8 字节数截断，且只在字符边界切（切半个中文字会变乱码）。"""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    # errors="ignore" 丢掉结尾被切断的半个字符
    return raw[:limit].decode("utf-8", errors="ignore")


def truncate_filename(name: str, limit: int = MAX_NAME_BYTES) -> str:
    """截断文件名但保留扩展名（`.mp4` 丢了播放器就认不出）。

    扩展名本身异常长（可能是文件名里的假点号）时按普通文本截断，不当扩展名处理。
    """
    if len(name.encode("utf-8")) <= limit:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext.encode("utf-8")) > 16 or not stem:
        return truncate_bytes(name, limit)
    keep = limit - len(("." + ext).encode("utf-8"))
    if keep <= 0:
        return truncate_bytes(name, limit)
    return truncate_bytes(stem, keep) + "." + ext


def is_too_long(name: str, limit: int = MAX_NAME_BYTES) -> bool:
    return len(name.encode("utf-8")) > limit


def _unique_in(parent: Path, name: str) -> str:
    """在 parent 下找一个没被占用的名字。冲突时加 `_000` 后缀。

    ⚠️ 后缀也要算进字节预算里，否则「改短」的结果反而可能再次超限。
    """
    if not (parent / name).exists():
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext.encode("utf-8")) > 16 or not stem:
        stem, ext = name, ""
    for i in range(1000):
        suffix = f"_{i:03d}"
        budget = MAX_NAME_BYTES - len(suffix.encode("utf-8")) - (len(("." + ext).encode("utf-8")) if ext else 0)
        cand = truncate_bytes(stem, max(budget, 1)) + suffix + (("." + ext) if ext else "")
        if not (parent / cand).exists():
            return cand
    raise RuntimeError(f"给 {name!r} 找不到可用的短名字（试了 1000 次）")


class WalkFailed(OSError):
    """遍历目录树时出错。**不能当成「树是空的」。**

    存在的理由：`os.walk` 默认把 `onerror` 设成 None，也就是**静默吞掉**
    `PermissionError` 之类的错误，然后若无其事地产出零个条目。
    调用方看到的是「扫完了，没发现问题」——和「真的没问题」一模一样。

    2026-08-20 实测踩到：一台 Mac 上从 SSH 里扫 NFS 挂载目录，
    每一层都是 `Operation not permitted`（macOS TCC 按二进制授权，
    ssh 起的进程不在名单里），扫描器高高兴兴报告「✅ 没有超长分量」。
    这跟本模块要修的那个 rsync 静默跳过是同一类病。
    """


def fix_long_names(root: Path, limit: int = MAX_NAME_BYTES, log=None) -> list[tuple[str, str]]:
    """自底向上扫 root，把超长的路径分量改名。返回 [(旧路径, 新路径), ...]。

    ⚠️ **必须自底向上**（`topdown=False`）：先改父目录的话，
    还没处理的子路径就全失效了。

    只改名字，不动内容、不删东西。改不动的（权限/竞态）记一条错误继续走 ——
    半路抛异常会让「已经改好的」和「没改的」混在一起，比全部跳过更难收拾。

    ⚠️ 但「**整棵树都读不动**」是另一回事，那会抛 `WalkFailed`：
    读不动却返回「没发现问题」是最坏的结果。
    """
    renamed: list[tuple[str, str]] = []
    if not root.exists():
        return renamed

    def _say(msg: str) -> None:
        if log is not None:
            log(msg)

    walk_errors: list[OSError] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, onerror=walk_errors.append):
        parent = Path(dirpath)
        for name in list(filenames) + list(dirnames):
            if not is_too_long(name, limit):
                continue
            src = parent / name
            if not src.exists():          # 可能已被本轮改过（同名出现在两个列表里）
                continue
            short = truncate_filename(name, limit) if src.is_file() else truncate_bytes(name, limit)
            # 截完可能是空的（整个名字都是被切掉的半个字符），给个兜底
            if not short.strip(" ."):
                short = "renamed"
            try:
                final = _unique_in(parent, short)
                dst = parent / final
                src.rename(dst)
                renamed.append((str(src), str(dst)))
                _say(f"[pathlimits] 改名（原名 {len(name.encode('utf-8'))} 字节超上限）：{name!r} → {final!r}")
            except OSError as e:
                _say(f"[pathlimits] ⚠️ 改名失败 {src}: {e}")

    _raise_if_walk_was_blind(root, walk_errors, renamed)
    return renamed


def _raise_if_walk_was_blind(root: Path, errors: list, found) -> None:
    """遍历一个条目都没读到、却有报错 → 说明是权限之类的问题，不是「树是空的」。"""
    if errors and not found:
        first = errors[0]
        raise WalkFailed(
            f"遍历 {root} 失败（{len(errors)} 处报错），**不能据此认为没问题**："
            f"{type(first).__name__}: {first}"
        ) from first


def scan_long_names(root: Path, limit: int = MAX_NAME_BYTES) -> list[tuple[Path, int]]:
    """只扫不改：返回 [(路径, 该分量的字节数), ...]。给巡检脚本用。

    ⚠️ 读不动整棵树时抛 `WalkFailed` 而不是返回空列表 —— 见那个异常的说明。
    """
    out: list[tuple[Path, int]] = []
    if not root.exists():
        return out
    walk_errors: list[OSError] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=walk_errors.append):
        parent = Path(dirpath)
        seen += len(dirnames) + len(filenames)
        for name in list(dirnames) + list(filenames):
            n = len(name.encode("utf-8"))
            if n > limit:
                out.append((parent / name, n))
    _raise_if_walk_was_blind(root, walk_errors, seen)
    return out


def looks_like_mojibake(name: str) -> bool:
    """粗略判断是不是 GBK 被当 CP437 解出来的乱码。

    只用于日志提示——超长名字里很大一部分是这么来的，
    改短能让文件系统收下它，但**名字本身还是乱的**，值得单独说一句。
    判据：拉丁扩展/制表符区的字符占比过半（正常中文/英文名不会这样）。
    """
    if not name:
        return False
    odd = sum(1 for ch in name
              if unicodedata.category(ch) in ("So", "Sk", "Lo", "Ll", "Lu")
              and 0x80 <= ord(ch) <= 0x2FFF
              and not ("一" <= ch <= "鿿"))
    return odd > len(name) * 0.5
