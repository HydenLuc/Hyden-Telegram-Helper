# SPDX-License-Identifier: AGPL-3.0-or-later
"""控制台「设置」页的后端：哪些 .env 配置能在网页上改、怎么校验、怎么保存（#1803）。

- `GET  /api/config`       可编辑配置的「已保存值」+ 哪些还没生效 + 部署模式
- `POST /api/config`       校验并写入 .env；值为空 = 删掉这一行（回到默认）
- `GET  /api/help`         「?」卡片的说明文字（dashboard/help_texts.py）
- `POST /api/notify/test`  用填的（或已保存的）聊天 ID + 机器人 Token 发一条测试通知

## 「已保存」和「正在用」是两回事

大部分配置是各服务**启动时**读一次的，保存只是写进 .env。所以 GET 同时给两样：
  · values：.env 里现在写的（用户刚保存的），表单显示这个
  · pending：已保存、但正在跑的服务还没用上的键 → 前端标「重启后生效」
「正在用」取的是 dashboard 进程启动时的环境变量；各服务是一起启动的，够用。
能热改的（目前只有总连接数）保存时顺手推给下载器，立即生效。

## 不开放的
凭证（API_ID / API_HASH / PHONE / API_KEY）、端口、监听地址、STATE_DIR 这类改错了
页面自己就打不开、或者等于换账号的，永远不放进白名单。清单见 docs/settings-help-plan.md 的 D 组。
"""
import os
import re
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from dotenv import dotenv_values

import config
from common.env_writer import save_env_values
from common.logger import get_logger
from common.peer_sync import post_settings as peer_post_settings
from dashboard.help_texts import HELP

_log = get_logger("dashboard")

# ── 字段规格 ─────────────────────────────────────────────────────────────────
#   "path"                   路径（Docker 下只读）
#   ("int", min, max)        整数
#   ("float", min, max)      小数
#   "bool"                   true / false
#   ("enum", [...])          枚举
#   "pathlist"               逗号分隔的绝对路径（前端一行一个）
#   "chat_id"                Telegram 数字 ID（可带负号，群是 -100…）
#   "secret"                 只写不读（GET 永远返回空，只告诉前端设没设）
# 所有字段都允许留空 = 删掉这一行，回到默认值（Docker 下回到宿主机 .env 的值）。
_EDITABLE_FIELDS: dict[str, Any] = {
    # 数据目录
    "DATA_ROOT":             "path",
    "DOWNLOAD_DIR":          "path",
    "WATCH_PATH":            "path",
    "OUTPUT_PATH":           "path",
    # 性能与行为
    # ⚠️ 上限 64 跟下载器页面、下载器 /api/settings 的钳制一致（以前这里是 100、那边 64，#1803 统一）
    "MAX_TOTAL_CONNECTIONS": ("int", 1, 64),
    "MAX_CONCURRENT_TASKS":  ("int", 1, 20),
    "MOVER_MAX_CONCURRENT":  ("int", 1, 20),
    "DOWNLOAD_TIMEOUT":      ("int", 0, 3600),     # 下限是动态的，见 _min_download_timeout()
    "AUTO_MOVE":             "bool",
    "LOG_LEVEL":             ("enum", ["DEBUG", "INFO", "WARNING", "ERROR"]),
    "RESTART_MODE":          ("enum", ["RESUME", "PAUSED"]),   # 见 common/run_state.py
    "DOWNLOAD_START_INTERVAL": ("float", 0, 600),
    "DOWNLOAD_START_JITTER":   ("float", 0, 600),
    # 高级：下载调度
    "RECOVER_WORKERS":                 ("int", 1, 64),
    "STALLED_RETRY_INTERVAL":          ("int", 60, 86400),
    "STALLED_RETRY_BATCH":             ("int", 1, 50),
    "HISTORY_CONN_FRACTION":           ("float", 0.1, 0.9),
    "HISTORY_TAKEOUT":                 "bool",
    "SMALL_FILE_THRESHOLD_MB":         ("int", 1, 2048),
    "SMALL_FILE_RESERVED_CONNECTIONS": ("int", 0, 63),
    # 解压
    "UNZIPPER_7Z_TIMEOUT":    ("int", 60, 7 * 86400),
    "UNZIPPER_SCAN_INTERVAL": ("float", 2, 3600),
    # 记录保留
    "MAX_HISTORY":           ("int", 100, 100000),
    "MOVER_MAX_HISTORY":     ("int", 50, 100000),
    "HISTORY_JOB_KEEP_DAYS": ("int", 1, 3650),
    "LOG_KEEP_DAYS":         ("int", 1, 3650),
    # 安全 / 通知 / 自愈
    "MOVE_ALLOWED_ROOTS":    "pathlist",
    "ADMIN_CHAT_ID":         "chat_id",
    "BOT_TOKEN":             "secret",
    "AUTOHEAL":              "bool",
}
_PATH_FIELDS = ("DATA_ROOT", "DOWNLOAD_DIR", "WATCH_PATH", "OUTPUT_PATH")
_SECRET_FIELDS = tuple(k for k, v in _EDITABLE_FIELDS.items() if v == "secret")
# 保存时顺手推给正在跑的服务、立即生效的键
_HOT_FIELDS = ("MAX_TOTAL_CONNECTIONS",)

