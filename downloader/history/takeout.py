# SPDX-License-Identifier: AGPL-3.0-or-later
"""历史扫描走 takeout 会话（#2013）。

实验结论（docs/takeout-experiment.md）：takeout 会话扫历史消息快约 4.6 倍、几乎不被限流；
下载文件没有好处。所以**只用在历史下载的扫描阶段**，下载照旧走普通会话。

开关 `HISTORY_TAKEOUT`（默认关）：
- 关：`scan_messages()` 原样转给 `client.iter_messages()`，参数一个不改，和以前完全一样。
- 开：
  - 所有扫描 job 共用一个 takeout 会话（引用计数），最后一个 job 用完就结束它。
  - **不写 `client.session.takeout_id`**：Telethon 会把它存进 session 文件，进程崩了留下一个失效的 id，
    以后经 Telethon 自带的 takeout 接口都会出错。id 另记在 `STATE_DIR/takeout.json`，
    下次申请前先把上次没关掉的那个关掉（同一个号同一时间只能有一个 takeout 会话）。
  - 申请失败（如 `TakeoutInitDelayError`）或用到一半失败 → 日志记一行，退回普通会话，
    从最后一条已交出去的消息接着扫，不重复、不漏。申请失败后冷却一段时间再试，不让每个 job 都去撞。
  - 限流（FloodWait）不算 takeout 坏了：照旧往外抛，由 runner 暂停 job，和普通会话一样。
"""
import asyncio
import functools
import inspect
import json
import logging
import time

from telethon import utils as tl_utils
from telethon.errors import FloodWaitError, FloodPremiumWaitError, TakeoutInitDelayError
from telethon.tl import functions

import config
from common.atomic_io import atomic_write_json
from common.logger import get_logger

_log = get_logger("history")

# 申请失败后多久内不再申请（秒）；TakeoutInitDelayError 给了等待时间就按它的来
_RETRY_AFTER = 600


def enabled() -> bool:
    return bool(getattr(config, "HISTORY_TAKEOUT", False))


def _init_request():
    # 只要频道 / 超级群的消息；文件不经 takeout 下载
    return functions.account.InitTakeoutSessionRequest(
        contacts=False, message_users=False, message_chats=False,
        message_megagroups=True, message_channels=True, files=False)


def _describe(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:200]


def _state_file():
    return config.STATE_DIR / "takeout.json"


def _load_left_over() -> int | None:
    try:
        return int(json.loads(_state_file().read_text(encoding="utf-8"))["takeout_id"])
    except Exception:  # noqa: BLE001 —— 没有 / 坏了都当没有
        return None


def _remember(tid: int | None) -> None:
    try:
        if tid is None:
            _state_file().unlink(missing_ok=True)
        else:
            atomic_write_json(_state_file(), {"takeout_id": tid})
    except Exception as e:  # noqa: BLE001 —— 记不下来只影响「下次先关掉上次的」
        _log.warning(f"[takeout] 记录 takeout 会话失败：{_describe(e)}")


async def _finish(client, tid: int) -> None:
    await client(functions.InvokeWithTakeoutRequest(
        tid, functions.account.FinishTakeoutSessionRequest(success=True)))


class _Pool:
    """全进程共用一个 takeout 会话。"""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.tid: int | None = None
        self.refs = 0
        self.cooldown_until = 0.0

    async def acquire(self, client) -> int | None:
        """拿到 takeout id；拿不到返回 None（调用方走普通会话）。"""
        async with self.lock:
            if self.tid is None:
                if time.monotonic() < self.cooldown_until:
                    return None
                left = _load_left_over()
                if left is not None:      # 上次进程没来得及关的
                    try:
                        await _finish(client, left)
                        _log.info("[takeout] 关掉了上次留下的 takeout 会话")
                    except Exception as e:  # noqa: BLE001 —— 多半已经过期
                        _log.info(f"[takeout] 上次留下的 takeout 会话关不掉（多半已过期）：{_describe(e)}")
                    _remember(None)
                try:
                    r = await client(_init_request())
                except Exception as e:  # noqa: BLE001 —— 任何失败都退回普通会话
                    wait = _RETRY_AFTER
                    if isinstance(e, TakeoutInitDelayError):
                        wait = max(wait, int(getattr(e, "seconds", 0) or 0))
                    self.cooldown_until = time.monotonic() + wait
                    _log.warning(f"[takeout] 申请失败，退回普通会话（{wait} 秒内不再申请）：{_describe(e)}")
                    return None
                self.tid = r.id
                self.refs = 0
                _remember(r.id)
                _log.info("[takeout] 已开启 takeout 会话（历史扫描专用）")
            self.refs += 1
            return self.tid

    async def release(self, client, tid: int) -> None:
        """一个 job 用完。最后一个用完就结束 takeout 会话。"""
        async with self.lock:
            if tid != self.tid:
                return          # 中途已经作废，不用管
            self.refs -= 1
            if self.refs > 0:
                return
            self.tid = None
            try:
                await _finish(client, tid)
                _remember(None)
                _log.info("[takeout] 扫描都结束了，已关闭 takeout 会话")
            except Exception as e:  # noqa: BLE001 —— 关不掉也不影响下次（下次重新申请）
                _log.warning(f"[takeout] 关闭 takeout 会话失败（不影响使用）：{_describe(e)}")

    def invalidate(self, tid: int) -> None:
        """用到一半失败：作废，其他还在用的 job 下次请求也会失败、各自退回普通会话。"""
        if tid == self.tid:
            self.tid = None
            self.refs = 0
            self.cooldown_until = time.monotonic() + _RETRY_AFTER


