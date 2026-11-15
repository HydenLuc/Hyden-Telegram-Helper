# Downloader 下载可靠性设计

> **状态**：已实现（P1-5b）。本文档定义 pending_tasks / grouped_state 的结构与语义，以及若干配套行为。
>
> ⚠️ **2026-08-19 起持久化后端从 JSON 换成 SQLite**（`state.db`，见 `downloader/kvstore.py`）。
> 记录的**结构和语义完全没变**，变的只是「怎么落盘」——从「整份 dict 重写整个文件」
> 变成「改哪条写哪行」。本文下面凡是写 `pending_tasks.json` 的地方，读作「pending_tasks 这份数据」；
> 「原子写」一节已按新实现改写。

## 背景

当前 downloader 存在 4 类可靠性问题：

1. **任务丢失**：进程崩溃后，已排队和正在下载的任务全部丢失，需手动重试
2. **孤儿目录**：重试时创建 `retry_YYYYMMDD_HHMMSS` 目录，崩溃后残留无法识别
3. **重复下载**：`grouped_id` 媒体组只用 5 分钟 TTL 内存缓存（`state._group_dirs`），重启后同组消息重复入新目录
4. **耗时不准**：`started_at` 字段记录的是入队时间而非实际下载开始时间，UI 显示的"耗时"含连接等待和 FloodWait 退避，影响速度感知

P1-5b 一次性解决前 3 项 + 时间戳问题；断点续传（节流量）作为 P1-5c 可选未来规划。

---

## 数据文件总览

| 数据 | 存在哪 | 内容 | 何时写 | 何时读 |
|---|---|---|---|---|
| `pending_tasks` | **`state.db`** 表 | 已知未完成任务 | 入队 / 状态变更 | 启动恢复扫描 |
| `grouped_state` | **`state.db`** 表 | 媒体组下载状态 | 收消息 / 任务完成 | `handle_media` 单条 dedup |
| `content_index` | **`state.db`** 的 `content_md5` + `content_fuid` 两张表 | MD5 去重索引 | 算完 MD5 | 去重判定 |
| `completed.json` | JSON | 已完成任务历史 | 任务完成 | 启动加载 / Web UI |
| `watched_chats.json` | JSON | 监听频道列表 | 添加/移除频道 | 启动加载 |
| `duplicate_queue.json` | JSON | 待确认重复队列 | 去重判定 | 启动加载 / Web UI |

- **SQLite 的三份**：按 key 增量写，WAL 模式。为什么要这样见下面「原子写」。
- **剩下的 JSON**：仍用 **临时文件 + `os.rename` 原子写** + 2 秒合并写。
  它们小、变动不频繁，没有换的必要。

⚠️ **`state.db` 必须放本地盘**，不能放 NFS（SQLite 在网络文件系统上锁不可靠）。
和 `userbot.session` 同一条约束。

---

## `pending_tasks.json`

### 结构

```json
{
  "{task_id}": {
    "chat_id": -100123456789,
    "message_id": 42,
    "save_path": "/abs/path/to/save_dir/filename.zip",
    "expected_size": 1048576,
    "grouped_id": "12345678901234567",
    "queued_at": "2026-04-26T03:14:15.123456",
    "downloaded_bytes": 0
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` (key) | `str` | `{chat_id}_{message_id}` 或重试派生（`..._r{ts}`、`..._api{ts}`）|
| `chat_id` | `int` | Telegram chat ID |
| `message_id` | `int` | Telegram message ID |
| `save_path` | `str` | 文件应保存的绝对路径 |
| `expected_size` | `int` | `message.file.size`（消息对象元数据，下载前即知）|
| `grouped_id` | `str | null` | 媒体组 ID（来自 `message.grouped_id`，单条媒体为 `null`）|
| `queued_at` | ISO 8601 | 入队时间戳 |
| `downloaded_bytes` | `int` | **预留字段**，P1-5c 断点续传用；P1-5b 阶段固定为 `0` |

### 生命周期