# 搬运白名单里不许写的地方（搬运器自己还有一道更全的黑名单，这里只挡明显写错的）
_SYSTEM_ROOTS = ("/", "/etc", "/bin", "/sbin", "/usr", "/var", "/boot", "/dev", "/proc",
                 "/sys", "/lib", "/lib64", "/root", "/System", "/Library",
                 "/private/etc", "/private/var")

_BOT_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
_CHAT_ID_RE = re.compile(r"^-?\d{3,20}$")


def _min_download_timeout() -> int:
    """下载超时的下限 = 2 × FLOOD_SLEEP_THRESHOLD（默认 120）。

    Telethon 遇到不超过 FLOOD_SLEEP_THRESHOLD 秒的限流会自己静默等待，这期间进度为零；
    超时要是不比它长一截，看门狗就会把「正在等限流」当成卡死杀掉 —— 2026-09-17 那串大文件
    永远下不完的事故就是两个 60 撞车。以前设置页允许填 10，60 这个坑能直接填进去。
    """
    return max(10, 2 * int(config.FLOOD_SLEEP_THRESHOLD))


def _saved_env() -> dict[str, str]:
    """ENV_FILE 里现在写着的值（原生 = 项目 .env；Docker = /state/.env 覆盖层）。"""
    try:
        return {k: (v or "") for k, v in dotenv_values(config.ENV_FILE).items()}
    except OSError:
        return {}


def _effective_value(key: str, saved: dict[str, str]) -> str:
    """表单该显示的值：.env 里写了就用它，没写就用进程环境（Docker 下来自宿主机 .env）。"""
    if key in saved:
        return saved[key]
    return os.environ.get(key, "")


def _resolve_dirs(env: dict[str, str]) -> dict[str, Path]:
    """按 config.py 相同优先级（显式 > DATA_ROOT 派生 > 内置默认）计算三个生效目录。"""
    data_root = (env.get("DATA_ROOT") or "").strip()
    if data_root:
        dmz = Path(data_root) / "telegramDMZ"
        defaults = {"DOWNLOAD_DIR": dmz / "download",
                    "WATCH_PATH":   dmz / "move",
                    "OUTPUT_PATH":  dmz / "unzip"}
    else:
        defaults = {"DOWNLOAD_DIR": config.DEFAULT_DOWNLOAD_DIR,
                    "WATCH_PATH":   config.DEFAULT_WATCH_PATH,
                    "OUTPUT_PATH":  config.DEFAULT_OUTPUT_PATH}
    return {k: Path(env[k]) if (env.get(k) or "").strip() else defaults[k]
            for k in ("DOWNLOAD_DIR", "WATCH_PATH", "OUTPUT_PATH")}


