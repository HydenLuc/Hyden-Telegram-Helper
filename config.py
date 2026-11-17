# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

# 输出里有中文和 emoji。Windows 重定向到文件时默认是 cp1252 / gbk，直接 UnicodeEncodeError
# 把进程带崩；C locale 下的 Linux 也可能这样。统一成 UTF-8，实在编不了的字符替换掉（2026-11-13）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):     # 被替换成不支持 reconfigure 的对象（pytest 捕获等）
        pass


def _detect_docker() -> bool:
    """是否跑在容器里。`TGH_IN_DOCKER=1/0` 可以强制指定（测试用 / 检测不准时兜底）。

    Docker 会在根目录放 /.dockerenv，Podman 放的是 /run/.containerenv，两个都认。
    """
    forced = os.getenv("TGH_IN_DOCKER", "").strip()
    if forced in ("0", "1"):
        return forced == "1"
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


IS_DOCKER = _detect_docker()

# ── .env：读和写必须是同一个文件（2026-11-11 修）────────────────────────────
#
# 设置页 / downloader / unzipper 保存配置时写的都是 ENV_FILE。以前读配置用的是
# 无参数的 load_dotenv()——它从 config.py 所在目录往上找 .env：
#   · 原生部署：config.py 就在项目根，跟 ENV_FILE 碰巧是同一个文件，没问题
#   · Docker：config.py 在 /app，镜像里故意不放 .env，**什么都读不到**；
#     而保存写进的是 /state/.env，没有任何地方读它 → 设置页改了等于白改
#
# 现在：
#   · 原生部署：ENV_FILE = 项目根的 .env，不管从哪个目录启动都读写同一个
#   · Docker：基础配置由 compose 的 env_file（宿主机 .env）注入成环境变量；
#     /state/.env 是「设置页覆盖层」，启动时读进来、盖过宿主机的值，保存才真的生效。
#     但容器里固定的几项（数据目录、监听地址、端口、服务互相寻址）**不许被覆盖层改**，
#     否则一个旧值就能让容器找不到数据盘或者互相连不上。
#     ⚠️ 想恢复用宿主机 .env 里的值：删掉 state/.env 里对应那一行再重启。
_PROJECT_DIR = Path(__file__).resolve().parent

if IS_DOCKER:
    ENV_FILE = Path.cwd() / ".env"          # 容器工作目录是 /state（volume 持久化）
    DOCKER_FIXED_KEYS = frozenset({
        "DATA_ROOT", "LISTEN_HOST",
        "DASHBOARD_PORT", "WEB_PORT", "MOVER_PORT", "UNZIPPER_PORT",
        "WEB_HOST", "MOVER_HOST", "UNZIPPER_HOST",
        "CONTROL_HOST", "CONTROL_PORT",
    })
    for _k, _v in dotenv_values(ENV_FILE).items():
        if _v is not None and _k not in DOCKER_FIXED_KEYS:
            os.environ[_k] = _v
else:
    ENV_FILE = _PROJECT_DIR / ".env"
    DOCKER_FIXED_KEYS = frozenset()
    load_dotenv(ENV_FILE)

# ── 状态目录（2026-11-11）──────────────────────────────────────────────────
#
# 所有「跟用户走」的状态（监听列表、数据库、Telegram 登录文件、日志、解压密码……）
# 都放在 STATE_DIR 下。以前全是相对路径，跟着「程序从哪个目录启动」走：
#   · Docker：工作目录是 /state，刚好对
#   · 原生（start.sh / systemd）：工作目录是项目根，状态文件和代码混在一起，
#     备份工具（tools/backup.py 按 state/ 找）还会漏掉 session 和数据库
#
# 现在：
#   · Docker：固定是容器工作目录 /state（volume 持久化）。**不认 STATE_DIR 环境变量**——
#     宿主机 .env 里误写一个 STATE_DIR，状态就会写到 volume 外面、重建容器全丢
#   · 原生：默认项目里的 state/；可以用 STATE_DIR 指定别处（相对路径按项目根算）
#   · ⚠️ 必须放本地盘：session 和 state.db 都是 SQLite，放 NFS / SMB 上锁不可靠
def _resolve_state_dir() -> Path:
    if IS_DOCKER:
        return Path.cwd().resolve()
    raw = os.getenv("STATE_DIR", "").strip()
    if not raw:
        return _PROJECT_DIR / "state"
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else _PROJECT_DIR / p).resolve()


