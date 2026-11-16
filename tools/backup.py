#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""TGhelper 一键备份工具。

打包 TGhelper 的所有「跟用户走」的配置和状态到一个 tar.gz（可选加密），用于：
  - 换机迁移：空机器上 restore.py 一键还原
  - 回滚保险：误删后 restore.py 合并回来
  - 跨平台：带着文件去 Linux / Windows / Docker，还原脚本会交互式问路径

用法：
    python tools/backup.py                    # 默认：不加密，输出到 ~/tghelper-backups/
    python tools/backup.py --encrypt          # age 加密（没装 fallback openssl）
    python tools/backup.py --output /path/x   # 自定义输出位置
    python tools/backup.py --dry-run          # 只列会备什么，不打包

⚠️ 产物敏感性：含 .env（API_KEY/API_HASH/手机号）+ userbot.session（Telegram 登录态），
   这两个合起来 = 账号完整控制权。推荐 --encrypt。
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from statedir import resolve_state_dir   # 同目录的 tools/statedir.py

BACKUP_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parent.parent   # tghelper 根目录
HOME = Path.home()

# ── 备份清单 ─────────────────────────────────────────────────────────────────
# 每条 = (存档内相对路径, 项目根相对的源路径, 分组)
#
# 分组含义：
#   core           = 核心数据，没有就跑不起来
#   feature_state  = 功能状态（去重、历史、密码库等），缺了部分功能退化
#   env_native_mac = mac launchd plist（2026-11-13 起不再生成，旧备份里可能有）
#   env_android    = Android SDK 本地配置；只影响编 APK
#
# 源路径以 "state/" 开头的，实际在**状态目录**里（见 tools/statedir.py，规则同 config.STATE_DIR）；
# 其余按项目根算。
#
# ⚠️ 每条源路径下面 collect_sources() 会 exists 检查，不存在就跳过（不报错）

BACKUP_ITEMS: list[tuple[str, str, str]] = [
    # core
    ("core/userbot.session",         "state/userbot.session",         "core"),
    ("core/.env",                    ".env",                          "core"),
    # Docker 的「设置页覆盖层」：设置页保存的配置写在这里（2026-11-11 起），不备就丢
    ("core/state-overlay.env",       "state/.env",                    "core"),
    # Docker 部署的机器专属 compose 配置（端口绑定等，不进 git）。曾经被别的机器同步过来的
    # 同名文件覆盖、只能照文档重写，才加进来。还原时不自动复制（换台机器多半不适用），见 restore.py
    ("core/docker-compose.override.yml", "docker-compose.override.yml", "core"),
    ("core/watched_chats.json",      "state/watched_chats.json",      "core"),
    # state.db 走 SQLite 在线备份（见 copy_into_stage），产出一个完整的单文件，
    # 所以不再带 -shm / -wal：WAL 里没合并的写入已经包含在快照里了。
    ("core/state.db",                "state/state.db",                "core"),

    # feature_state
    ("feature_state/completed.json",            "state/completed.json",           "feature_state"),
    ("feature_state/downloader_settings.json",  "state/downloader_settings.json", "feature_state"),
    ("feature_state/unzipper_settings.json",    "state/unzipper_settings.json",   "feature_state"),
    ("feature_state/unzipper_history.json",     "state/unzipper_history.json",    "feature_state"),
    ("feature_state/mover_state.json",          "state/mover_state.json",         "feature_state"),
    ("feature_state/duplicate_queue.json",      "state/duplicate_queue.json",     "feature_state"),
    ("feature_state/history_jobs.json",         "state/history_jobs.json",        "feature_state"),
    ("feature_state/passwords-state.json",      "state/passwords.json",           "feature_state"),
    # 各模块的暂停开关（重启 / 断电后恢复用，common/run_state.py，2026-11-13）
    ("feature_state/run_state_downloader.json", "state/run_state_downloader.json", "feature_state"),
    ("feature_state/run_state_mover.json",      "state/run_state_mover.json",      "feature_state"),
    ("feature_state/run_state_unzipper.json",   "state/run_state_unzipper.json",   "feature_state"),
    ("feature_state/dashboard_branding.json",   "state/dashboard_branding.json",   "feature_state"),

    # env_android
    ("env_android/local.properties",            "android/local.properties",       "env_android"),
]

# mac launchd plist：2026-11-13 起不再备份。
# 以前备的是作者自己 Mac 上手写的 plist；现在开机自启由
# `python -m tools.autostart on` 生成，plist 里写的是本机的项目绝对路径，
# 拷到别的机器反而是错的——还原后在新机器上重新开一次就行。
# --no-plist 参数保留（旧脚本还在传），不再有作用。


