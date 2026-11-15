# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite 键值存储：给大状态字典做**增量**持久化。

## 为什么要有这层（2026-08-19）

原来 `pending_tasks` / `grouped_state` / `content_index` 都是「整份 dict →
`json.dumps` → 原子重写整个文件」。实测的后果：

    pending_tasks.json（17.7 MB / 41,123 条）的 mtime **每 2 秒推进一次，从不停**

因为每次下载进度更新（`downloaded_bytes`）都会把整个字典标脏。代价三重：

- **磁盘**：约 9 MB/s 持续写、≈780 GB/天 —— 白白磨内置 SSD
- **事件循环**：`json.dumps` 数万条要 0.2~0.6 秒，而它**是在事件循环里做的**
  （见 storage.py 里那段注释：挪进线程会撞上并发修改）。循环被周期性掐住，
  多半也是日志里那些「超过 60s 无进度，取消下载」的成因
- **内存**：每轮产生几十到上百 MB 的临时字符串，堆被撑碎之后 RSS 再也降不回去。
  实测 RSS 在 970 ~ 2,030 MB 之间锯齿，而**活数据其实只有 155 MB**
  （pending 38.5 + grouped 76.2 + content_index 63.0，在旧服务器上逐个加载量的）

改成按 key 增量写之后，「改一条任务的进度」就是一条几十字节的 UPDATE。

## 设计要点

- **读路径完全不变**：启动时 `load()` 一次性读进内存，业务代码还是操作普通 dict。
  这里换掉的只是**写**。省的不是常驻内存，是写放大和它带来的堆碎片。
- **脏键在事件循环里收集，SQL 在线程池里执行**：序列化要读活字典，必须在循环里做
  （否则并发修改）；但脏键通常只有一两个，序列化代价可忽略。真正慢的 SQL 走线程。
- **`mark()` 不传 key 就退化成全量重写**。这是有意的安全默认：将来有人加了新的
  调用点却忘了传 key，结果是「写多了」而不是「丢数据」。
- **删除靠比对活字典**：flush 时 key 不在活字典里就 DELETE。这样 `del d[k]` 之后
  照常调 `save_x(d, key=k)` 就够了，调用点不需要区分增删改。