STATE_DIR = _resolve_state_dir()
STATE_DIR.mkdir(parents=True, exist_ok=True)

# 原生部署从旧版升级上来时，状态文件还在项目根目录：提醒一次（start.sh 会自动搬）
_LEGACY_STATE_NAMES = (
    "userbot.session", "state.db", "watched_chats.json", "completed.json",
    "duplicate_queue.json", "history_jobs.json", "downloader_settings.json",
    "unzipper_settings.json", "unzipper_history.json", "mover_state.json", "passwords.json",
)
if not IS_DOCKER and STATE_DIR != _PROJECT_DIR:
    _left = [n for n in _LEGACY_STATE_NAMES
             if (_PROJECT_DIR / n).exists() and not (STATE_DIR / n).exists()]
    if _left:
        print(f"[config] ⚠ 项目根目录还有旧位置的状态文件：{', '.join(_left)}\n"
              f"         现在状态目录是 {STATE_DIR}，请把它们移过去（./start.sh 启动时会自动搬）",
              file=sys.stderr)

API_ID           = int(os.getenv("API_ID"))
API_HASH         = os.getenv("API_HASH")
PHONE            = os.getenv("PHONE")
# ── DATA_ROOT（推荐）：只选一个根路径，自动派生三个工作目录 ──────────
#    <DATA_ROOT>/telegramDMZ/{download,move,unzip}
#    数据流联动天然成立：downloader 落盘 download/ → mover 搬到 move/
#    （move/ 同时是 unzipper 的监听目录）→ 解压输出 unzip/。
#    显式设置 DOWNLOAD_DIR / WATCH_PATH / OUTPUT_PATH 时以显式值优先（旧部署兼容）。
#
# 没设 DATA_ROOT 时默认 ~/TGhelperFileSystem（2026-11-13，开源准备）。
# 以前是 ~/HydenFileSystem/{Downloads,Archives,Extracted}：带作者名字，结构也和 DATA_ROOT 不一样。
# 老部署里那个目录已经存在、又没设 DATA_ROOT 的，继续用老位置并提示，免得升级后「文件不见了」。
DEFAULT_DATA_ROOT = Path.home() / "TGhelperFileSystem"
_LEGACY_DEFAULT   = Path.home() / "HydenFileSystem"
DATA_ROOT = os.getenv("DATA_ROOT", "").strip()
if DATA_ROOT:
    _DMZ_ROOT = Path(DATA_ROOT) / "telegramDMZ"
    DEFAULT_DOWNLOAD_DIR = _DMZ_ROOT / "download"
    DEFAULT_WATCH_PATH   = _DMZ_ROOT / "move"
    DEFAULT_OUTPUT_PATH  = _DMZ_ROOT / "unzip"
elif _LEGACY_DEFAULT.is_dir() and not DEFAULT_DATA_ROOT.exists():
    DEFAULT_DOWNLOAD_DIR = _LEGACY_DEFAULT / "Downloads"
    DEFAULT_WATCH_PATH   = _LEGACY_DEFAULT / "Archives"
    DEFAULT_OUTPUT_PATH  = _LEGACY_DEFAULT / "Extracted"
    print(f"[config] 提示：沿用旧版默认目录 {_LEGACY_DEFAULT}。新版默认是 {DEFAULT_DATA_ROOT}；"
          f"想换过去就在 .env 里设 DATA_ROOT", file=sys.stderr)
else:
    _DMZ_ROOT = DEFAULT_DATA_ROOT / "telegramDMZ"
    DEFAULT_DOWNLOAD_DIR = _DMZ_ROOT / "download"
    DEFAULT_WATCH_PATH   = _DMZ_ROOT / "move"
    DEFAULT_OUTPUT_PATH  = _DMZ_ROOT / "unzip"
