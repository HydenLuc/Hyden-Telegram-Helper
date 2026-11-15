# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import json
from datetime import datetime
from config import (
    WATCHED_FILE,
    COMPLETED_FILE,
    ENV_FILE,
    MAX_HISTORY,
    PENDING_TASKS_FILE,
    GROUPED_STATE_FILE,
    DUPLICATE_QUEUE_FILE,
    CONTENT_INDEX_FILE,
    STATE_DB_FILE,
    HISTORY_JOBS_FILE,
    DOWNLOADER_SETTINGS_FILE,
)
from common.atomic_io import atomic_write_json, atomic_write_text
from common.env_writer import save_env_values
from common.logger import get_logger
from common.settings_store import SettingsStore
from downloader.kvstore import KVStore

_log = get_logger("downloader")

# 模块级单例：路径历史 + use_last_path 偏好
_settings_store = SettingsStore(DOWNLOADER_SETTINGS_FILE, ["download_dir", "watch_path", "move_target"])

# ── 大状态字典：SQLite 增量持久化（2026-08-19）────────────────────────────────
#
# 换掉的**只是写路径**。三个字典照旧整份读进内存、业务代码照旧当普通 dict 用；
# 变的是「改一条就重写 17.7 MB」变成「改一条就 UPDATE 一行」。
# 起因和实测数字见 downloader/kvstore.py 的模块注释。
_kv_pending = KVStore(STATE_DB_FILE, "pending_tasks")
_kv_grouped = KVStore(STATE_DB_FILE, "grouped_state")
_kv_md5     = KVStore(STATE_DB_FILE, "content_md5")
_kv_fuid    = KVStore(STATE_DB_FILE, "content_fuid")


def _migrate_json_to_kv(kv: KVStore, json_path, extract=None) -> None:
    """一次性迁移：库里没数据、但旧 JSON 还在 → 导进去。

    幂等：库里已有数据就直接跳过。**旧 JSON 一律保留不删**——它是回滚路径，
    也是万一 SQLite 出问题时的兜底。等稳定跑一阵再由人决定清不清。
    """
    if kv.count() > 0 or not json_path.exists():
        return
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        _log.error(f"[storage] 迁移 {json_path.name} → SQLite 失败（读不出来）: {e}")
        return
    if extract is not None:
        data = extract(data)
    if not isinstance(data, dict):
        return
    n = kv.import_dict(data)
    _log.info(f"[storage] 已迁移 {json_path.name} → SQLite {kv.table}：{n} 条（旧文件保留）")


def _atomic_write_json(path, data) -> None:
    """向后兼容包装；统一日志前缀。新代码直接 import common.atomic_io.atomic_write_json。"""
    try:
        atomic_write_json(path, data)
    except Exception as e:
        _log.error(f"[downloader] 保存 {path.name} 失败: {e}")


# ── 大状态文件：合并写 + 落盘挪出事件循环（2026-08-14）───────────────────────
#
# 背景：pending_tasks.json 16.5MB、grouped_state.json 25.2MB，而这两个文件在
# 「每次任务状态变化」时都存一次（9 处调用点）。实测单次 dumps+fsync 阻塞事件
# 循环 0.23~0.30 秒；恢复数万个任务时每秒几十次状态变化 → 循环被喂满 →
# /api/status 响应时间抖到 30 秒 → dashboard 10 秒超时判「下载模块离线」→
# 前端「正在下载」整片空白。**页面空白的根因在这里，不在前端。**
#
# 修法两层：
#   ① 合并：DEBOUNCE 秒内的多次保存合并成一次（恢复期把上千次写压成个位数）。
#   ② 分离：json.dumps 仍在事件循环里做（读的是活字典，挪到线程会撞上并发修改），
#      但真正费时的 write+fsync+fsync(dir) 丢给线程池。
#
# ⚠️ 代价：崩溃最多丢 DEBOUNCE 秒内的状态变化。可接受——分块下载靠 .partN 续传、
#    恢复扫描会重新对账；而且原来那种「循环卡死 30 秒」本身就在制造超时和误判。
#    进程退出前 bot.py 会调 flush_now() 兜底（含 SIGTERM）。

_SAVE_DEBOUNCE = 2.0

_dirty: dict = {}          # path -> 活对象引用（dumps 时才快照成字符串）
_flusher_task = None


def _mark_dirty(path, data) -> None:
    """标脏并确保后台合并写任务在跑；拿不到事件循环就退化成同步直写。"""
    global _flusher_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _atomic_write_json(path, data)      # 启动/脚本等无循环场景，保持原行为
        return

    _dirty[path] = data
    if _flusher_task is None or _flusher_task.done():
        _flusher_task = loop.create_task(_flush_loop())