README_TEMPLATE = """\
TGhelper 备份 · {created_at}
================================================================
hostname : {hostname}
OS       : {source_os}
加密     : {encrypted}
git HEAD : {git_commit}
文件数   : {file_count}
总大小   : {total_size}

包含什么
--------
core/            Telegram 登录态、监听列表、主状态库（必须；少了跑不起来）
                 （Docker 部署还带 docker-compose.override.yml：机器专属，还原时不自动复制）
feature_state/   完成记录、去重索引、解压密码、搬运状态（功能状态）
（不再备份 launchd plist：新机器上 python -m tools.autostart on 重新生成）
env_android/     Android SDK 路径（只有还要编 APK 才用）

怎么还原
--------
在新环境 clone 项目后：
    python tools/restore.py <本备份文件>

默认合并模式（不覆盖已有配置，只补差异）。
加 --overwrite 强制覆盖（空环境用）。
加密备份（扩展名 .age 或 .enc）会提示输入密码。

⚠️ 敏感性
---------
本备份含 .env（API_KEY / API_HASH / 手机号）+ userbot.session（Telegram 登录态）
= 账号完整控制权。别放公共位置、别上传公共云、别发给别人。
"""


# ── helpers ─────────────────────────────────────────────────────────────────

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit_or_none() -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _downloader_port() -> int:
    """下载器端口：环境变量 > 项目 .env > 默认 8091。Docker 部署时是宿主机映射端口 HOST_WEB_PORT。"""
    from statedir import _from_env_file_key
    for key in ("HOST_WEB_PORT", "WEB_PORT"):
        raw = os.getenv(key, "").strip() or _from_env_file_key(PROJECT_ROOT / ".env", key)
        if raw.isdigit():
            return int(raw)
    return 8091


def check_downloader_running(interactive: bool) -> None:
    """跑着 downloader 时 state.db 会在写入。SQLite 走在线备份 API，备下来是一致的，
    但最近几秒的改动可能不在里面——提醒一句，让人决定要不要先停。

    判断方法：本机连一下下载器的 /api/health（任何系统、原生和 Docker 都一样；
    以前只在 macOS 上查 launchctl，2026-11-13 改）。连不上就当没在跑。"""
    import urllib.error
    import urllib.request
    port = _downloader_port()
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3)
    except urllib.error.HTTPError:
        pass                           # 有 HTTP 回应（比如设了 API_KEY 回 401）= 在跑
    except Exception:
        return                         # 连不上 = 没在跑
    print(f"⚠️  下载器还在跑（127.0.0.1:{port} 有响应）；state.db 在线备份是一致的，但最近几秒的改动可能没备进去")
    print("   要完全静止的备份：原生 ./stop.sh，Docker docker compose stop downloader")
    if interactive and input("继续备份？[y/N] ").strip().lower() != "y":
        sys.exit(1)


def copy_into_stage(src: Path, target: Path) -> None:
    """复制一个文件进暂存目录。SQLite 库走在线备份 API。

    直接复制活的 WAL 模式数据库会拿到撕裂快照（主文件和 -wal 不同步）；
    sqlite3 的 backup() 在库被别的进程写着的时候也能拿到一致的快照，
    所以备份前不强制停 downloader。
    """
    if src.suffix == ".db":
        import sqlite3
        src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        dst_con = sqlite3.connect(str(target))
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
            src_con.close()
        shutil.copystat(src, target)
    else:
        shutil.copy2(src, target)


def collect_sources(include_plist: bool, include_android: bool, state_dir: Path):
    """yield (archive_path, source_path, group) —— 只给存在的文件。"""
    for arch, src_rel, group in BACKUP_ITEMS:
        if group == "env_android" and not include_android:
            continue
        src = state_dir / src_rel[len("state/"):] if src_rel.startswith("state/") else PROJECT_ROOT / src_rel
        if src.exists():
            yield arch, src, group



def pick_encrypt_tool() -> str | None:
    """age 优先，fallback openssl；都没 → None（调用方报错退出）。"""
    for tool in ("age", "openssl"):
        if shutil.which(tool):
            return tool
    return None


def encrypt_file(src_path: Path, out_path: Path, tool: str) -> None:
    """同步加密；密码从 getpass 读两次核对。源文件加密后删除。"""
    password = getpass.getpass("加密密码: ")
    confirm  = getpass.getpass("再输一次: ")
    if password != confirm:
        print("❌ 两次密码不一致"); sys.exit(1)
    if not password:
        print("❌ 密码不能为空"); sys.exit(1)

    if tool == "age":
        # age -p 读 stdin 的密码（提示 + 确认两次）
        r = subprocess.run(
            ["age", "-p", "-o", str(out_path), str(src_path)],
            input=f"{password}\n{password}\n", text=True, capture_output=True,
        )
        if r.returncode != 0:
            print(f"❌ age 加密失败: {r.stderr}"); sys.exit(1)
    elif tool == "openssl":
        r = subprocess.run(
            ["openssl", "aes-256-cbc", "-salt", "-pbkdf2", "-iter", "100000",
             "-in", str(src_path), "-out", str(out_path),
             "-pass", f"pass:{password}"],
            capture_output=True,
        )
        if r.returncode != 0:
            print(f"❌ openssl 加密失败: {r.stderr.decode(errors='replace')}")
            sys.exit(1)
    else:
        print(f"❌ 未知加密工具 {tool}"); sys.exit(1)

    src_path.unlink()