"""
import json
import sqlite3
import threading
from pathlib import Path

from common.logger import get_logger

_log = get_logger("downloader")

# 全量重写的哨兵：_dirty[table] 是它时表示「整表重写」
_ALL = object()


class KVStore:
    """一张 (key TEXT PRIMARY KEY, value TEXT) 表，值是 JSON 文本。"""

    def __init__(self, db_path: Path, table: str):
        self.db_path = Path(db_path)
        self.table = table
        self._dirty: set | object = set()
        # 标脏时一并记住「活字典是哪个对象」。
        # ⚠️ 别改成去某个全局模块取——那样 save_x(d, key=k) 的 d 就成了摆设，
        #    传进来的字典和 flush 时读的字典一旦不是同一个，flush 会把
        #    「活字典里没有的键」全判成删除，直接删数据（2026-08-19 演练时踩到）。
        self._live: dict | None = None
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ── 连接 ──────────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False：写在线程池里做，读在主线程。
            # 所有访问都过 self._lock，不会真的并发。
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL：崩溃时最多丢最后一个事务。本来就接受丢 2 秒（见 storage.py
            # 的防抖注释），换来的是不用每次 fsync。
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} "
                "(k TEXT PRIMARY KEY, v TEXT NOT NULL)"
            )
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── 读 ────────────────────────────────────────────────────────────────
    def load(self) -> dict:
        """整表读进内存。表不存在或空则返回 {}。"""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(f"SELECT k, v FROM {self.table}").fetchall()
            except sqlite3.Error as e:
                _log.error(f"[kvstore] 读 {self.table} 失败: {e}")
                return {}
        out = {}
        for k, v in rows:
            try:
                out[k] = json.loads(v)
            except Exception:
                # 单行坏掉不该让整个表读不出来——跳过并记下来
                _log.error(f"[kvstore] {self.table} 的 key={k!r} 反序列化失败，已跳过")
        return out

    def count(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0]
            except sqlite3.Error:
                return 0

    # ── 标脏 ──────────────────────────────────────────────────────────────
    def mark(self, live: dict, key=None) -> None:
        """标记某个 key 需要落盘；key=None 表示整表重写（安全兜底）。

        `live` 是这份数据的活字典，flush 时从它取值、并据它判断删除。
        """
        self._live = live
        if self._dirty is _ALL:
            return
        if key is None:
            self._dirty = _ALL
        else:
            self._dirty.add(key)

    def has_dirty(self) -> bool:
        return self._dirty is _ALL or bool(self._dirty)

    # ── 写 ────────────────────────────────────────────────────────────────
    def snapshot(self) -> tuple | None:
        """在**事件循环里**调用：把脏键序列化成可以丢给线程的纯数据。

        返回 (upserts, deletes, full) 或 None（没有脏数据）。
        序列化必须在这里做——读的是活字典，挪进线程会撞上并发修改。
        """
        dirty = self._dirty
        if dirty is not _ALL and not dirty:
            return None
        live = self._live
        if live is None:
            # 标过脏却没有活字典，说明 mark() 被绕过了。宁可不写也不能瞎删。
            self._dirty = set()
            _log.error(f"[kvstore] {self.table} 标脏了但没有活字典，跳过本次写入")
            return None
        self._dirty = set()

        if dirty is _ALL:
            upserts = [(k, json.dumps(v, ensure_ascii=False)) for k, v in live.items()]
            return (upserts, [], True)

        upserts, deletes = [], []
        for k in dirty:
            if k in live:
                upserts.append((k, json.dumps(live[k], ensure_ascii=False)))
            else:
                deletes.append((k,))
        return (upserts, deletes, False)

    def apply(self, batch: tuple) -> None:
        """在**线程池里**调用：把 snapshot() 的产物写进库。"""
        upserts, deletes, full = batch
        with self._lock:
            conn = self._connect()
            try:
                if full:
                    # 全量重写：先清空再灌。整个过程在一个事务里，
                    # 中途崩溃不会留下半张表。
                    conn.execute("BEGIN")
                    conn.execute(f"DELETE FROM {self.table}")
                    conn.executemany(
                        f"INSERT INTO {self.table}(k, v) VALUES(?, ?)", upserts
                    )
                else:
                    conn.execute("BEGIN")
                    if upserts:
                        conn.executemany(
                            f"INSERT INTO {self.table}(k, v) VALUES(?, ?) "
                            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                            upserts,
                        )
                    if deletes:
                        conn.executemany(
                            f"DELETE FROM {self.table} WHERE k=?", deletes
                        )
                conn.commit()
            except sqlite3.Error as e:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                # 这一批脏键已经从 _dirty 里摘掉了，直接放过就是**静默丢数据**。
                # 退化成「下次全量重写」——代价是一次大写入，换来自愈。
                self._dirty = _ALL
                _log.error(f"[kvstore] 写 {self.table} 失败: {e}（已标记下次全量重写）")

    def flush_sync(self) -> None:
        """无事件循环时的同步兜底（信号处理器里用）。"""
        batch = self.snapshot()
        if batch is not None:
            self.apply(batch)

    # ── 一次性导入 ────────────────────────────────────────────────────────
    def import_dict(self, data: dict) -> int:
        """把一份 dict 整个灌进表（用于 JSON → SQLite 的一次性迁移）。"""
        rows = [(k, json.dumps(v, ensure_ascii=False)) for k, v in data.items()]
        with self._lock:
            conn = self._connect()
            conn.execute("BEGIN")
            conn.execute(f"DELETE FROM {self.table}")
            conn.executemany(f"INSERT INTO {self.table}(k, v) VALUES(?, ?)", rows)
            conn.commit()
        return len(rows)
