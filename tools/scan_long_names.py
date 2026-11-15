#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""巡检：扫数据目录里的超长路径分量。默认只报不改，加 --fix 才动手。

为什么需要：ZFS/APFS 的单分量上限是 255 **字节**，而 exFAT 按 UTF-16 单元算
（同一个中文名在 exFAT 上能到 700+ 字节）。从 exFAT 搬过来的东西、
以及 unzipper 解出来的乱码名，都可能超限。超限的后果是**静默**的 ——
2026-08-13 rsync 遇到一个 288 字节的目录名，只打了一行
`Skipping any contents from this failed directory` 就跳过其下 23 个文件，
**退出码还是 0**。

用法（项目根目录下）：
    python -m tools.scan_long_names                # 扫下载 / 搬运 / 解压三个目录（按 .env 配置）
    python -m tools.scan_long_names --fix          # 扫完顺手改短
    python -m tools.scan_long_names /some/path     # 扫指定目录

⚠️ macOS 上数据在网络盘 / 外接盘时，从 SSH 跑可能没有读取权限（隐私与安全性 →
完全磁盘访问权限）。读不动时脚本会**明确报错并返回 2**，不会假装「没发现问题」——
这正是本脚本要防的那类静默，见 common/pathlimits.WalkFailed。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.pathlimits import (          # noqa: E402
    FS_NAME_LIMIT_BYTES,
    MAX_NAME_BYTES,
    WalkFailed,
    fix_long_names,
    looks_like_mojibake,
    scan_long_names,
)

def default_roots() -> list[Path]:
    """下载 / 搬运 / 解压三个目录，跟程序用的是同一份配置（2026-11-13 去掉写死的路径）。"""
    import config
    return [config.DOWNLOAD_DIR, config.WATCH_PATH, config.OUTPUT_PATH]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", type=Path, default=None)
    ap.add_argument("--fix", action="store_true", help="不只是报告，顺手改短")
    ap.add_argument("--limit", type=int, default=MAX_NAME_BYTES)
    args = ap.parse_args()

    roots = args.roots or default_roots()
    total = 0
    for root in roots:
        if not root.exists():
            print(f"⏭  跳过（不存在）：{root}")
            continue
        print(f"\n=== {root} ===")
        try:
            hits = scan_long_names(root, args.limit)
        except WalkFailed as e:
            # 读不动却报「干净」是最坏的结果——这正是本脚本要防的那类静默
            print(f"  🔴 读不动，本次扫描**无效**（不是「没问题」）：{e}")
            print(f"     多半是 macOS TCC。TCC 按**调用方**授权，换个上下文跑试试：")
            print(f"       · 本机终端 / 已授 FDA 的 SSH")
            print(f"       · 或挂个一次性 LaunchAgent，在 launchd 上下文里跑")
            print(f"     授权入口：系统设置 → 隐私与安全性 → **完全磁盘访问权限**")
            print(f"     （「文件与文件夹」那页没用，非 GUI 进程不会出现在那儿）")
            total = -1
            continue
        if not hits:
            print("  ✅ 没有超长分量")
            continue
        total += len(hits)
        over_fs = [h for h in hits if h[1] > FS_NAME_LIMIT_BYTES]
        print(f"  ⚠️  {len(hits)} 个超过 {args.limit} 字节"
              f"（其中 {len(over_fs)} 个超过文件系统硬上限 {FS_NAME_LIMIT_BYTES}）")
        for p, n in hits[:20]:
            flag = " 🔴超硬上限" if n > FS_NAME_LIMIT_BYTES else ""
            moji = " 疑似乱码" if looks_like_mojibake(p.name) else ""
            print(f"    {n:4d}B{flag}{moji}  …/{p.name[:60]}")
        if len(hits) > 20:
            print(f"    …… 还有 {len(hits) - 20} 个未列出")

        if args.fix:
            renamed = fix_long_names(root, args.limit, log=lambda m: print("  " + m))
            print(f"  ✅ 已改短 {len(renamed)} 个")

    if total < 0:
        print("\n🔴 有目录读不动，本次巡检结论无效。")
        return 2
    print(f"\n合计 {total} 个超长分量。" + ("" if args.fix else " 加 --fix 可以改短。"))
    return 1 if total and not args.fix else 0


if __name__ == "__main__":
    raise SystemExit(main())