# ── main flow ───────────────────────────────────────────────────────────────

def create_backup(output_dir: Path, encrypt: bool, include_plist: bool,
                  include_android: bool, dry_run: bool, state_dir: Path):
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    name  = f"tghelper-backup-{stamp}"

    sources = list(collect_sources(include_plist, include_android, state_dir))

    if dry_run:
        print(f"[DRY-RUN] 会备份到: {output_dir}/{name}.tar.gz{'.age' if encrypt else ''}")
        print(f"[DRY-RUN] 状态目录: {state_dir}")
        print(f"[DRY-RUN] 会包含 {len(sources)} 个文件:\n")
        total = 0
        last_group = None
        for arch, src, group in sources:
            if group != last_group:
                print(f"  ── {group} ──")
                last_group = group
            sz = src.stat().st_size
            total += sz
            print(f"    {arch:<45} {sz:>14,} bytes  ← {src}")
        print(f"\n  总大小: {total:,} bytes ({total / 1024 / 1024:.1f} MB)")
        return None, None

    files_info = []

    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / name
        stage.mkdir()

        for arch, src, group in sources:
            target = stage / arch
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_into_stage(src, target)
            files_info.append({
                "path":   arch,
                "group":  group,
                "size":   target.stat().st_size,
                "sha256": sha256_of(target),
            })

        manifest = {
            "backup_version":      BACKUP_VERSION,
            "created_at":          datetime.now().astimezone().isoformat(timespec="seconds"),
            "hostname":            platform.node(),
            "state_dir":           str(state_dir),
            "source_os":           platform.system(),
            "tghelper_git_commit": git_commit_or_none(),
            "encrypted":           encrypt,
            "files":               files_info,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8",
        )

        total_size = sum(f["size"] for f in files_info)
        (stage / "README.txt").write_text(README_TEMPLATE.format(
            created_at = manifest["created_at"],
            hostname   = manifest["hostname"],
            source_os  = manifest["source_os"],
            encrypted  = "是" if encrypt else "否",
            git_commit = manifest["tghelper_git_commit"] or "（不在 git 里）",
            file_count = len(files_info),
            total_size = f"{total_size:,} bytes ({total_size / 1024 / 1024:.1f} MB)",
        ), encoding="utf-8")

        output_dir.mkdir(parents=True, exist_ok=True)
        tar_path = output_dir / f"{name}.tar.gz"
        with tarfile.open(tar_path, "w:gz", compresslevel=6) as tar:
            tar.add(stage, arcname=name)

        if encrypt:
            tool = pick_encrypt_tool()
            if not tool:
                print("❌ 找不到 age 或 openssl；要么装 age (brew install age) 要么去掉 --encrypt")
                tar_path.unlink(missing_ok=True)
                sys.exit(1)
            ext = ".age" if tool == "age" else ".enc"
            encrypted_path = Path(str(tar_path) + ext)
            encrypt_file(tar_path, encrypted_path, tool)
            tar_path = encrypted_path

        return tar_path, manifest


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--output",      type=Path, default=HOME / "tghelper-backups",
                    help="输出目录（默认 ~/tghelper-backups）")
    ap.add_argument("--encrypt",     action="store_true",
                    help="启用加密（age 优先，openssl fallback）")
    ap.add_argument("--no-plist",    action="store_true",
                    help="（已无作用，保留兼容旧脚本：plist 不再备份）")
    ap.add_argument("--no-android",  action="store_true",
                    help="不含 Android SDK 本地配置")
    ap.add_argument("--state-dir",   default=None,
                    help="状态目录（默认：环境变量 / .env 里的 STATE_DIR，都没有就是项目里的 state/）")
    ap.add_argument("--dry-run",     action="store_true",
                    help="只列会备什么，不打包")
    ap.add_argument("--yes",         action="store_true",
                    help="不交互确认（CI 用；跳过 downloader-running 的追问）")
    args = ap.parse_args()

    if not args.dry_run:
        check_downloader_running(interactive=not args.yes)

    path, manifest = create_backup(
        output_dir      = args.output,
        encrypt         = args.encrypt,
        include_plist   = not args.no_plist,
        include_android = not args.no_android,
        dry_run         = args.dry_run,
        state_dir       = resolve_state_dir(args.state_dir),
    )
    if path is None:    # dry-run
        return

    size = path.stat().st_size
    print()
    print(f"✅ 备份完成")
    print(f"   路径: {path}")
    print(f"   大小: {size:,} bytes ({size / 1024 / 1024:.1f} MB)")
    print(f"   加密: {'是（' + Path(path).suffix.lstrip('.') + '）' if manifest['encrypted'] else '否'}")
    print(f"   文件: {len(manifest['files'])} 个（见 manifest.json）")
    print()
    print(f"还原命令:")
    print(f"   python tools/restore.py {path}")


if __name__ == "__main__":
    main()
