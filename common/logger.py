# SPDX-License-Identifier: AGPL-3.0-or-later
"""统一 logger 配置。

格式：%(asctime)s [%(name)s] %(levelname)s %(message)s
时间：%Y-%m-%d %H:%M:%S
级别：从 config.LOG_LEVEL 读取（默认 INFO，env LOG_LEVEL 覆盖）

输出：
- stdout（由 start.sh 重定向到日志文件，保留旧行为；前台调试也方便）
- 文件 logs/app.log：TimedRotatingFileHandler，每天午夜 rotate
  - backupCount = LOG_KEEP_DAYS（默认 14）
  - 旧文件 gzip 压缩为 app.log.YYYY-MM-DD.gz

"""
import gzip
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import config

_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_configured = False


def _gzip_rotator(source: str, dest: str) -> None:
    """rotate 完成后把旧文件 gzip 压缩，删除原文件。"""
    try:
        with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
            f_out.writelines(f_in)
        os.remove(source)
    except Exception as e:
        # rotation 失败不能阻塞 logger，写到 stderr
        print(f"[logger] 日志 rotate gzip 失败 {source} → {dest}: {e}", file=sys.stderr)


def _gzip_namer(default_name: str) -> str:
    """让 backupCount 计算与 .gz 后缀匹配。"""
    return default_name + ".gz"


_ENTRY_NAMES = {"bot": "downloader", "downloader": "downloader", "mover": "mover",
                "unzipper": "unzipper", "dashboard": "dashboard", "control": "control"}


def _service_name() -> str:
    """日志文件名用的服务名。SERVICE_NAME 优先（start.sh / compose 会设）；
    没设时按启动入口推断（`python bot.py` → downloader，`python -m mover.main` → mover），
    免得手动启动的几个进程共写 app.log、午夜 rotate 时互相删日志（2026-11-13）。
    推断不出来（比如 pytest）才退回 app.log。"""
    svc = os.getenv("SERVICE_NAME", "").strip()
    if svc:
        return svc
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    name = spec.name if spec is not None else Path(getattr(main, "__file__", "") or "").stem
    return _ENTRY_NAMES.get((name or "").split(".")[0], "")


def _build_file_handler() -> logging.handlers.TimedRotatingFileHandler | None:
    """创建文件 handler；目录创建失败则返回 None（仅 stdout 工作）。"""
    try:
        log_dir = Path(getattr(config, "LOG_DIR", Path("logs")))   # 正常是 STATE_DIR/logs
        log_dir.mkdir(parents=True, exist_ok=True)
        # ⚠️ 四个模块拆成独立容器后共用同一个 /state/logs：必须各写各的文件。
        # TimedRotatingFileHandler 是多进程不安全的——同名文件会在午夜 rotate 时
        # 互相重命名/删除对方的日志。SERVICE_NAME 由 compose 按服务注入；
        # 不设时退回 app.log（单进程跑，行为跟以前一样）。
        svc = _service_name()
        log_file = log_dir / (f"{svc}.log" if svc else "app.log")
        keep_days = int(getattr(config, "LOG_KEEP_DAYS", 14))
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",
            backupCount=max(1, keep_days),
            encoding="utf-8",
            delay=True,    # 首次写入时才开 fd
            utc=False,
        )
        handler.rotator = _gzip_rotator
        handler.namer = _gzip_namer
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        return handler
    except Exception as e:
        print(f"[logger] 日志文件 handler 初始化失败: {e}", file=sys.stderr)
        return None


def _ensure_root_configured() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()

    # stdout handler（保留旧行为，与 start.sh 重定向兼容）
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout
               for h in root.handlers):
        root.addHandler(stdout_handler)

    # file handler（按天 rotate + gzip）
    file_handler = _build_file_handler()
    if file_handler is not None:
        # 防重复添加（dev 多次 import）
        if not any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in root.handlers):
            root.addHandler(file_handler)

    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    root.setLevel(level)

    # aiohttp.access 默认每个 HTTP 请求都打 INFO，extract_status 周期任务每 5s
    # 对每个 archive task 调一次 mover /api/tasks/{id}（多数 404 因为 hist 任务
    # 没进 mover），3 天累计可超 24 GB log。降到 WARNING 只保留真正的访问日志
    # 异常（500 等通过 access logger 记录的也保留）。
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取统一配置的 logger。"""
    _ensure_root_configured()
    return logging.getLogger(name)