| 时机 | 操作 |
|---|---|
| 任务入队（`handlers.py:handle_media`、`_api_download`、`_api_retry`）| 写入 pending_tasks |
| 任务成功完成（`_finish(status="done")`）| 删除 pending_tasks 条目 |
| 任务失败/超时/取消（`_finish` 其他 status）| **保留**，用于 UI"待重试"显示 |
| 用户主动从 UI 删除失败记录 | 同步删除 pending_tasks 条目 |

### 落盘（2026-08-19 改写）

- 内存里仍然维护 `pending_tasks: dict[str, dict]`，作为 `state.py` 模块级变量。
  **读路径没变**，业务代码照旧当普通 dict 用
- 变更时调 `storage.save_pending_tasks(tasks, key=task_id)` → 标记这一个 key 脏
- 每 2 秒（`_SAVE_DEBOUNCE`）把脏键写进 `state.db`。序列化在事件循环里做
  （要读活字典，挪线程会撞并发修改），SQL 丢线程池

#### ⚠️ 为什么不再是「整文件重写」

原实现是「任何变更 → 整个 dict 序列化 → 原子重写整个文件」。实测：

```
pending_tasks.json（17.7 MB / 41,123 条）的 mtime 每 2 秒推进一次，从不停
```

因为下载进度（`downloaded_bytes`）也算变更。代价：约 9 MB/s 持续写（780 GB/天）、
`json.dumps` 数万条 0.2~0.6 秒**卡在事件循环里**、RSS 在 972~2,034 MB 之间锯齿。

改按 key 增量写之后：改一条进度 **0.2 ms**，RSS 505~647 MB 平稳。

#### ⚠️ 调用点的约定

**有 key 就一定要传 `key=`。** 不传会退化成整表重写——不会丢数据，但一次写数万行，
正是要消灭的那件事。之所以留这个退路而不强制传参：
「忘了传 → 写多了」远比「忘了传 → 悄悄没存」安全。

删除不需要特殊处理：`del d[k]` 之后照常 `save_x(d, key=k)`，
flush 时发现 k 不在活字典里就 DELETE。

#### ⚠️ 旧 JSON 别删

迁移后 `pending_tasks.json` / `grouped_state.json` / `content_index.json` 会**冻在迁移时刻**
（mtime 不再变）。它们是回滚路径，也是 SQLite 出问题时的兜底。
`_migrate_json_to_kv` 靠「库里有没有数据」判断是否需要迁移，所以**别删也别改名**：
库要是没了而 JSON 也不在，启动会得到一个空队列，几万个任务静默消失。

### ⚠️ 恢复扫描只跑一次；搁置任务靠 stalled_retry_loop（2026-09-17）

`recover_pending_tasks` **只在 `client.start()` 之后跑一次**。跑完还失败的任务
就留在 `pending_tasks` 里，**没有任何东西会再自动碰它们** —— 直到下次重启。

界面上它们混在「队列」里看着像在排队，实际不会动。2026-09-17 实测 11 个大文件
任务因此躺了一个多月（hyden 报「队列 18 但只有 1 个在下」）。

现在 `stalled_retry_loop`（`bot.py` 启动时挂）周期性把它们捞起来重试：
- **搁置** = 在 pending、不在 active_downloads（没协程在管它）
- **绝不碰已在 active 的** —— 同 task_id 起两次会互相踩踏、白下几个 GB
- 退避 = `STALLED_RETRY_INTERVAL × 2^retry_count`，封顶 24h
- `last_attempt_at` 持久化进 pending 记录，重启后退避不归零

配合下面「.partN 保留」，每次重试从断点续，大文件才有跑完的一天。

### 🔴 .partN 只在「确实要从零重来」时删（2026-09-17 血泪）

`_should_purge_parts(reason)` 是唯一决策点：

| 删 | 留 |
|---|---|
| `manual_cancel` 用户不要了 | `stall_timeout` **最需要续传的时刻** |
| `resume_fallback` 旧分块可能坏 | `flood_wait` 临时限流 |
| `gave_up` 重试用尽 | （未知原因保守保留）|

