FROM python:3.12-slim-bookworm

# 系统解压依赖：p7zip（zip/7z）+ unrar（rar，Debian non-free 仓库）
# tzdata：让 .env 里的 TZ 生效（没有它日志永远按 UTC 零点切分，2026-11-13 加）
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends p7zip-full unrar tzdata \
    && rm -rf /var/lib/apt/lists/*

# 依赖层（利用构建缓存：requirements 不变就不重装）
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行时约定：
#   /app   代码（镜像层，只读使用）
#   /state 运行时状态（userbot.session / 各类 *.json 队列 / logs）→ compose 挂 volume 持久化
#   /data  下载数据根（DATA_ROOT）→ compose 里映射宿主机路径（移动硬盘等）
WORKDIR /state
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    DATA_ROOT=/data \
    LISTEN_HOST=0.0.0.0

EXPOSE 8090 8091 8092 8093

ENTRYPOINT ["/app/docker/entrypoint.sh"]
