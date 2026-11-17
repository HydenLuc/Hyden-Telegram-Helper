# SPDX-License-Identifier: AGPL-3.0-or-later
"""takeout 对比实验（普通会话 vs `client.takeout()` 的限流和耗时）。报告见 docs/takeout-experiment.md。

⚠️ 只在测试号上跑，并且先停掉下载器（同一个号的限流是共用的，下载器在跑会干扰结果）。

用法（cwd = 项目根目录，用它的 .env 和 venv）：
  cp state/userbot.session /some/private/dir/exp.session        # 用副本，别动原文件
  export EXP_SESSION=/some/private/dir/exp                       # 不带 .session 后缀
  python tools/experiments/takeout_compare.py probe              # 列频道 + 试一次 initTakeoutSession
  python tools/experiments/takeout_compare.py history <@用户名|id> <mode> <请求数> [--limit 100]
  python tools/experiments/takeout_compare.py download <@用户名|id> <mode> <文件数> [--conc 8] [--max-mb 2000] [--skip 0]
  python tools/experiments/takeout_compare.py finish             # 中途崩了留下的 takeout 会话手动结束
mode = normal | takeout

所有 FloodWait 都不让 Telethon 静默吞掉（flood_sleep_threshold=0），自己记次数和秒数再 sleep 重试。
结果追加到 session 副本旁边的 results.jsonl。下载只读进内存不落盘。
用完删掉 session 副本。
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
import config  # noqa: E402
from telethon import TelegramClient, errors, utils  # noqa: E402
from telethon.tl import functions, types  # noqa: E402

SESSION = Path(os.environ["EXP_SESSION"])  # 副本路径（不带 .session）
RESULTS = SESSION.parent / "results.jsonl"   # 跟 session 副本放一起，不落进仓库


def log(rec):
    rec["ts"] = time.strftime("%F %T")
    with RESULTS.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False))


class Flood:
    def __init__(self):
        self.count = 0
        self.wait_s = 0
        self.events = []

    async def call(self, fn, *a, **kw):
        while True:
            try:
                return await fn(*a, **kw)
            except (errors.FloodWaitError, errors.FloodPremiumWaitError) as e:
                self.count += 1
                self.wait_s += e.seconds
                self.events.append([round(time.time() - T0, 1), type(e).__name__, e.seconds])
                print(f"  ⏳ {type(e).__name__} {e.seconds}s", flush=True)
                await asyncio.sleep(e.seconds + 1)


T0 = time.time()


def make_client():
    return TelegramClient(str(SESSION), config.API_ID, config.API_HASH,
                          flood_sleep_threshold=0)


def takeout_request(**kw):
    return functions.account.InitTakeoutSessionRequest(
        contacts=False, message_users=kw.get("users", False), message_chats=False,
        message_megagroups=True, message_channels=True,
        files=True, file_max_size=kw.get("max_size", 4 * 1024 ** 3))


async def init_takeout(client):
    """返回 takeout_id；遇到 TakeoutInitDelayError 直接抛出给调用方记录。"""
    if client.session.takeout_id:
        return client.session.takeout_id
    r = await client(takeout_request())
    client.session.takeout_id = r.id
    client.session.save()
    return r.id


async def finish_takeout(client):
    tid = client.session.takeout_id
    if not tid:
        return
    try:
        await client(functions.InvokeWithTakeoutRequest(
            tid, functions.account.FinishTakeoutSessionRequest(success=True)))
    except Exception as e:  # noqa: BLE001
        print("finish takeout:", type(e).__name__, e)
    client.session.takeout_id = None
    client.session.save()


def wrap(req, tid):
    return functions.InvokeWithTakeoutRequest(tid, req) if tid else req


async def probe():
    async with make_client() as c:
        me = await c.get_me()
        print("me premium:", bool(me.premium))
        async for d in c.iter_dialogs():
            ent = d.entity
            if not isinstance(ent, types.Channel):
                continue
            tot = (await c.get_messages(ent, limit=0)).total
            docs = (await c.get_messages(ent, limit=0, filter=types.InputMessagesFilterDocument())).total
            vids = (await c.get_messages(ent, limit=0, filter=types.InputMessagesFilterVideo())).total
            print(f"{d.id}\t{'bc' if ent.broadcast else 'mg'}\tmsgs={tot}\tdocs={docs}\tvideos={vids}\t{d.name[:30]}")
        try:
            tid = await init_takeout(c)
            log({"phase": "probe", "takeout": "ok", "takeout_id_set": bool(tid)})
            await finish_takeout(c)
        except errors.TakeoutInitDelayError as e:
            log({"phase": "probe", "takeout": "TakeoutInitDelayError", "seconds": e.seconds})
        except Exception as e:  # noqa: BLE001
            log({"phase": "probe", "takeout": type(e).__name__, "msg": str(e)[:200]})


async def history(chat_id, mode, n_req, limit=100):
    fl = Flood()
    async with make_client() as c:
        ent = await c.get_input_entity(chat_id)
        tid = await init_takeout(c) if mode == "takeout" else None
        t0 = time.time()
        offset_id = 0
        got = 0
        cycles = 0
        for i in range(n_req):
            req = functions.messages.GetHistoryRequest(
                peer=ent, offset_id=offset_id, offset_date=None, add_offset=0,
                limit=limit, max_id=0, min_id=0, hash=0)
            r = await fl.call(c, wrap(req, tid))
            msgs = r.messages
            got += len(msgs)
            if len(msgs) < limit:      # 到底了，从头再来（只为凑够请求数）
                offset_id = 0
                cycles += 1
            else:
                offset_id = msgs[-1].id
        dt = time.time() - t0
        if mode == "takeout":
            await finish_takeout(c)
    log({"phase": "history", "mode": mode, "chat": chat_id, "requests": n_req, "limit": limit,
         "messages": got, "wraps": cycles, "seconds": round(dt, 1),
         "flood_count": fl.count, "flood_wait_s": fl.wait_s, "flood_events": fl.events[:50]})


async def download(chat_id, mode, n_files, conc=8, max_mb=2000, chunk=1024 * 1024, skip=0):
    fl = Flood()
    async with make_client() as c:
        ent = await c.get_input_entity(chat_id)
        # 选文件：同一批消息，两种模式下一样（按 id 倒序取前 n 个有文档的，跳过 skip 个）
        picked, total_bytes = [], 0
        async for m in c.iter_messages(ent, filter=types.InputMessagesFilterDocument()):
            if not m.file or not m.file.size:
                continue
            if skip:
                skip -= 1
                continue
            if total_bytes + m.file.size > max_mb * 1024 ** 2:
                continue
            picked.append(m)
            total_bytes += m.file.size
            if len(picked) >= n_files:
                break
        tid = await init_takeout(c) if mode == "takeout" else None
        sem = asyncio.Semaphore(conc)
        errs = []
        dcs = {}
        senders = {}

        async def sender_for(dc):
            if dc == c.session.dc_id:
                return c._sender
            if dc not in senders:
                senders[dc] = await c._borrow_exported_sender(dc)
            return senders[dc]

        async def one(m):
            dc, loc = utils.get_input_location(m.media)
            dcs[dc] = dcs.get(dc, 0) + 1
            size = m.file.size
            offsets = list(range(0, size, chunk))
            snd = await sender_for(dc)

            async def part(off):
                async with sem:
                    req = functions.upload.GetFileRequest(loc, off, chunk, precise=False, cdn_supported=False)
                    r = await fl.call(c._call, snd, wrap(req, tid))
                    return len(r.bytes)

            got = sum(await asyncio.gather(*(part(o) for o in offsets)))
            if got != size:
                errs.append([m.id, size, got])

        t0 = time.time()
        results = await asyncio.gather(*(one(m) for m in picked), return_exceptions=True)
        dt = time.time() - t0
        exc = [type(r).__name__ + ":" + str(r)[:120] for r in results if isinstance(r, BaseException)]
        for s in senders.values():
            await c._return_exported_sender(s)
        if mode == "takeout":
            await finish_takeout(c)
    log({"phase": "download", "mode": mode, "chat": chat_id, "files": len(picked),
         "mb": round(total_bytes / 1024 ** 2, 1), "conc": conc, "seconds": round(dt, 1),
         "mb_s": round(total_bytes / 1024 ** 2 / dt, 2) if dt else None,
         "flood_count": fl.count, "flood_wait_s": fl.wait_s, "flood_events": fl.events[:50],
         "dcs": dcs, "home_dc": c.session.dc_id, "size_mismatch": errs[:10], "exceptions": exc[:10]})


def main():
    a = sys.argv[1:]
    opt = {}
    while "--" in " ".join(a):
        for i, x in enumerate(a):
            if x.startswith("--"):
                opt[x[2:]] = int(a[i + 1])
                del a[i:i + 2]
                break
    if a[0] == "probe":
        asyncio.run(probe())
    elif a[0] == "history":
        asyncio.run(history(a[1], a[2], int(a[3]), opt.get("limit", 100)))
    elif a[0] == "download":
        asyncio.run(download(a[1], a[2], int(a[3]), opt.get("conc", 8),
                             opt.get("max-mb", 2000), skip=opt.get("skip", 0)))
    elif a[0] == "finish":
        async def f():
            async with make_client() as c:
                await finish_takeout(c)
        asyncio.run(f())


if __name__ == "__main__":
    main()
