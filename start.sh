#!/usr/bin/env bash
# 原生部署（Linux / macOS）一键启动四个模块。Docker 部署用 docker compose，不走这个脚本。
#
# ⚠️ 四个模块的清单只写在下面 MODULES 一处，stop.sh 用同一份。
#    2026-11-11 之前两个脚本各写各的：start.sh 漏了 unzipper（只检查端口、从没启动它），
#    stop.sh 也漏了 unzipper —— 原生部署下载完永远不会解压。
set -euo pipefail

# 进到脚本所在目录。别用 `readlink -f`：macOS 12.3 之前没有这个选项。
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --boot：开机自启时由 launchd / systemd 调用（tools/autostart.py 装的）。
#   · 先等网络（开机时 Wi-Fi / Tailscale 可能还没好，Telegram 连不上下载器会直接退出）
#   · 已经在运行就安静地退出 0（不算错）
BOOT=0
[[ "${1:-}" == "--boot" ]] && BOOT=1
(( BOOT )) && echo "[$(date '+%F %T')] 开机自启：start.sh --boot"

if [[ -t 1 ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; NC=''
fi
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

# 模块清单：名字 | 启动参数 | 端口配置项
#   名字同时用作 pid 文件名和 SERVICE_NAME（日志各写各的 logs/<名字>.log，
#   不设的话四个进程抢同一个 app.log，午夜切分日志时会互相删文件）
MODULES=(
    "downloader|bot.py|WEB_PORT"
    "mover|-m mover.main|MOVER_PORT"
    "unzipper|-m unzipper.main|UNZIPPER_PORT"
    "dashboard|-m dashboard.main|DASHBOARD_PORT"
)

mkdir -p .run logs

# 清理 7 天前的启动日志（避免长期累积塞满磁盘）
find logs/ -name "*-2*.log" -mtime +7 -delete 2>/dev/null || true

# pid 是不是这个模块的进程。⚠️ 不能只看 `kill -0`：断电重启后 pid 文件还在，
# 里面的数字很可能已经被别的程序用了 → 误判「已在运行」拒绝启动（2026-11-13 改）
is_ours() {   # $1=pid  $2=命令行里一定有的串（bot.py / mover.main …）
    local cmd
    cmd=$(ps -p "$1" -o command= 2>/dev/null) || return 1
    [[ "$cmd" == *"$2"* ]]
}

# 1. 检查是否已有进程在跑
for entry in "${MODULES[@]}"; do
    IFS='|' read -r name args _port_key <<< "$entry"
    pidfile=".run/$name.pid"
    if [[ -f "$pidfile" ]]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null && is_ours "$pid" "${args#-m }"; then
            if (( BOOT )); then
                ok "$name 已在运行 (pid=$pid)，开机自启不用再起"
                exit 0
            fi
            err "进程已在运行：$name (pid=$pid)"
            err "请先运行 ./stop.sh 停止后再启动"
            exit 1
        else
            warn "发现陈旧 pid 文件 $pidfile (pid=$pid 已不是本程序)，自动清理"
            rm -f "$pidfile"
        fi
    fi
done
# 旧版脚本的 pid 文件名（downloader 以前叫 bot）
if [[ -f .run/bot.pid ]] && kill -0 "$(cat .run/bot.pid)" 2>/dev/null; then
    err "旧版脚本启动的下载器还在运行 (pid=$(cat .run/bot.pid))，请先运行 ./stop.sh"
    exit 1
fi
rm -f .run/bot.pid

# 2. 检查 .env
if [[ ! -f .env ]]; then
    err ".env 不存在"
    err "请先运行：cp .env.example .env"
    err "然后编辑 .env 填入 API_ID / API_HASH / PHONE 等必填项"
    exit 1
fi

# 3. 检查 .venv
PY=.venv/bin/python
if [[ ! -x $PY ]]; then
    err ".venv 不存在或不完整"
    err "请先运行："
    err "  python3 -m venv .venv"
    err "  .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# 3b. 开机自启：等网络通（最多 120 秒），连的是 Telegram 的一个 DC
if (( BOOT )); then
    for _i in $(seq 1 60); do
        if "$PY" -c "import socket; socket.create_connection(('149.154.167.50', 443), 3).close()" 2>/dev/null; then
            ok "网络已通"
            break
        fi
        (( _i == 60 )) && warn "120 秒网络还没通，照常启动（下载器会自己重连）"
        sleep 2
    done
fi

# 4. 旧版状态文件在项目根目录 → 搬进状态目录（2026-11-11 起状态统一放 STATE_DIR，默认 ./state）
#    只搬新目录里还没有的；同名文件已存在就不动，留给人判断。
#    ⚠️ 故意不搬 pending_tasks.json / grouped_state.json / content_index.json：那是换 SQLite 前的
#    旧快照，进了新目录会被当成「待导入」再导一遍，冒出几万个幽灵任务（2026-09-24 出过事）。
STATE_DIR=$("$PY" -c "import config; print(config.STATE_DIR)" 2>/dev/null || echo "state")
mkdir -p "$STATE_DIR"
for f in userbot.session userbot.session-journal state.db state.db-wal state.db-shm \
         watched_chats.json completed.json duplicate_queue.json history_jobs.json \
         downloader_settings.json unzipper_settings.json unzipper_history.json \
         mover_state.json passwords.json; do
    if [[ -f "$f" && ! -e "$STATE_DIR/$f" ]]; then
        mv "$f" "$STATE_DIR/$f"
        warn "旧位置的 $f 已搬到 $STATE_DIR/"
    fi
done

# 5. 启动
TS=$(date +%Y%m%d-%H%M%S)
declare -a PIDS=() LOGS=()
for entry in "${MODULES[@]}"; do
    IFS='|' read -r name args _port_key <<< "$entry"
    log="logs/${name}-${TS}.log"
    # shellcheck disable=SC2086  # args 故意按空格拆开（"-m mover.main"）
    SERVICE_NAME="$name" nohup "$PY" $args > "$log" 2>&1 &
    pid=$!
    echo "$pid" > ".run/$name.pid"
    PIDS+=("$pid"); LOGS+=("$log")
done

# 6. 等 2 秒，确认进程都还活着
sleep 2
failed=0
i=0
for entry in "${MODULES[@]}"; do
    name=${entry%%|*}
    if kill -0 "${PIDS[$i]}" 2>/dev/null; then
        ok "$name 已启动 (pid=${PIDS[$i]})"
    else
        err "$name 启动失败，查看日志：${LOGS[$i]}"
        rm -f ".run/$name.pid"
        failed=1
    fi
    i=$((i + 1))
done

# 7. 端口监听验证。用 Python 连一下端口，Linux / macOS 通用
#    （原来用 `ss`，macOS 上没有这个命令，永远报未监听）
port_of() { "$PY" -c "import config; print(config.$1)" 2>/dev/null || true; }
port_open() {
    "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(('127.0.0.1', int(sys.argv[1]))))" "$1" 2>/dev/null
}
for entry in "${MODULES[@]}"; do
    IFS='|' read -r name _args port_key <<< "$entry"
    port=$(port_of "$port_key")
    [[ -z $port ]] && continue
    if port_open "$port"; then
        ok "$name 监听 :$port"
    else
        warn "$name 端口 :$port 未监听（可能仍在启动中）"
    fi
done

if [[ $failed -eq 1 ]]; then
    err "部分模块启动失败，请检查上述日志"
    exit 1
fi

echo
ok "全部启动成功"
echo
echo "  Web UI:"
echo "    dashboard   http://localhost:$(port_of DASHBOARD_PORT)  (推荐入口)"
echo "    downloader  http://localhost:$(port_of WEB_PORT)"
echo "    mover       http://localhost:$(port_of MOVER_PORT)"
echo "    unzipper    http://localhost:$(port_of UNZIPPER_PORT)"
echo
echo "  启动日志:"
i=0
for entry in "${MODULES[@]}"; do
    printf "    %-11s %s\n" "${entry%%|*}:" "${LOGS[$i]}"
    i=$((i + 1))
done
echo
echo "  停止：./stop.sh"