DOWNLOAD_DIR     = Path(os.getenv("DOWNLOAD_DIR", str(DEFAULT_DOWNLOAD_DIR)))
WATCHED_FILE       = STATE_DIR / "watched_chats.json"
COMPLETED_FILE     = STATE_DIR / "completed.json"
PENDING_TASKS_FILE = STATE_DIR / "pending_tasks.json"
GROUPED_STATE_FILE = STATE_DIR / "grouped_state.json"
DUPLICATE_QUEUE_FILE = STATE_DIR / "duplicate_queue.json"
CONTENT_INDEX_FILE = STATE_DIR / "content_index.json"
# 大状态字典的增量持久化库（2026-08-19）。pending_tasks / grouped_state /
# content_index 从「每次变更全量重写 JSON」改成「按 key 写一行 SQLite」，
# 原因和量到的数见 downloader/kvstore.py 的模块注释。
# ⚠️ 和 session 一样必须放**本地盘**，不能放 NFS（SQLite 在网络文件系统上锁不可靠）。
STATE_DB_FILE      = STATE_DIR / "state.db"
HISTORY_JOBS_FILE = STATE_DIR / "history_jobs.json"
HISTORY_JOB_KEEP_DAYS = int(os.getenv("HISTORY_JOB_KEEP_DAYS", "30"))
DOWNLOADER_SETTINGS_FILE = STATE_DIR / "downloader_settings.json"
UNZIPPER_SETTINGS_FILE   = STATE_DIR / "unzipper_settings.json"
# ENV_FILE / IS_DOCKER 在文件开头定义（读 .env 之前就要知道），见那里的注释。
# 停滞超时：连续多少秒零进度就判定卡死、取消本次下载。
#
# 🔴 别再设成 60。2026-09-17 查明的真相：**Telethon 的 flood_sleep_threshold 默认也是 60**，
#    它遇到 ≤60 秒的 FloodWait 会自己静默 sleep 重试，这期间进度当然是零 ——
#    而看门狗的阈值一模一样，只要 Telegram 给一次接近 60 秒的限流，看门狗必然先开枪。
#    大文件请求多、限流重，所以专挑它们死：日志里 363 次超时几乎全是 2.5~3.5 GB 的文件。
#    配合当时「超时就删光 .partN」的 bug，那些文件永远下不完。
# 现在 180 > 60，给 Telethon 的内部重试留足空间；真卡死了 3 分钟也够判定。
DOWNLOAD_TIMEOUT      = int(os.getenv("DOWNLOAD_TIMEOUT", 180))

# 防封号：全局两次「开始下载一个新文件」之间的最小间隔（秒，浮点）。0 = 关闭（默认）。
# 实时下载和历史下载共用这一个节流；JITTER 在间隔上再随机加 0~JITTER 秒。负数按 0 处理。
# 注意：间隔为 0 时整个节流关闭，此时 JITTER 不起作用。
def _nonneg_float(name: str) -> float:
    try:
        return max(0.0, float(os.getenv(name, "0")))
    except ValueError:
        return 0.0


DOWNLOAD_START_INTERVAL = _nonneg_float("DOWNLOAD_START_INTERVAL")
DOWNLOAD_START_JITTER   = _nonneg_float("DOWNLOAD_START_JITTER")

# Telethon 内部自动 sleep 重试的上限。超过这个秒数的 FloodWait 会抛给我们自己处理
# （走 download_one 的 FloodWait 分支，会设 flood_until 让看门狗豁免）。
# ⚠️ 必须**明显小于** DOWNLOAD_TIMEOUT，否则又回到「两个 60 撞车」那种局面。
FLOOD_SLEEP_THRESHOLD = int(os.getenv("FLOOD_SLEEP_THRESHOLD", "60"))
WEB_PORT              = int(os.getenv("WEB_PORT", 8091))
MOVER_PORT            = int(os.getenv("MOVER_PORT", 8092))
UNZIPPER_PORT         = int(os.getenv("UNZIPPER_PORT", 8093))
DASHBOARD_PORT        = int(os.getenv("DASHBOARD_PORT", 8090))
LISTEN_HOST           = os.getenv("LISTEN_HOST", "127.0.0.1")

# ── 服务间寻址（四模块拆成独立容器后用）─────────────────────────────────────
# 默认 127.0.0.1：单进程/单容器/本地开发时四个模块同机，行为跟以前完全一样。
# 拆成多容器时在 compose 里用服务名覆盖（如 MOVER_HOST=mover），走 docker 内部 DNS。
WEB_HOST              = os.getenv("WEB_HOST", "127.0.0.1")        # downloader
MOVER_HOST            = os.getenv("MOVER_HOST", "127.0.0.1")
UNZIPPER_HOST         = os.getenv("UNZIPPER_HOST", "127.0.0.1")
# 控制服务（只在 Docker 部署里有，负责启停本项目容器；见 control/docker_api.py）。
# 不映射端口，只在 compose 内部网络可达。原生部署没有它，面板和停止按钮都隐藏。
CONTROL_HOST          = os.getenv("CONTROL_HOST", "control")
CONTROL_PORT          = int(os.getenv("CONTROL_PORT", 8094))
# 容器「活着但不健康」时由 control 自动重启（2026-11-13）。见 control/autoheal.py
AUTOHEAL              = os.getenv("AUTOHEAL", "true").strip().lower() not in ("0", "false", "no", "off")
AUTOHEAL_INTERVAL     = int(os.getenv("AUTOHEAL_INTERVAL", "60"))   # 秒，最小 15
API_KEY               = os.getenv("API_KEY", "")

