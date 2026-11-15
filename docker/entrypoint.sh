#!/bin/sh
# 四个模块共用的入口：先做数据盘守卫，再 exec compose 里给的 command。
# 2026-08-12 之前这里直接起三个进程（单容器模式），拆分后改由 compose 的
# command 指定各服务跑什么，本脚本只保留所有服务都要做的前置检查。
set -e

# 数据盘守卫：若设了 DATA_MARKER，该标记文件（存活于外接数据盘上）必须存在，
# 否则说明盘没挂上（bind 挂了空目录）→ 拒绝启动，避免把下载静默写进宿主根文件系统。
# dev（Mac 本地 ./data）不设此变量即跳过；迁到任何主机只需在该机数据盘放同名标记 + compose 里设 DATA_MARKER。
if [ -n "$DATA_MARKER" ] && [ ! -e "$DATA_MARKER" ]; then
  echo "FATAL: 数据盘标记 $DATA_MARKER 不存在——外接数据盘可能未挂载，拒绝启动（防写入根文件系统）。" >&2
  exit 1
fi

# 以指定用户运行（2026-11-13，开源准备）：设了 PUID（可选 PGID）就降权到这个用户，
# 下载出来的文件归你自己，不再是 root。不设 = 跟以前一样用 root。
#   · /state（登录文件、队列、日志，量很小）会被 chown 给这个用户
#   · /data 不动（可能是几 TB 的数据盘）：要保证这个用户对它有写权限
#   · control 服务例外：它要读写 /var/run/docker.sock，必须留在 root
if [ -n "${PUID:-}" ] && [ "$(id -u)" = "0" ] && [ "${SERVICE_NAME:-}" != "control" ]; then
  PGID=${PGID:-$PUID}
  chown -R "$PUID:$PGID" /state 2>/dev/null || echo "[entrypoint] ⚠ chown /state 失败，后面可能写不进状态文件" >&2
  if ! setpriv --reuid="$PUID" --regid="$PGID" --clear-groups test -w /data; then
    echo "[entrypoint] ⚠ 用户 $PUID:$PGID 对 /data 没有写权限，下载会失败。" \
         "在宿主机上把 HOST_DATA_ROOT 那个目录 chown 给它，或者去掉 .env 里的 PUID/PGID" >&2
  fi
  export HOME=/state
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups /app/docker/entrypoint.sh "$@"
fi

cd /state

# 没给 command 时退回单容器模式（四进程合跑），保证 docker run 不带参数仍可用。
# ⚠️ unzipper 必须显式起——2026-08-12 起它已从 bot.py 里摘出来了。
if [ "$#" -eq 0 ]; then
  echo "[entrypoint] 未指定 command，退回单容器模式（mover + unzipper + dashboard + bot 合跑）" >&2
  python -m mover.main &
  python -m unzipper.main &
  python -m dashboard.main &
  exec python /app/bot.py
fi

exec "$@"
