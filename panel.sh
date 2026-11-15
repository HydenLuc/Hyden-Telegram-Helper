#!/usr/bin/env bash
# 桌面控制面板入口（macOS / Linux）：
# 用浏览器 app 模式打开 dashboard —— 无地址栏独立窗口，体验等同桌面应用。
# 用法：./panel.sh [端口]   （默认 8090；Docker 改过 HOST_DASHBOARD_PORT 就传那个端口）
set -u

PORT="${1:-8090}"
URL="http://localhost:${PORT}"

if ! curl -s -m 2 -o /dev/null "$URL"; then
    echo "⚠ 面板未响应（${URL}）"
    echo "  请先启动服务：./start.sh   或   docker compose up -d"
    exit 1
fi

open_app() { "$1" --app="$URL" >/dev/null 2>&1 & disown 2>/dev/null; exit 0; }

# 优先 app 模式（Chrome / Edge / Chromium 系）
command -v google-chrome        >/dev/null && open_app google-chrome
command -v microsoft-edge      >/dev/null && open_app microsoft-edge
command -v chromium            >/dev/null && open_app chromium
command -v chromium-browser    >/dev/null && open_app chromium-browser
if [ "$(uname)" = "Darwin" ]; then
    for app in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
        [ -x "$app" ] && open_app "$app"
    done
    open "$URL"; exit 0   # 兜底：默认浏览器
fi
xdg-open "$URL" 2>/dev/null || echo "请手动打开 $URL"