之前停滞超时**无条件删 .partN**，后果是大文件永动机：
下 3.5GB → 尾部卡 → 60s 超时 → 删光 → 从 0 再来。11 个任务这么循环了一个多月，
每轮烧 3.5GB，一个没成。整套续传机制（chunker 读 .partN 续传）本来是好的，
**只是永远没有 .partN 可读**。

### 🔴 同 task_id 两次下载的归属守卫（2026-09-17）

重试/恢复复用原 task_id，同一 task_id 可能同时有两个 `download_one`。
每次调用发递增 `run_id` 写进 active 记录；`_finish` 只摘 run_id 匹配的那次；
所有 `active_downloads[task_id]` 的写入过 `_own()`（被顶替就安静退出）。
不做的话老协程收尾会把新协程的记录 pop 掉 → 新协程 `KeyError` 崩掉 →
任务永久卡 pending，而且崩成 asyncio「Task exception was never retrieved」，
**错误计数里都看不见**。

### crash 恢复扫描（4 分支）

启动时（`main.py` 在 `client.start()` 之后），加载 `pending_tasks.json`，对每条记录按 4 分支处理：

```python
file = Path(rec["save_path"])

if not file.exists():
    # 分支 1：文件根本不存在 → 重新下载
    schedule_redownload(task_id, rec)

elif file.stat().st_size == rec["expected_size"]:
    # 分支 2：大小完全匹配 → 视为已完成
    rec["status"] = "done"
    completed_downloads.insert(0, rec)
    save_completed(...)
    del pending_tasks[task_id]
    save_pending_tasks()

elif file.stat().st_size < rec["expected_size"]:
    # 分支 3：文件不完整（崩溃中断）
    # v1 (P1-5b)：删除旧文件，重新下载
    # v2 (P1-5c)：从 downloaded_bytes 续传
    file.unlink()
    schedule_redownload(task_id, rec)

else:  # file.stat().st_size > rec["expected_size"]
    # 分支 4：异常状态（理论上不应发生）
    print(f"[warning] {file} size > expected, will redownload")
    file.unlink()
    schedule_redownload(task_id, rec)
```

`schedule_redownload(task_id, rec)` 内部需先 `client.get_messages(rec["chat_id"], ids=rec["message_id"])` 重取消息对象（防 `file_reference` 过期），然后调用 `download_one`。

---

## `grouped_state.json`

### 结构

```json
{
  "{chat_id}_{grouped_id}": {
    "status": "downloading",
    "total_files": 3,
    "done_files": 2,
    "task_ids": ["-100..._42", "-100..._43", "-100..._44"],
    "files": {
      "{task_id}": {
        "save_path": "/abs/path/to/file.mp4",
        "expected_size": 1048576,
        "status": "done"
      }
    },
    "first_seen_at": "2026-04-26T03:14:15.123456",
    "completed_at": null
  }
}
```

| 字段 | 说明 |
|---|---|
| key | `f"{chat_id}_{grouped_id}"`，chat 和 group 的复合键（同一 group_id 在不同 chat 是不同的键）|
| `status` | **自动计算汇总**，不参与跳过决策（详见下） |
| `total_files` | 当前组内已收到的消息数（动态增长，新到 task_id 加 1）|
| `done_files` | 当前组内 status==done 的数量 |
| `task_ids` | 完整的 task_id 列表（保序）|
| `files[task_id]` | 单条文件的 `save_path` / `expected_size` / `status` |
| `first_seen_at` | 该组第一条消息进入 handler 的时间 |
| `completed_at` | 最后一次整组 done 的时间；新消息到达会重置为 `null` |

### 单条 dedup（**唯一参与跳过决策的规则**）

```
新消息进入 handle_media:
  group_key = f"{chat_id}_{grouped_id}"  if message.grouped_id else None
  task_id   = f"{chat_id}_{message_id}"

  if group_key and group_key in grouped_state:
      grp = grouped_state[group_key]
      if task_id in grp["files"] and grp["files"][task_id]["status"] == "done":
          # 该条已下载过 → 跳过
          return

  # 其他情况：照常入队（即使整组 status=="done" 也照常处理新 task_id）
```

