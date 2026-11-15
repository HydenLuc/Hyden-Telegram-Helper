# SPDX-License-Identifier: AGPL-3.0-or-later
"""跨模块共享常量。"""

# 压缩包扩展名（downloader/mover_client、unzipper/utils 共用）
# tar 系列：单后缀变体（.tgz/.tbz2/.txz）+ 多后缀的尾后缀（.gz/.bz2/.xz）
# 注意 .gz/.bz2/.xz 单文件（非 tar 包裹）会被识别为 archive，解压时若非 tar 会
# 抛"不支持格式"被标 extract_failed，不会造成静默错误。
ARCHIVE_EXTS = frozenset({
    ".zip", ".rar", ".7z",
    ".tar", ".tgz", ".tbz2", ".txz",
    ".gz", ".bz2", ".xz",
})