# ── KV（SQLite）侧的防抖调度 ────────────────────────────────────────────────
#
# 和上面 JSON 的防抖是同一套思路，但便宜得多：脏的只有那几个 key，
# 序列化在循环里做（要读活字典），SQL 丢线程池。
_kv_flusher_task = None


_KV_STORES = (_kv_pending, _kv_grouped, _kv_md5, _kv_fuid)


def _schedule_kv_flush() -> None:
    global _kv_flusher_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 启动阶段 / 脚本场景：没有循环，直接同步写
        for kv in _KV_STORES:
            kv.flush_sync()
        return
    if _kv_flusher_task is None or _kv_flusher_task.done():
        _kv_flusher_task = loop.create_task(_kv_flush_loop())


async def _kv_flush_loop() -> None:
    while True:
        await asyncio.sleep(_SAVE_DEBOUNCE)
        if not await _kv_flush_once():
            return          # 没脏数据了就退出，下次标脏时再拉起来


async def _kv_flush_once() -> bool:
    """返回本轮是否有东西要写（用于让空转的 loop 自己退出）。"""
    loop = asyncio.get_running_loop()
    did = False
    for kv in _KV_STORES:
        batch = kv.snapshot()          # 必须在循环里：读的是活字典
        if batch is None:
            continue
        did = True
        await loop.run_in_executor(None, kv.apply, batch)
    return did


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(_SAVE_DEBOUNCE)
        if not _dirty:
            continue
        await _flush_once()


async def _flush_once() -> None:
    batch = dict(_dirty)
    _dirty.clear()
    loop = asyncio.get_running_loop()
    for path, data in batch.items():
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2)   # 在循环里做，避免并发修改
        except Exception as e:
            _log.error(f"[downloader] 序列化 {path.name} 失败: {e}")
            continue
        try:
            await loop.run_in_executor(None, atomic_write_text, path, text)
        except Exception as e:
            _log.error(f"[downloader] 保存 {path.name} 失败: {e}")


async def flush_now() -> None:
    """把所有待写的立刻落盘。退出前 / 关键节点调用。"""
    await _flush_once()
    await _kv_flush_once()


def flush_now_sync() -> None:
    """无事件循环可用时的同步兜底（信号处理器里用）。"""
    batch = dict(_dirty)
    _dirty.clear()
    for path, data in batch.items():
        _atomic_write_json(path, data)
    for kv in _KV_STORES:
        kv.flush_sync()


def load_watched() -> dict:
    """加载 watched_chats.json。

    P1-7 兼容：旧格式 {cid: name(str)} → 新格式
    {cid: {name, watched_since, task_count, task_count_reset_at, exempt}}。
    检测到旧条目即迁移并立即持久化（一次性，下次启动不再迁移）。
    例外字段（exempt）在 dict 格式记录上若缺失则补 False。
    """
    if not WATCHED_FILE.exists():
        return {}
    raw = json.loads(WATCHED_FILE.read_text(encoding="utf-8"))
    needs_save = False
    migrated: dict = {}
    now_iso = datetime.now().isoformat()
    for cid, val in raw.items():
        if isinstance(val, str):
            migrated[cid] = {
                "name": val,
                "watched_since": now_iso,
                "task_count": 0,
                "task_count_reset_at": None,
                "exempt": False,
            }
            needs_save = True
        elif isinstance(val, dict):
            if "exempt" not in val:
                val["exempt"] = False
                needs_save = True
            migrated[cid] = val
    if needs_save:
        save_watched(migrated)
        _log.warning(f"[downloader] watched_chats.json 已迁移（{len(migrated)} 个条目，含 exempt 字段补齐）")
    return migrated


def save_watched(data: dict):
    _atomic_write_json(WATCHED_FILE, data)