### "整组 done" 仅作 UI 标签

`status` 字段是**自动计算的汇总**，**不参与跳过决策**。计算规则：

| `status` 值 | 条件 |
|---|---|
| `done` | 所有 `files` 都是 `done` |
| `partial` | 至少一个 `done`，但有非 `done` |
| `downloading` | 无 `done`，至少一个 `downloading` |
| `error` | 全部 `error` 且无进行中 |

### 新 task_id 到达：始终添加

```python
if task_id not in grp["files"]:
    grp["files"][task_id] = {
        "save_path": ...,
        "expected_size": ...,
        "status": "downloading",
    }
    grp["task_ids"].append(task_id)
    grp["total_files"] += 1
    grp["completed_at"] = None         # 之前的完成时间戳作废
    grp["status"] = recompute(grp)     # 重新汇总（done 退回 partial/downloading）
    save_grouped_state()
```

这样可以正确处理"组消息延迟到达"场景：前 3 条已下完（status=done），第 4 条 30 秒后到，按规则**照常下载**，组 status 退回 `partial`，第 4 条完成后再升回 `done`。

### 持久化时机

- 新组首次出现：写入
- 组内增加新文件：更新
- 组内某文件状态变更（`_finish` 调用时同步）：更新

每次更新都触发整文件原子写。

---

## 时间戳字段修正

### 字段含义

| 字段 | 含义 | 何时赋值 |
|---|---|---|
| `queued_at`（**新增**）| 任务入队时间 | `download_one` 入口、`_api_download` / `_api_retry` 写入 pending 时 |
| `started_at`（**含义变更**）| **真正开始下载流量的时间**（`_acquire_connections` 之后）| `download_one` 在拿到连接后赋值；FloodWait 重试时**每次 attempt 重置** |
| `finished_at`（不变）| 任务结束时间（done/error/timeout/cancelled）| `_finish()` |

### 派生量

| 量 | 公式 |
|---|---|
| **实际下载耗时** | `finished_at - started_at` |
| 排队等待时长 | `started_at - queued_at` |
| 总耗时（端到端）| `finished_at - queued_at` |

前端 `fdur` 函数默认显示**实际下载耗时**（不含排队等待、不含 FloodWait 退避）。可选地副信息里加"等待 X 秒"。

### 旧记录兼容性迁移

`completed.json` 已有最多 100 条历史记录的 `started_at` 是入队时间（旧含义）。`load_completed()` 加载时迁移：

```python
def load_completed():
    raw = json.load(...)
    for rec in raw:
        if "queued_at" not in rec:
            rec["queued_at"] = rec.get("started_at")
            # 注意：旧记录的 started_at 仍然是入队时间，
            # 即旧记录的"耗时"显示偏大（含等待时间），仅升级后的新任务准确。
    return raw
```

UI 不区分新旧记录显示——本文档明确说明"升级后旧记录耗时显示偏大"，新任务准确。

---

## 连接分级调度

### 现状

`MAX_TOTAL_CONNECTIONS=16` 全局共享，所有任务先到先得。大文件 `_adaptive_chunks` 一次申请 6 个连接，可能挤压小文件。

### 新增配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SMALL_FILE_THRESHOLD_MB` | `5` | 小于此阈值的文件视为"小文件" |
| `SMALL_FILE_RESERVED_CONNECTIONS` | `3` | 始终为小文件预留的连接数 |

二者均通过 `os.getenv` 读取，可在 `.env` 配置。

### 硬预留模式

```
小文件（< THRESHOLD）申请 n 连接：
    cap = MAX_TOTAL_CONNECTIONS
    while _total_connections + n > cap:
        await _conn_gate.wait()

大文件（>= THRESHOLD）申请 n 连接：
    cap = MAX_TOTAL_CONNECTIONS - SMALL_FILE_RESERVED_CONNECTIONS
    while _total_connections + n > cap:
        await _conn_gate.wait()
```

