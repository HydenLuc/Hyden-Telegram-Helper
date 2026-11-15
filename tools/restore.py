#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""TGhelper 一键还原。

用法：
    python tools/restore.py <backup.tar.gz>
    python tools/restore.py <backup.tar.gz.age>      # 加密备份，会问密码
    python tools/restore.py <backup> --dry-run       # 只列会怎么处理
    python tools/restore.py <backup> --overwrite     # 覆盖模式（警告：覆盖本机现有）
    python tools/restore.py <backup> --only core     # 只还原指定组
    python tools/restore.py <backup> --skip env_native_mac

默认合并模式：**不覆盖已有，只把备份里有、本机没有的加上**。
- watched_chats.json：按 chat_id 合并，冲突保留本机
- state.db：INSERT OR IGNORE，本机已有记录不动
- completed.json：按 task_id 合并去重
- .env：交互式问 PATH 变量新值；凭证字段保留本机（防老 key 覆盖新的）
- userbot.session：不能合并，问是否覆盖
"""
from __future__ import annotations

import argparse
import getpass
import json
import platform
import shutil
import sqlite3
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from statedir import resolve_state_dir   # 同目录的 tools/statedir.py

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()

# .env 里这些变量在跨平台时几乎必须改路径
PATH_VARS_IN_ENV = {
    "DATA_ROOT", "DOWNLOAD_DIR", "WATCH_PATH", "OUTPUT_PATH",
    "STAGING_DIR", "MOVER_STATE_FILE",
}


def _new_temp_file(suffix: str) -> Path:
    """建一个空临时文件，返回路径。mkstemp 会顺手打开文件，fd 必须关掉——
    不关的话 Windows 上这个文件一直被占着，后面 age/openssl 写不进去、删也删不掉。"""
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(name)


# ── decrypt ──────────────────────────────────────────────────────────────────

def decrypt_if_needed(src: Path) -> Path:
    """返回解密后的本地路径；不加密的话原样返回。调用方负责清理新产生的临时文件。"""
    s = str(src)
    if s.endswith(".age"):
        if not shutil.which("age"):
            print("❌ 备份是 age 加密，本机没装 age（brew install age）"); sys.exit(1)
        password = getpass.getpass("解密密码: ")
        out = _new_temp_file(".tar.gz")
        r = subprocess.run(
            ["age", "-d", "-o", str(out), str(src)],
            input=password + "\n", text=True, capture_output=True,
        )
        if r.returncode != 0:
            out.unlink(missing_ok=True)
            print(f"❌ 解密失败：{r.stderr.strip()}"); sys.exit(1)
        return out

    if s.endswith(".enc"):
        if not shutil.which("openssl"):
            print("❌ 备份是 openssl 加密，本机没 openssl"); sys.exit(1)
        password = getpass.getpass("解密密码: ")
        out = _new_temp_file(".tar.gz")
        r = subprocess.run(
            ["openssl", "aes-256-cbc", "-d", "-salt", "-pbkdf2", "-iter", "100000",
             "-in", str(src), "-out", str(out), "-pass", f"pass:{password}"],
            capture_output=True,
        )
        if r.returncode != 0:
            out.unlink(missing_ok=True)
            print(f"❌ 解密失败：{r.stderr.decode(errors='replace').strip()}"); sys.exit(1)
        return out

    return Path(src)


# ── .env ─────────────────────────────────────────────────────────────────────

def parse_env(path: Path) -> dict[str, str]:
    """解析 KEY=VAL；忽略注释和空行，不保留原始顺序（够用）。"""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def write_env(path: Path, vars: dict[str, str], header: str = "") -> None:
    lines = []
    if header:
        lines.append(header)
    for k, v in vars.items():
        lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def restore_env(src: Path, target: Path, interactive: bool, overwrite: bool) -> None:
    print(f"\n[.env] 合并 → {target}")
    src_vars = parse_env(src)
    target_vars = parse_env(target) if target.exists() else {}

    if overwrite:
        # 直接覆盖
        shutil.copy2(src, target)
        print(f"  ✓ 覆盖模式，直接写入 {len(src_vars)} 个变量")
        return

    merged = dict(target_vars)  # 基于本机，往上加

    for k, v in src_vars.items():
        if k in PATH_VARS_IN_ENV and interactive:
            # 跨平台几乎肯定要改的路径变量：交互式问
            cur = target_vars.get(k, "")
            print(f"  {k}")
            print(f"    备份里的值: {v}")
            if cur:
                print(f"    本机当前值: {cur}")
                new = input(f"    新值（回车=保留本机）: ").strip()
            else:
                new = input(f"    新值（回车=用备份值）: ").strip()
            if new:
                merged[k] = new
            elif not cur:
                merged[k] = v
            # 否则：保留 target 里的
        elif k not in merged:
            # 本机没有 → 补上
            merged[k] = v
        # k 本机已有且非 PATH → 保留本机（防老凭证覆盖新的）

    write_env(target, merged)
    print(f"  ✓ 合并后 {len(merged)} 个变量（本机 {len(target_vars)}，备份 {len(src_vars)}）")


# ── JSON merge ──────────────────────────────────────────────────────────────

def restore_watched(src: Path, target: Path, overwrite: bool) -> None:
    """按顶层 key（chat_id）合并，冲突保留本机。"""
    print(f"\n[watched_chats.json] 合并 → {target}")
    src_data = json.loads(src.read_text(encoding="utf-8"))
    target_data = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    if overwrite:
        target_data = src_data
        added = len(src_data)
    else:
        added = 0
        for k, v in src_data.items():
            if k not in target_data:
                target_data[k] = v
                added += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(target_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 合并后 {len(target_data)} 条（新增 {added}）")


def restore_completed(src: Path, target: Path, overwrite: bool) -> None:
    """按 task_id 合并去重。"""
    print(f"\n[completed.json] 合并 → {target}")
    src_data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(src_data, list):
        print(f"  ⚠ 备份里不是数组，跳过"); return
    target_data = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    if not isinstance(target_data, list):
        target_data = []

    if overwrite:
        target.write_text(json.dumps(src_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✓ 覆盖 {len(src_data)} 条")
        return

    seen = {r.get("task_id") for r in target_data if r.get("task_id")}
    added = 0
    for r in src_data:
        tid = r.get("task_id")
        if tid and tid not in seen:
            target_data.append(r)
            seen.add(tid)
            added += 1
    target.write_text(json.dumps(target_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 合并后 {len(target_data)} 条（新增 {added}）")


def restore_file_if_missing(src: Path, target: Path, label: str, overwrite: bool) -> None:
    """简单策略：目标存在就跳过（或 overwrite 模式直接覆盖）。
    适用于 settings / state 这类整体一致性重要的 JSON。"""
    if target.exists() and not overwrite:
        print(f"  ○ {label}: 已存在，跳过（加 --overwrite 可强制）")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    print(f"  ✓ {label}: 已复制")


# ── SQLite merge ────────────────────────────────────────────────────────────

def restore_state_db(src: Path, target: Path, overwrite: bool) -> None:
    print(f"\n[state.db] 合并 → {target}")
    if overwrite or not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        print(f"  ✓ {'覆盖' if overwrite else '本机没有，直接复制'}")
        return

    tables = ("pending_tasks", "grouped_state", "content_md5", "content_fuid")
    src_con = sqlite3.connect(str(src))
    tgt_con = sqlite3.connect(str(target))
    try:
        for t in tables:
            try:
                rows = src_con.execute(f"SELECT k, v FROM {t}").fetchall()
                before = tgt_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                tgt_con.executemany(f"INSERT OR IGNORE INTO {t} (k, v) VALUES (?, ?)", rows)
                tgt_con.commit()
                after = tgt_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"  ✓ {t}: 本机 {before} → {after}（备份里 {len(rows)} 条，新增 {after-before}）")
            except sqlite3.Error as e:
                print(f"  ✗ {t}: {e}")
    finally:
        src_con.close()
        tgt_con.close()


# ── session（不能合并，只能覆盖/跳过）─────────────────────────────────────

def restore_userbot_session(src: Path, target: Path, interactive: bool, overwrite: bool) -> None:
    print(f"\n[userbot.session] → {target}")
    if target.exists() and not overwrite:
        if interactive:
            print(f"  ⚠ 目标 session 已存在。覆盖 = 把本机 Telegram 登录态替换掉")
            print(f"    备份 size={src.stat().st_size:,}  本机 size={target.stat().st_size:,}")
            choice = input(f"    覆盖？[y/N] ").strip().lower()
            if choice != "y":
                print(f"  ○ 跳过")
                return
        else:
            print(f"  ○ 已存在，跳过（--yes 下不互动；要覆盖加 --overwrite）")
            return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    print(f"  ✓ 已复制")


# ── plist / android ─────────────────────────────────────────────────────────

def restore_plists(stage: Path) -> None:
    plist_dir = stage / "env_native_mac"
    if not plist_dir.exists():
        return
    print(f"\n[plist] mac launchd 服务定义")
    if platform.system() != "Darwin":
        print(f"  ○ 当前系统 {platform.system()} 不是 macOS，跳过 plist")
        print(f"  → 建议 Docker 部署：docker compose up -d")
        return
    target_dir = HOME / "Library" / "LaunchAgents"
    target_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(plist_dir.glob("*.plist")):
        dst = target_dir / p.name
        if dst.exists():
            print(f"  ○ {p.name}: 已存在，跳过")
            continue
        shutil.copy2(p, dst)
        print(f"  ✓ {p.name}（旧备份里的 plist；新装建议改用 python -m tools.autostart on）")


def restore_android(stage: Path) -> None:
    src = stage / "env_android" / "local.properties"
    if not src.exists():
        return
    print(f"\n[android/local.properties]")
    target = PROJECT_ROOT / "android" / "local.properties"
    if target.exists():
        print(f"  ○ 已存在，跳过")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    print(f"  ⚠ 已复制；但 sdk.dir 可能跟本机不符，必要时手动改成本机 Android SDK 路径")


# ── main flow ───────────────────────────────────────────────────────────────

def print_manifest(manifest: dict) -> None:
    print(f"\n═══ 备份摘要 ═══")
    print(f"  版本     : {manifest.get('backup_version')}")
    print(f"  创建时间 : {manifest.get('created_at')}")
    print(f"  源主机   : {manifest.get('hostname')} ({manifest.get('source_os')})")
    print(f"  git HEAD : {manifest.get('tghelper_git_commit') or '（不详）'}")
    print(f"  文件数   : {len(manifest.get('files', []))}")
    groups = sorted({f["group"] for f in manifest.get("files", [])})
    print(f"  含组     : {', '.join(groups)}")
    print(f"  目标系统 : {platform.system()}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("backup",      type=Path, help="备份文件 (.tar.gz / .tar.gz.age / .tar.gz.enc)")
    ap.add_argument("--dry-run",   action="store_true", help="只列会怎么处理，不写")
    ap.add_argument("--overwrite", action="store_true", help="覆盖模式（警告：覆盖本机现有）")
    ap.add_argument("--only",      nargs="+",
                    choices=["core", "feature_state", "env_native_mac", "env_android"],
                    help="只还原指定组")
    ap.add_argument("--skip",      nargs="+", default=[],
                    choices=["core", "feature_state", "env_native_mac", "env_android"],
                    help="跳过指定组")
    ap.add_argument("--yes",       action="store_true", help="不交互（用默认 / 跳过冲突）")
    ap.add_argument("--state-dir", default=None,
                    help="还原到哪个状态目录（默认：环境变量 / .env 里的 STATE_DIR，都没有就是项目里的 state/）")
    args = ap.parse_args()
    state_dir = resolve_state_dir(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    if not args.backup.exists():
        print(f"❌ 备份文件不存在: {args.backup}"); sys.exit(1)

    interactive = not args.yes

    plain = decrypt_if_needed(args.backup)
    plain_was_temp = plain != args.backup

    try:
        with tempfile.TemporaryDirectory() as td:
            with tarfile.open(plain) as tar:
                tar.extractall(td)
            # 找唯一顶层目录
            top = [p for p in Path(td).iterdir() if p.is_dir()]
            if not top:
                print(f"❌ 备份里找不到顶层目录"); sys.exit(1)
            stage = top[0]
            manifest_path = stage / "manifest.json"
            if not manifest_path.exists():
                print(f"❌ 备份里没有 manifest.json"); sys.exit(1)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            print_manifest(manifest)
            print(f"  模式     : {'覆盖' if args.overwrite else '合并（不碰本机已有）'}")
            print(f"  状态目录 : {state_dir}")

            all_groups = {f["group"] for f in manifest["files"]}
            if args.only:
                groups = set(args.only) & all_groups
            else:
                groups = all_groups - set(args.skip)

            print(f"  要还原的组: {', '.join(sorted(groups))}")

            if args.dry_run:
                print(f"\n[DRY-RUN] 会处理这些文件:")
                for f in manifest["files"]:
                    if f["group"] in groups:
                        print(f"  [{f['group']:<16}] {f['path']}")
                return

            if interactive:
                prompt = f"\n继续还原到当前项目 {PROJECT_ROOT}？[y/N] "
                if input(prompt).strip().lower() != "y":
                    print("取消"); return

            # ── core ───
            if "core" in groups:
                print(f"\n═══ core ═══")
                env_src = stage / "core" / ".env"
                if env_src.exists():
                    restore_env(env_src, PROJECT_ROOT / ".env", interactive, args.overwrite)

                # Docker 的「设置页覆盖层」（2026-11-11 起备份里才有）
                overlay_src = stage / "core" / "state-overlay.env"
                if overlay_src.exists():
                    restore_file_if_missing(overlay_src, state_dir / ".env",
                                            "state/.env（设置页覆盖层）", args.overwrite)

                w_src = stage / "core" / "watched_chats.json"
                if w_src.exists():
                    restore_watched(w_src, state_dir / "watched_chats.json", args.overwrite)

                s_src = stage / "core" / "userbot.session"
                if s_src.exists():
                    restore_userbot_session(
                        s_src, state_dir / "userbot.session",
                        interactive, args.overwrite,
                    )

                db_src = stage / "core" / "state.db"
                if db_src.exists():
                    restore_state_db(db_src, state_dir / "state.db", args.overwrite)

            # ── feature_state ───
            if "feature_state" in groups:
                print(f"\n═══ feature_state ═══")
                fs = stage / "feature_state"

                if (fs / "completed.json").exists():
                    restore_completed(fs / "completed.json",
                                      state_dir / "completed.json",
                                      args.overwrite)

                # 其它状态 JSON：目标不存在才复制（避免破坏本机已有的运行状态）
                simple_files = [
                    ("downloader_settings.json", "downloader_settings.json"),
                    ("unzipper_settings.json",   "unzipper_settings.json"),
                    ("unzipper_history.json",    "unzipper_history.json"),
                    ("mover_state.json",         "mover_state.json"),
                    ("duplicate_queue.json",     "duplicate_queue.json"),
                    ("history_jobs.json",        "history_jobs.json"),
                    ("run_state_downloader.json", "run_state_downloader.json"),
                    ("run_state_mover.json",      "run_state_mover.json"),
                    ("run_state_unzipper.json",   "run_state_unzipper.json"),
                    ("dashboard_branding.json",   "dashboard_branding.json"),
                    # 状态目录里的密码库优先；老备份里根目录那份（passwords-root）只在状态目录没有时补上
                    ("passwords-state.json",     "passwords.json"),
                    ("passwords-root.json",      "passwords.json"),
                ]
                print(f"\n[其它 state 文件]")
                for arch_name, rel in simple_files:
                    src = fs / arch_name
                    if src.exists():
                        restore_file_if_missing(src, state_dir / rel, arch_name, args.overwrite)

            # ── env ───
            if "env_native_mac" in groups:
                restore_plists(stage)
            if "env_android" in groups:
                restore_android(stage)

            print(f"\n✅ 还原完成")
            print(f"\n下一步：")
            print(f"  1. 装 Python 依赖:   python -m venv .venv && .venv/bin/pip install -r requirements.txt")
            print(f"  2. 原生启动:         ./start.sh   （要开机自启：python -m tools.autostart on）")
            print(f"     或 Docker 启动:   docker compose up -d")
            print(f"  3. 打开控制台验证:   http://localhost:8090（端口以 .env 为准）")

    finally:
        if plain_was_temp:
            plain.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
