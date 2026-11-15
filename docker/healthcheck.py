# SPDX-License-Identifier: AGPL-3.0-or-later
"""Docker 健康检查：调本容器服务的 /api/health（2026-11-13）。

docker-compose.yml 的 healthcheck 调它。按 SERVICE_NAME 找端口；设了 API_KEY 就带上。
只回答「进程活着、能响应」，`docker ps` 里看得到 healthy / unhealthy。
"""
import os
import sys
import urllib.request

PORTS = {"dashboard": 8090, "downloader": 8091, "mover": 8092, "unzipper": 8093, "control": 8094}

port = PORTS.get(os.environ.get("SERVICE_NAME", ""))
if port is None:
    sys.exit(0)          # 不认识的服务（单容器模式等）不判
req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health",
                             headers={"X-API-Key": os.environ.get("API_KEY", "")})
try:
    urllib.request.urlopen(req, timeout=10).read()
except Exception as e:
    print(f"unhealthy: {e}", file=sys.stderr)
    sys.exit(1)