**特性**：
- 即使没有小文件等待，大文件也**无法**使用预留的连接
- 行为可预测，实现简单
- 利用率损失上限 = `RESERVED / MAX_TOTAL`（默认 3/16 ≈ 19%）

### 实现要点

`_acquire_connections(n, is_small_file: bool)` 加一个参数；`download_one` 调用方根据 `_adaptive_chunks` 返回值（`n_conns == 1` 即 `< 50 MB`，进一步用文件大小和阈值判断小文件）传入。**不需要新建第二个 Condition**，复用现有 `state._conn_gate`。

---

## 全局暂停监听

### 状态

`state.monitoring_paused: bool = False`（模块级变量）

### 行为

- `tg/handlers.py:handle_media` 入口：`if state.monitoring_paused: return`
- 不影响：已排队、正在下载的任务（在 `download_one` 协程内运行，与 handler 解耦）
- 不影响：通过 `/api/download` 主动触发的下载（用户主动操作不受暂停约束）

### API

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/monitoring/pause` | POST | 设置 `state.monitoring_paused = True` |
| `/api/monitoring/resume` | POST | 设置 `state.monitoring_paused = False` |
| `/api/status` | GET | 响应里加 `"monitoring_paused": bool` 字段 |

### v1 不持久化

`monitoring_paused` 仅在内存维护。**重启后自动恢复监听**（值回到默认 `False`）。

**文档明确**：暂停状态不跨重启保留。  
理由：重启是少见操作，监听暂停通常是临时性的（处理紧急事务、调试）。如果未来用户反馈需要持久化，可在 v2 加 `paused.flag` 文件或 `.env` 字段。

### 前端

- 顶部导航栏加按钮："暂停监听" / "恢复监听"
- 状态用颜色区分：暂停时按钮变橙；`bot-status` badge 显示"已暂停监听"

---

## `retry_*` 目录

### 现状

`_api_retry`（`web/api.py`）在原目录不可用时创建 `retry_{YYYYMMDD_HHMMSS}` 目录。崩溃后残留。

### 决策：v1 不自动清理

P1-5b 实施后，**不再产生新的 `retry_*` 目录**——失败任务保留在 `pending_tasks.json` 条目中，用户重试沿用原 `save_path`。所以 `retry_*` 是历史遗留，规模有限。

### 人工清理命令

清空目录可放心删：

```bash
find $DOWNLOAD_DIR -name "retry_*" -type d -empty -delete
```

非空目录用户自己判断（可能含部分有用文件）：

```bash
ls $DOWNLOAD_DIR | grep "^retry_"
```

### 不提供 `/api/cleanup` 端点

P1-5b 范围内不做。如果未来历史 `retry_*` 累积成问题，再考虑加一个返回**候选列表**（不直接删）的 API，由调用方手动确认。

---

## 断点续传（P1-5c）

> 状态：**设计已定，待实现**。本节定义实施方案；代码改动见后续 commit。

### 目标

**节省"已下载字节因崩溃 / 失败被丢弃"的流量**——无论崩溃恢复还是用户主动重试，只要磁盘上有 `.partN` 进度，就**续传**而不是重头下。

### 技术可行性

Telethon `iter_download(message.media, offset=N, ...)` 原生支持任意字节偏移开始下载（已用 chunker.py 多 chunk 并行验证）。

### 与 P1-5b 的字段差异

P1-5b 已为本节预留两个字段：

```json
{
  "task_id_xxx": {
    "chat_id": ...,
    "message_id": ...,
    "save_path": ...,
    "expected_size": ...,
    "grouped_id": ...,
    "queued_at": ...,
    "downloaded_bytes": 0     // ← P1-5b 一直为 0；P1-5c 由 chunker 周期更新
  }
}
```

**P1-5c 新增两个字段**：

| 字段 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `retry_count` | `int` | `0` | 用户**主动重试**累计次数（`_api_retry` 时 +1）；崩溃恢复不计 |
| `last_resume_failed` | `bool` | `false` | 上次续传失败 → 下次重试强制重头下；成功后清回 false |

`downloaded_bytes` 语义升级为：**所有 `.partN` 文件已写字节数的汇总**（仅用于决策"是否续传"和 UI 显示，**不直接作为 iter_download 的 offset**——见下方"实现要点"）。

### 决策

#### 决策 1：续传触发条件（崩溃恢复 + 主动重试统一）

```
                ┌─ downloaded_bytes > 0 ─┐