_pool = _Pool()


class _ScanClient:
    """把 client 包一层：经它发出的请求都套上 InvokeWithTakeoutRequest(tid, …)。
    做法和 Telethon 自带的 client.takeout() 代理一样（client 的方法以代理为 self 调用，
    方法里的 self(request) 就走到这里的 __call__），只是 takeout id 用我们自己的，
    不读写 session.takeout_id。"""

    def __init__(self, client, tid: int):
        object.__setattr__(self, "_scan_client", client)
        object.__setattr__(self, "_scan_tid", tid)

    def __getattr__(self, name):
        client = object.__getattribute__(self, "_scan_client")
        value = getattr(client, name)
        if inspect.ismethod(value):
            return functools.partial(getattr(type(client), name), self)
        return value

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_scan_client"), name, value)

    async def __call__(self, request, ordered=False):
        client = object.__getattribute__(self, "_scan_client")
        tid = object.__getattribute__(self, "_scan_tid")
        single = not tl_utils.is_list_like(request)
        wrapped = []
        for r in ((request,) if single else request):
            await r.resolve(self, tl_utils)
            wrapped.append(functions.InvokeWithTakeoutRequest(tid, r))
        return await client(wrapped[0] if single else wrapped, ordered=ordered)


def _resume_kwargs(kwargs: dict, last_id: int, yielded: int) -> dict:
    """从最后一条已交出去的消息之后接着扫。"""
    kw = dict(kwargs)
    if kw.get("reverse"):
        kw["min_id"] = max(kw.get("min_id") or 0, last_id)
    else:
        kw["offset_id"] = last_id
    if kw.get("limit") is not None:
        kw["limit"] = max(0, kw["limit"] - yielded)
    kw.pop("wait_time", None)
    return kw


async def scan_messages(client, chat_id, **kwargs):
    """和 `client.iter_messages(chat_id, **kwargs)` 一样用。开关打开时走 takeout，失败自动退回。"""
    if not enabled():
        async for m in client.iter_messages(chat_id, **kwargs):
            yield m
        return

    tid = await _pool.acquire(client)
    if tid is None:
        async for m in client.iter_messages(chat_id, **kwargs):
            yield m
        return

    last_id, yielded, failed = None, 0, None
    try:
        tk = _ScanClient(client, tid)
        # takeout 的限流宽松得多，不用 Telethon 默认每 100 条睡 1 秒
        async for m in tk.iter_messages(chat_id, **{**kwargs, "wait_time": 0}):
            last_id, yielded = m.id, yielded + 1
            yield m
    except (FloodWaitError, FloodPremiumWaitError):
        raise
    except Exception as e:  # noqa: BLE001 —— 任何失败都退回普通会话
        failed = e
    finally:
        if failed is None:
            await _pool.release(client, tid)

    if failed is None:
        return
    _pool.invalidate(tid)
    _log.warning(f"[takeout] 扫描中途失败，退回普通会话接着扫（已扫 {yielded} 条）：{_describe(failed)}")
    kw = kwargs if last_id is None else _resume_kwargs(kwargs, last_id, yielded)
    async for m in client.iter_messages(chat_id, **kw):
        yield m


# ── 限流计数：Telethon 自动等掉的限流只打一行 INFO 日志，这里数一下，job 结束时写进日志 ──

class _FloodCounter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = 0
        self.seconds = 0

    def filter(self, record):
        if "flood wait" in str(record.msg):
            self.count += 1
            try:
                self.seconds += int(record.args[1])
            except Exception:  # noqa: BLE001
                pass
        return True


flood_counter = _FloodCounter()


def install_flood_counter() -> None:
    lg = logging.getLogger("telethon.client.users")
    if flood_counter not in lg.filters:
        lg.addFilter(flood_counter)
        if lg.getEffectiveLevel() > logging.INFO:
            lg.setLevel(logging.INFO)