def _validate_dirs_disjoint(dirs: dict[str, Path]) -> str | None:
    """三个目录互不重叠（相等或互为父子都不行）。返回错误信息或 None。"""
    items = [(k, p.expanduser().resolve()) for k, p in dirs.items()]
    for i, (k1, p1) in enumerate(items):
        for k2, p2 in items[i + 1:]:
            if p1 == p2 or p1.is_relative_to(p2) or p2.is_relative_to(p1):
                return f"{k1} 与 {k2} 目录重叠（{p1} ↔ {p2}），会触发重复检测和误触发解压"
    return None


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def validate_field(key: str, raw: Any) -> tuple[str | None, str | None]:
    """校验一个字段。返回 (要写进 .env 的值, 错误)。值为 None 表示「删掉这一行」。"""
    spec = _EDITABLE_FIELDS[key]
    val = "" if raw is None else str(raw).strip()
    if spec == "path" and config.IS_DOCKER:
        return None, ("Docker 部署下数据目录由宿主机映射决定：请修改宿主 .env 的 "
                      "HOST_DATA_ROOT 后执行 docker compose up -d")
    if val == "":
        return None, None
    if spec == "path":
        return val, None
    if spec == "bool":
        if val.lower() not in ("true", "false"):
            return None, f"{key} 只能是 true/false"
        return val.lower(), None
    if spec == "pathlist":
        parts = [p.strip() for p in re.split(r"[,\n]", val) if p.strip()]
        for p in parts:
            if not Path(p).is_absolute():
                return None, f"{key}：「{p}」不是绝对路径"
            norm = "/" + p.strip("/") if p.strip("/") else "/"
            for bad in _SYSTEM_ROOTS:
                if norm == bad or (bad != "/" and norm.startswith(bad + "/")):
                    return None, f"{key}：不能放行系统目录「{p}」"
        return (",".join(parts) or None), None
    if spec == "chat_id":
        if not _CHAT_ID_RE.match(val):
            return None, f"{key} 要填数字 ID（群是 -100 开头的负数）"
        return val, None
    if spec == "secret":
        if not _BOT_TOKEN_RE.match(val):
            return None, f"{key} 格式不对（应该像 123456789:AA…，从 @BotFather 复制）"
        return val, None
    kind = spec[0]
    if kind in ("int", "float"):
        try:
            n = int(val) if kind == "int" else float(val)
        except ValueError:
            return None, f"{key} 必须是{'整数' if kind == 'int' else '数字'}"
        lo, hi = spec[1], spec[2]
        if key == "DOWNLOAD_TIMEOUT":
            lo = _min_download_timeout()
            if n < lo:
                return None, (f"{key} 不能低于 {lo} 秒（Telegram 限流自动等待 "
                              f"{config.FLOOD_SLEEP_THRESHOLD} 秒的 2 倍），否则大文件会被反复误判卡死")
        if not (lo <= n <= hi):
            return None, f"{key} 需在 {_fmt_num(lo)}~{_fmt_num(hi)} 之间"
        return (str(n) if kind == "int" else _fmt_num(n)), None
    if kind == "enum":
        v = val.upper()
        if v not in spec[1]:
            return None, f"{key} 只能是 {'/'.join(spec[1])}"
        return v, None
    return None, f"{key} 规格未知"


def _int_of(key: str, updates: dict[str, str | None], saved: dict[str, str], default: int) -> int:
    """保存后某个整数字段会是多少（用来做跨字段校验）。"""
    if key in updates:
        v = updates[key]
    else:
        v = _effective_value(key, saved) or None
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


def _cross_check(updates: dict[str, str | None], saved: dict[str, str]) -> str | None:
    """几个字段之间的约束：按「保存后会是什么样」来算。"""
    mtc = _int_of("MAX_TOTAL_CONNECTIONS", updates, saved, 20)
    if any(k in updates for k in ("RECOVER_WORKERS", "MAX_TOTAL_CONNECTIONS")):
        rw = _int_of("RECOVER_WORKERS", updates, saved, 8)
        if rw > mtc:
            return f"RECOVER_WORKERS（{rw}）不能超过总连接数 MAX_TOTAL_CONNECTIONS（{mtc}）"
    if any(k in updates for k in ("SMALL_FILE_RESERVED_CONNECTIONS", "MAX_TOTAL_CONNECTIONS")):
        sr = _int_of("SMALL_FILE_RESERVED_CONNECTIONS", updates, saved, 3)
        if sr >= mtc:
            return f"SMALL_FILE_RESERVED_CONNECTIONS（{sr}）必须小于总连接数 MAX_TOTAL_CONNECTIONS（{mtc}）"
    if any(k in _PATH_FIELDS for k in updates):
        merged = {k: _effective_value(k, saved) for k in _PATH_FIELDS}
        merged.update({k: (v or "") for k, v in updates.items() if k in _PATH_FIELDS})
        return _validate_dirs_disjoint(_resolve_dirs(merged))
    return None


def _pending_keys(saved: dict[str, str]) -> list[str]:
    """已保存、但正在跑的服务还没用上的键。"""
    out = []
    for k in _EDITABLE_FIELDS:
        if k in _HOT_FIELDS:
            continue
        if _effective_value(k, saved) != os.environ.get(k, ""):
            out.append(k)
    return sorted(out)


def _restart_hint() -> str:
    return "docker compose restart" if config.IS_DOCKER else "./stop.sh && ./start.sh"


# ── handlers ─────────────────────────────────────────────────────────────────