是否续传 = AND  │                         │
                └─ NOT last_resume_failed ┘
```

| 入口 | retry_count | downloaded_bytes 检查 | last_resume_failed 检查 |
|------|-------------|----------------------|------------------------|
| 崩溃恢复（`recover_pending_tasks`）| 不变（仍为 0 或历史值）| 是 | 是 |
| 主动重试（`_api_retry`）| **+1** | 是 | 是 |

两条路径**都走续传逻辑**，区别仅在 `retry_count` 是否累加（用于统计/UI 显示用户重试次数）。

#### 决策 2：`downloaded_bytes` 持久化粒度

```
N = max(1 MB, expected_size / 100)
```

- 1 GB 文件：每 10 MB 持久化一次（100 次写）
- 100 MB 文件：每 1 MB 持久化一次（100 次写）
- 5 GB 文件：每 50 MB 持久化一次（100 次写）

满足"最坏丢失 1% 进度"上限，同时把 .json 写盘次数控制在 100 量级。

#### 决策 3：续传失败 fallback 策略

```
续传请求失败（任意原因）：
   ├─ 清零 downloaded_bytes（实际是删 .partN 文件）
   ├─ 设 last_resume_failed = True
   ├─ 保留 retry_count（让用户看到重试历史）
   └─ 改为重头下载（不再续传本次）

重头下载成功：
   └─ 清除 last_resume_failed = False（恢复"下次可续传"能力）

下次再次失败被重试 → 检查 last_resume_failed 直接走重头，不再尝试续传。
```

### 实现要点

#### 1. `chunker.py` — 每 chunk 各自决定续传

```python
async def download_chunk(idx: int):
    offset_b, limit_b = ranges[idx]
    tmp = tmp_paths[idx]

    # 续传：检查已存在的 .partN 文件大小
    resume_skip = 0
    open_mode = "wb"
    if resume and tmp.exists() and tmp.stat().st_size > 0 and tmp.stat().st_size < limit_b:
        resume_skip = tmp.stat().st_size
        open_mode = "ab"

    written = resume_skip
    async for block in client.iter_download(
        message.media,
        offset=offset_b + resume_skip,    # 关键：每个 chunk 用自己的 offset_b + resume_skip
        request_size=state.CHUNK_SIZE,
        file_size=file_size,
    ):
        # 现有写入逻辑不变
        ...
```

**关键**：续传起点是**每个 chunk 的 offset_b + 该 chunk 的 .partN 已写字节数**，不是全局 downloaded_bytes。

#### 2. `download_one` — 周期写 downloaded_bytes 到 pending_tasks

在 chunker.py 内既有的 `state.active_downloads[task_id].update(...)` 旁加：

```python
total_cur = sum(c["current"] for c in chunks_info)