# ── 没设访问密码时的安全默认（2026-11-11）──────────────────────────────────
# 空 API_KEY = 所有 /api/ 接口不用密码（包括改设置、删任务、看 Telegram 登录状态）。
#   · 原生部署：LISTEN_HOST 是回环地址就只有本机能连，没问题；
#     改成 0.0.0.0 / 局域网 IP 却没设密码 → **拒绝启动**。确实要这样（比如只在可信内网）
#     就在 .env 里写 ALLOW_NO_API_KEY=1 显式放行。以前只打一行警告，没人会看见。
#   · Docker：容器里必须监听 0.0.0.0（不然别的容器连不上），真正谁能访问由 compose 的
#     ports 决定——默认只映射到宿主机 127.0.0.1。所以这里不拦，只提醒一句：
#     **把端口映射到局域网 / 公网之前先设 API_KEY**。
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
ALLOW_NO_API_KEY      = os.getenv("ALLOW_NO_API_KEY", "").strip().lower() in ("1", "true", "yes")


def _check_api_key_default() -> None:
    if API_KEY or LISTEN_HOST in _LOOPBACK:
        return
    if IS_DOCKER:
        print("[config] 提示：没设 API_KEY。容器里监听 0.0.0.0 是正常的，谁能访问取决于 "
              "docker-compose 的 ports 映射（默认只给宿主机 127.0.0.1）。"
              "要把端口映射到局域网 / 公网，先在 .env 里设 API_KEY。", file=sys.stderr)
        return
    if ALLOW_NO_API_KEY:
        print(f"[config] ⚠ 没设 API_KEY 且监听 {LISTEN_HOST}：已按 ALLOW_NO_API_KEY=1 放行，"
              "能连到这个地址的任何人都能操作全部接口。", file=sys.stderr)
        return
    sys.exit(
        f"[config] ✗ 拒绝启动：LISTEN_HOST={LISTEN_HOST} 不是本机地址，但没设 API_KEY——"
        "局域网里任何人都能改设置、删任务。\n"
        "  三选一：① .env 里设 API_KEY=<一串随机字符>（推荐）\n"
        "          ② LISTEN_HOST 改回 127.0.0.1（只本机用）\n"
        "          ③ 确定是可信内网：.env 里加 ALLOW_NO_API_KEY=1"
    )


_check_api_key_default()
MOVER_MAX_CONCURRENT  = int(os.getenv("MOVER_MAX_CONCURRENT", "3"))
MOVER_MAX_HISTORY     = int(os.getenv("MOVER_MAX_HISTORY", 500))
SMALL_FILE_THRESHOLD_MB         = int(os.getenv("SMALL_FILE_THRESHOLD_MB", 5))
SMALL_FILE_RESERVED_CONNECTIONS = int(os.getenv("SMALL_FILE_RESERVED_CONNECTIONS", 3))
# 历史下载（source="history"）最多占总连接的比例（剩余给实时独占）
HISTORY_CONN_FRACTION           = float(os.getenv("HISTORY_CONN_FRACTION", "0.6"))
# 历史下载的扫描阶段走 takeout 会话（扫得快、几乎不限流；失败自动退回普通会话）。默认关。见 downloader/history/takeout.py
HISTORY_TAKEOUT                 = os.getenv("HISTORY_TAKEOUT", "false").strip().lower() in ("1", "true", "yes", "on")
AUTO_MOVE             = os.getenv("AUTO_MOVE", "true").lower() == "true"
# 重启 / 断电后：RESUME = 恢复成关机前的暂停开关（默认）；PAUSED = 每次都回到出厂默认（下载监听暂停）
# 说明见 common/run_state.py（2026-11-13）
RESTART_MODE          = os.getenv("RESTART_MODE", "RESUME").strip().upper()
if RESTART_MODE not in ("RESUME", "PAUSED"):
    print(f"[config] RESTART_MODE={RESTART_MODE!r} 不认识，按 RESUME 处理", file=sys.stderr)
    RESTART_MODE = "RESUME"