async def config_get_handler(_request: web.Request) -> web.Response:
    saved = _saved_env()
    values = {k: _effective_value(k, saved) for k in _EDITABLE_FIELDS}
    secrets_set = {k: bool(values[k]) for k in _SECRET_FIELDS}
    for k in _SECRET_FIELDS:
        values[k] = ""          # 只写不读：Token 永远不回传给浏览器
    return web.json_response({
        "docker": config.IS_DOCKER,
        "env_file": str(config.ENV_FILE),
        "values": values,
        "secrets_set": secrets_set,
        "pending": _pending_keys(saved),
        "api_key_set": bool(config.API_KEY),
        "limits": {"DOWNLOAD_TIMEOUT_MIN": _min_download_timeout()},
        "effective_dirs": {
            "DOWNLOAD_DIR": str(config.DOWNLOAD_DIR),
            "WATCH_PATH":   str(config.WATCH_PATH),
            "OUTPUT_PATH":  str(config.OUTPUT_PATH),
        },
        "restart_hint": _restart_hint(),
    })


async def _apply_hot(updates: dict[str, str | None]) -> list[str]:
    """能热改的推给正在跑的服务。返回立即生效了的键。失败不报错（重启后照样生效）。"""
    applied = []
    if "MAX_TOTAL_CONNECTIONS" in updates and updates["MAX_TOTAL_CONNECTIONS"]:
        n = int(updates["MAX_TOTAL_CONNECTIONS"])
        ok = await peer_post_settings(config.WEB_PORT, config.API_KEY,
                                      {"max_total_connections": n},
                                      host=config.WEB_HOST, label="dashboard→downloader")
        if ok:
            os.environ["MAX_TOTAL_CONNECTIONS"] = str(n)
            applied.append("MAX_TOTAL_CONNECTIONS")
    return applied


async def config_post_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效 JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "请求体必须是对象"}, status=400)

    updates: dict[str, str | None] = {}
    for key, raw in body.items():
        if key not in _EDITABLE_FIELDS:
            return web.json_response({"error": f"字段不允许修改：{key}"}, status=400)
        val, err = validate_field(key, raw)
        if err:
            return web.json_response({"error": err}, status=400)
        updates[key] = val

    if not updates:
        return web.json_response({"error": "没有可保存的字段"}, status=400)

    saved = _saved_env()
    err = _cross_check(updates, saved)
    if err:
        return web.json_response({"error": err}, status=400)

    try:
        save_env_values(config.ENV_FILE, updates)
    except Exception as e:
        _log.error(f"[dashboard] 写入 .env 失败: {e}")
        return web.json_response({"error": f"写入 .env 失败：{e}"}, status=500)

    applied = await _apply_hot(updates)
    # 日志只记键名，不记值（BOT_TOKEN 在里面）
    _log.info(f"[dashboard] 设置已保存：{', '.join(sorted(updates))}"
              + (f"；立即生效：{', '.join(applied)}" if applied else ""))
    need_restart = sorted(k for k in updates if k not in applied)
    return web.json_response({
        "saved": sorted(updates),
        "applied_now": applied,
        "need_restart": bool(need_restart),
        "restart_keys": need_restart,
        "restart_hint": _restart_hint(),
    })


async def help_handler(_request: web.Request) -> web.Response:
    return web.json_response(HELP)


async def _send_test(token: str, chat_id: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(url, json={"chat_id": int(chat_id),
                                         "text": "✅ TGhelper 测试通知：能收到这条，崩溃 / 磁盘告警也能收到。"}) as r:
                if r.status == 200:
                    return True, ""
                try:
                    desc = (await r.json()).get("description", "")
                except Exception:
                    desc = ""
                return False, f"Telegram 返回 {r.status}" + (f"：{desc}" if desc else "")
    except Exception as e:
        return False, f"连不上 Telegram：{type(e).__name__}"


async def notify_test_handler(request: web.Request) -> web.Response:
    """用框里填的值发一条测试；框里没填就用已保存的。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    saved = _saved_env()
    chat_id = str(body.get("ADMIN_CHAT_ID") or _effective_value("ADMIN_CHAT_ID", saved)).strip()
    token = str(body.get("BOT_TOKEN") or _effective_value("BOT_TOKEN", saved)).strip()
    if not chat_id:
        return web.json_response({"ok": False, "error": "先填聊天 ID"}, status=400)
    if not _CHAT_ID_RE.match(chat_id):
        return web.json_response({"ok": False, "error": "聊天 ID 要填数字"}, status=400)
    if not token:
        return web.json_response({"ok": False, "error": "没填机器人 Token，没法从这里测（只填聊天 ID 时由下载器用账号代发）"},
                                 status=400)
    if not _BOT_TOKEN_RE.match(token):
        return web.json_response({"ok": False, "error": "机器人 Token 格式不对"}, status=400)
    ok, err = await _send_test(token, chat_id)
    _log.info(f"[dashboard] 测试通知 → {'成功' if ok else '失败：' + err}")
    return web.json_response({"ok": ok, "error": err}, status=200 if ok else 502)