# 持久化粒度：N = max(1MB, file_size/100)
persist_threshold = max(1048576, file_size // 100)
last_persisted = state.pending_tasks.get(task_id, {}).get("downloaded_bytes", 0)
if total_cur - last_persisted >= persist_threshold:
    if task_id in state.pending_tasks:
        state.pending_tasks[task_id]["downloaded_bytes"] = total_cur
        storage.save_pending_tasks(state.pending_tasks)
```

任务完成成功时（manager.py:228 的 `if status == "done":` 分支）：
- 现有逻辑：从 pending_tasks 删除条目（沿用，无需改）
- 新增：清除 `last_resume_failed`（虽然马上要删，但保持字段一致性是好习惯）

#### 3. `_api_retry` 改动

```python
async def _api_retry(request):
    ...
    pending_rec = state.pending_tasks.get(task_id)
    if pending_rec:
        # 决定续传还是重头
        resume = (
            pending_rec.get("downloaded_bytes", 0) > 0 and
            not pending_rec.get("last_resume_failed", False)
        )
        # 累加 retry_count
        pending_rec["retry_count"] = pending_rec.get("retry_count", 0) + 1
        if not resume:
            # 重头下载：清进度 + 删 .partN
            pending_rec["downloaded_bytes"] = 0
            for p in save_path.parent.glob(f"{save_path.name}.part*"):
                try: p.unlink()
                except OSError: pass
        storage.save_pending_tasks(state.pending_tasks)
    ...
    # 启动 download_one(resume=resume, ...)
```

#### 4. `recover_pending_tasks` 分支 3 改动

`_recover_one` 中分支 3（文件不完整）的 `save_path.unlink()` 改为：

```python
elif save_path.stat().st_size < expected:
    branch_label = f"3（文件不完整 {save_path.stat().st_size}/{expected}）"
    # P1-5c：保留主文件 + .partN，让续传逻辑接管
    # 旧版本删文件重下；新版本走续传
    pass  # 不再 unlink
```

`download_one` 调用时传 `resume=True`（如果 `downloaded_bytes > 0` 且 `not last_resume_failed`）。

#### 5. fallback 流程

`download_one` 续传过程中若 Telethon 抛出异常（包括 `FileReferenceExpiredError` / 网络断 / DC 切换），**不要**直接报 error 完成任务。改为：

```python
try:
    await chunker.download_chunked(..., resume=True)
except Exception as resume_err:
    _log.warning(f"[resume] 续传失败 {task_id}: {resume_err}，回退重头下载")
    # 清现场
    pending_rec["downloaded_bytes"] = 0
    pending_rec["last_resume_failed"] = True
    storage.save_pending_tasks(state.pending_tasks)
    for p in save_path.parent.glob(f"{save_path.name}.part*"):
        try: p.unlink()
        except OSError: pass
    # 重头跑一次
    await chunker.download_chunked(..., resume=False)
    # 成功才清 last_resume_failed
    if task_id in state.pending_tasks:
        state.pending_tasks[task_id]["last_resume_failed"] = False
        storage.save_pending_tasks(state.pending_tasks)
```

只允许**一次** fallback，避免死循环。

### 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| `file_reference` 过期 | `_api_retry` 和 `recover_pending_tasks` 都已 `client.get_messages` 重取（现有行为） |
| 文件被发送者删除 | `get_messages` 返回 `None` → 标 error 并从 pending 删除（现有行为） |
| 无字节级哈希 | Telegram 不提供；只能信任字节数对齐 + Telethon iter_download 字节流连续性 |
| 跨 DC 切换 | 现有 `FileMigrateError` 处理沿用 |
| 续传死循环 | `last_resume_failed` 标志：失败后强制下次重头，避免 retry → 续传失败 → retry 循环 |
| 多 chunk 并行写竞争 | 每 chunk 独立 `.partN`，无共享文件；最终 assemble 阶段不变 |

### 测试矩阵

P1-5c 必须通过的场景：

1. **`kill -9` 中途**（multi-chunk 5 GB 文件下到 60% → 重启 → 续传 40% 完成）
2. **断网恢复**（拔网线 → Telethon 抛 ConnectionError → 续传至完成）
3. **DC 切换**（`FileMigrateError` 在续传过程中触发 → Telethon 自处理 → 不影响）
4. **`file_reference` 过期**（搁置任务 24h+ → 主动重试 → get_messages 重取后续传成功）
5. **`last_resume_failed` 防死循环**（mock Telethon 续传永远报错 → 第一次失败设标志 → 第二次走重头）
6. **小文件 < 50 MB**（单 chunk）的续传正确性（覆盖 `n_chunks=1` 边界条件）
7. **持久化粒度验证**（10 GB 文件下载完，`save_pending_tasks` 调用次数 ≈ 100 ± 10）

### 工作量预估

~1 天（chunker.py 改动小；download_one fallback 流程与持久化加约 30 行；4 个端到端场景手测占大头）。