MAX_HISTORY           = int(os.getenv("MAX_HISTORY", 5000))
MAX_TOTAL_CONNECTIONS = int(os.getenv("MAX_TOTAL_CONNECTIONS", 20))
# 块大小：必须是 4 KB 的倍数，最大 1 MB（Telethon iter_download 上限）
CHUNK_SIZE         = min(1048576, max(4096,
                         (int(os.getenv("CHUNK_SIZE", 1048576)) // 4096) * 4096))
FLOOD_RETRY_MAX    = 3
LOG_LEVEL          = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR            = STATE_DIR / "logs"
LOG_KEEP_DAYS      = int(os.getenv("LOG_KEEP_DAYS", "14"))
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID", "").strip()
BOT_TOKEN          = os.getenv("BOT_TOKEN", "").strip()

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

WATCH_PATH  = Path(os.getenv("WATCH_PATH",  str(DEFAULT_WATCH_PATH)))
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", str(DEFAULT_OUTPUT_PATH)))
# DATA_ROOT 模式：三个工作目录一次性建齐（用户选完根路径即得完整 telegramDMZ 结构）
if DATA_ROOT:
    WATCH_PATH.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
# P1-pwd: 密码独立存储到 passwords.json；config.PASSWORDS 保留空 list 仅供 extractor.py:129 fallback
PASSWORDS_FILE         = STATE_DIR / "passwords.json"
PASSWORDS              = []
MAX_CONCURRENT_TASKS   = int(os.getenv("MAX_CONCURRENT_TASKS", "3"))

# 恢复扫描的并发 worker 数（2026-08-18 加）。
#
# 为什么需要：原来 recover_pending_tasks 给**每个** pending 任务都 create_task 一个
# download_one，数万个任务 = 数万个活协程，全部阻塞在同一个 asyncio.Condition
# （连接预算门）上。而 _release_connections 用的是 notify_all —— 每释放一次连接就
# 唤醒全部几万个，各自重新判断条件后再睡回去。
#   实测：单次 notify_all 光排队 20ms；协程本身占 161MB；
#         downloader 78% CPU 只跑 3MB/s；
#         2026-08-18 迁到一台 Mac 后更严重——一个 2.43GB(要 6 条连接)的文件
#         直接卡死不动，零 .partN、零 ESTABLISHED 连接。
#
# 改成 worker 池后活协程数从数万降到这个数，惊群消失。
# ⚠️ 别设太大：每个 worker 会占用连接预算，超过 MAX_TOTAL_CONNECTIONS 就是白排队。
RECOVER_WORKERS        = int(os.getenv("RECOVER_WORKERS", "8"))

# 搁置任务（在 pending 里但没人在下）的周期性重试。
# 为什么需要：recover_pending_tasks **只在启动时跑一次**，跑完还失败的就永远躺着。
# 2026-09-17 实测：11 个大文件任务因此在队列里躺了一个多月，界面上混在「队列」里
# 看着像在排队。配合同日修好的 .partN 保留（超时不再删分块），每次重试都能
# 从断点接着下，大文件才有跑完的一天。
# ⚠️ 别调太短：失败任务会占连接预算，挤掉正常下载。退避是 间隔×2^重试次数，封顶 24h。
STALLED_RETRY_INTERVAL = int(os.getenv("STALLED_RETRY_INTERVAL", "1800"))   # 秒，0 以下会被抬到 60
STALLED_RETRY_BATCH    = int(os.getenv("STALLED_RETRY_BATCH", "3"))        # 每轮最多发起几个

# 分块下载开关（2026-08-18 加，为了在一台 Mac 上定位一个卡死）。
#
# 现象：在 macOS 上原生跑时，任何走分块路径的下载都永久卡在 chunker.py 的 tmp.open()。
#   py-spy 多次采样位置完全固定；单线程、CPU 0%、内存 593MB —— 是阻塞不是忙。
#   ⚠️ 所有孤立复现都失败：同路径单独 open 0.00s、6 协程并发 open 0.01s、
#      加 nolock 重挂后依旧、Telegram 探针能拉数据、dd 写 68MB/s。
#      只有在真实服务进程里才卡。
#
# DISABLE_CHUNKED=1 时 _adaptive_chunks 恒返回 1，走 client.download_media
# 单连接路径（探针已验证该路径可用）。代价是大文件慢，但服务能用。
# 设回 0 即恢复分块。
DISABLE_CHUNKED        = os.getenv("DISABLE_CHUNKED", "0") == "1"
