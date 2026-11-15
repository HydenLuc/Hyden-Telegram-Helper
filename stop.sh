#!/usr/bin/env bash
# 原生部署（Linux / macOS）一键停止四个模块。Docker 部署用 docker compose stop。
# 模块清单和 start.sh 保持一致（2026-11-11 之前这里漏了 unzipper）。
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -t 1 ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; NC=''
fi
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

if [[ ! -d .run ]]; then
    warn ".run/ 目录不存在，没有运行中的进程需要停止"
    exit 0
fi

# 断电重启后 pid 文件里的数字可能已经是别的程序 → 不核对就会把别人的进程杀掉（2026-11-13 改）
is_ours() {   # $1=pid  $2=命令行里一定有的串
    local cmd
    cmd=$(ps -p "$1" -o command= 2>/dev/null) || return 1
    [[ "$cmd" == *"$2"* ]]
}

stop_one() {
    local name=$1
    local pidfile=".run/$2.pid"
    local pattern=$3

    if [[ ! -f "$pidfile" ]]; then
        warn "$name 未运行（无 ${pidfile}）"
        return
    fi

    local pid
    pid=$(cat "$pidfile")

    if ! kill -0 "$pid" 2>/dev/null || ! is_ours "$pid" "$pattern"; then
        warn "$name pid=$pid 已不是本程序（进程不在了，或断电重启后这个号被别的程序用了），只清理 pid 文件"
        rm -f "$pidfile"
        return
    fi

    echo "正在停止 $name (pid=$pid)..."
    kill -TERM "$pid" 2>/dev/null || true

    # 最多等 10 秒优雅退出（下载器收到 SIGTERM 会先把没落盘的状态写完）
    local i=0
    while (( i < 10 )) && kill -0 "$pid" 2>/dev/null; do
        sleep 1
        i=$(( i + 1 ))
    done

    if kill -0 "$pid" 2>/dev/null; then
        warn "$name 未在 10 秒内退出，发送 SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
        sleep 1
    fi

    rm -f "$pidfile"
    ok "已停止 $name (pid=$pid)"
}

# 先停 dashboard（只是看板），最后停下载器（让它有时间把状态写完）
stop_one "dashboard"   "dashboard"   "dashboard.main"
stop_one "unzipper"    "unzipper"    "unzipper.main"
stop_one "mover"       "mover"       "mover.main"
stop_one "downloader"  "downloader"  "bot.py"
# 旧版 start.sh 启动的下载器 pid 文件叫 bot.pid
[[ -f .run/bot.pid ]] && stop_one "downloader（旧版脚本启动）" "bot" "bot.py"
exit 0