def load_completed() -> list:
    if COMPLETED_FILE.exists():
        try:
            data = json.loads(COMPLETED_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            data = data[:MAX_HISTORY]
            for rec in data:
                if "queued_at" not in rec:
                    rec["queued_at"] = rec.get("started_at")
            return data
        except Exception:
            return []
    return []


def save_completed(data: list):
    # 5MB，每次下载完成都存 → 合并写
    _mark_dirty(COMPLETED_FILE, data)


# ── P1-5b: pending_tasks.json ─────────────────────────────────────────────────

def load_pending_tasks() -> dict:
    _migrate_json_to_kv(_kv_pending, PENDING_TASKS_FILE)
    return _kv_pending.load()


def save_pending_tasks(tasks: dict, key=None) -> None:
    """标记 pending_tasks 需要落盘。

    ⚠️ **有 task_id 就一定要传 `key=`**。不传会退化成整表重写——不会丢数据，
    但一次要写数万行，正是本次要消灭的那件事。之所以留这个退路而不强制传参，
    是因为「忘了传 → 写多了」远比「忘了传 → 悄悄没存」安全。
    """
    _kv_pending.mark(tasks, key)
    _schedule_kv_flush()


# ── P1-5b: grouped_state.json ─────────────────────────────────────────────────

def load_grouped_state() -> dict:
    _migrate_json_to_kv(_kv_grouped, GROUPED_STATE_FILE)
    return _kv_grouped.load()


def save_grouped_state(state: dict, key=None) -> None:
    """同 save_pending_tasks：有 group key 就传 `key=`。"""
    _kv_grouped.mark(state, key)
    _schedule_kv_flush()


# ── F6: duplicate_queue.json ──────────────────────────────────────────────────

def load_duplicate_queue() -> list:
    if not DUPLICATE_QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(DUPLICATE_QUEUE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("queue", [])
        return data if isinstance(data, list) else []
    except Exception as e:
        _log.error(f"[downloader] 加载 duplicate_queue.json 失败: {e}")
        return []


def save_duplicate_queue(queue: list) -> None:
    # 每次去重判定都存 → 合并写（注意包了一层 {"queue": ...}，快照是新建的 dict）
    _mark_dirty(DUPLICATE_QUEUE_FILE, {"queue": queue})


# ── MD5 dedup: content_index.json ─────────────────────────────────────────────

def load_content_index() -> dict:
    """content_index 是两层结构 {"md5": {...}, "fuid": {...}}，落成两张表。"""
    _migrate_json_to_kv(_kv_md5,  CONTENT_INDEX_FILE, extract=lambda d: d.get("md5", {}))
    _migrate_json_to_kv(_kv_fuid, CONTENT_INDEX_FILE, extract=lambda d: d.get("fuid", {}))
    return {"md5": _kv_md5.load(), "fuid": _kv_fuid.load()}


def save_content_index(idx: dict, md5_key=None, fuid_key=None) -> None:
    """标记 content_index 需要落盘。

    两层结构分两张表，所以要分别传 `md5_key=` / `fuid_key=`。
    都不传 = 两张表全量重写（同样是安全退路，不是正常路径）。
    """
    md5_live  = idx.get("md5", {})
    fuid_live = idx.get("fuid", {})
    if md5_key is None and fuid_key is None:
        _kv_md5.mark(md5_live, None)
        _kv_fuid.mark(fuid_live, None)
    else:
        if md5_key is not None:
            _kv_md5.mark(md5_live, md5_key)
        if fuid_key is not None:
            _kv_fuid.mark(fuid_live, fuid_key)
    _schedule_kv_flush()


# ── 历史下载: history_jobs.json ────────────────────────────────────────────────

def load_history_jobs() -> dict:
    """加载并自动恢复 status=running → paused（崩溃恢复语义）。

    详见 docs/history-pull-design.md §8.2。
    """
    if not HISTORY_JOBS_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_JOBS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
    except Exception as e:
        _log.error(f"[downloader] 加载 history_jobs.json 失败: {e}")
        return {}
    changed = False
    for job in data.values():
        if isinstance(job, dict) and job.get("status") == "running":
            job["status"] = "paused"
            job["error_msg"] = "进程中断，已自动暂停"
            changed = True
    if changed:
        try:
            atomic_write_json(HISTORY_JOBS_FILE, data)
        except Exception as e:
            _log.warning(f"[downloader] history_jobs running→paused 持久化失败: {e}")
    return data


def save_history_jobs(jobs: dict) -> None:
    _atomic_write_json(HISTORY_JOBS_FILE, jobs)


def save_env_settings(max_total_connections: int, chunk_size: int):
    """向后兼容的固定字段写入器；新代码请直接调 common.env_writer.save_env_values。"""
    try:
        save_env_values(ENV_FILE, {
            "MAX_TOTAL_CONNECTIONS": str(max_total_connections),
            "CHUNK_SIZE":            str(chunk_size),
        })
    except Exception as e:
        _log.warning(f"  ⚠ 保存 .env 失败: {e}")


# ── P1-6: downloader_settings.json (路径历史 + 偏好) ───────────────────────────

def load_settings() -> dict:
    return _settings_store.load()


def save_settings(data: dict) -> None:
    _settings_store.save(data)


def add_path_to_history(settings: dict, field: str, path_str: str) -> None:
    _settings_store.add_to_history(settings, field, path_str)
