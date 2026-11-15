# Mover 内部机制

## 任务生命周期（状态机）

```
POST /api/move 接收请求
        │
        │ task_id 去重检查（见幂等性节）
        │
        ▼
  ┌───────────┐
  │  pending  │  已加入队列，等待 Semaphore 放行
  └─────┬─────┘
        │ asyncio.Semaphore 获取槽位
        ▼
  ┌───────────┐
  │  copying  │  正在执行搬运（staging → rename）
  └──┬──────┬─┘
     │      │
     │      └─── 任何子文件失败
     │                  ▼
     │           清理 staging 目录
     │                  ▼
     │           ┌───────────┐
     │           │  failed   │  error / failed_at / error_source / files_attempted / files_completed 填充
     │           └───────────┘
     │
     │ 全部文件成功，os.rename staging → 正式目录
     ▼
  ┌───────────┐
  │   done    │  completed_at / target_path 填充
  └───────────┘
```

所有状态变化立即写入 `mover_state.json` 并通过 WebSocket 广播。

---

## 两步原子移动（防止 watchdog 提前触发）

unzipper 的 watchdog 监听 `WATCH_PATH`，只要有新文件出现就会检测。如果 mover 直接复制大文件到 `WATCH_PATH`，watchdog 会在文件还没写完时就触发。两步移动解决这个问题：

```
WATCH_PATH/
├── .mover_staging_a3f9c8d2.../   ← 步骤 1：隐藏目录，watchdog 过滤 . 开头
│   └── 20260423_video/
│       ├── video.mp4             ← 复制中
│       └── 消息详情.txt
│
└── 20260423_video/               ← 步骤 2：rename（原子操作，毫秒级）
    ├── video.mp4                 ← watchdog 此时才看到完整目录
    └── 消息详情.txt
```

**步骤 1**（copying 阶段）：
- 在 `target_parent` 下（即 API 参数 `target` 目录内）创建 `.mover_staging_<uuid4_hex>/` 临时目录
- 将 `source` 的内容**复制**到 `staging/<source_basename>/`（保留目录结构）
- 跨文件系统：用 `shutil.copytree(source, staging_dst)` 或逐文件 `shutil.copy2`
- 同文件系统且 source 和 staging 在同一 fs：仍用 copy（因为 staging 和 target 同 fs，保证后续 rename 可用）

**步骤 2**（原子完成）：
- 全部文件复制并验证完成后：`os.rename(staging_dst, final_dst)`
- `os.rename` 在同文件系统上是原子操作（POSIX 保证）
- 此时 watchdog 才首次检测到 `final_dst`，文件已完整

**失败回滚**：
- 任何步骤失败 → `shutil.rmtree(staging_dir)` 清理 staging
- 源文件**不删除**（失败时 source 仍然完整，可以重试）

**target 路径冲突**：
- 若 `final_dst`（`target/source_basename`）在 `os.rename` 前已存在，直接抛出 `FileExistsError`，任务进入 `failed` 状态
- mover **不自动改名**（不加 `_000` 后缀）；冲突解决是调用方的职责

**要求 unzipper 配合**：`watcher.py` 的 `on_created` 必须过滤 `.` 开头的目录名，否则 staging 目录仍会被触发。

---

## 跨文件系统处理

通过比较 `os.stat(src).st_dev` 和 `os.stat(dst_parent).st_dev` 判断：

| 场景 | 处理方式 | 时间复杂度 |
|------|----------|------------|
| 同文件系统 | `shutil.copytree` 到 staging，然后 `os.rename` | 取决于文件数量，rename 瞬间 |
| 跨文件系统 | `shutil.copytree` 到 staging（跨盘实际复制），然后 `os.rename` staging 到 final（同 fs，原子），最后删源文件 | 取决于文件大小和 IO 速度 |

跨文件系统时，staging 目录和 target 在同一文件系统（staging 创建在 target_parent 下），所以第二步 `rename` 始终是原子操作。

---

## 幂等性

每个请求必须携带 `task_id`，mover 根据 task_id 的当前状态决定行为：

| 当前状态 | 行为 | 响应 |
|----------|------|------|
| 不存在 | 新建任务，入队 | `{"ok": true, "task_id": "..."}` |
| `pending` | 幂等，任务已在队列 | `{"ok": true, "in_progress": true, "task_id": "..."}` |
| `copying` | 幂等，任务正在搬运 | `{"ok": true, "in_progress": true, "task_id": "..."}` |
| `done` | 幂等，不重复搬运 | `{"ok": true, "already_moved": true, "target_path": "..."}` |
| `failed` | 覆盖旧记录，重新入队 | `{"ok": true, "task_id": "...", "retrying": true}` |

**设计依据**：downloader 在重启后可能重发同一 task_id 的 move 请求，幂等性保证不会造成重复搬运或出错。

---

## 持久化 Schema（mover_state.json）

```json
{
  "msg_group_123": {
    "task_id":         "msg_group_123",
    "source":          "/downloads/telegram/频道名/20260423_video",
    "target":          "/watch/频道名/20260423_video",
    "status":          "done",
    "created_at":      "2026-04-23T10:00:00.000000",
    "completed_at":    "2026-04-23T10:00:00.250000",
    "error":           null,
    "files_attempted": 3,
    "files_completed": 3,
    "failed_at":       null,
    "error_source":    null,
    "is_cross_fs":     false,
    "total_size":      104857600
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 调用方提供的唯一标识 |
| `source` | string | 源路径（绝对路径） |
| `target` | string | 搬运后的最终路径（done 时填入，等于 `target_parent/source_basename`） |
| `status` | string | `pending` / `copying` / `done` / `failed` |
| `created_at` | ISO datetime string | 任务创建时间 |
| `completed_at` | ISO datetime string \| null | 完成时间（done 或 failed 时填入） |
| `error` | string \| null | 失败原因描述；`done` 状态下也可能非 null（见下方说明） |
| `files_attempted` | int | 已尝试搬运的文件数 |
| `files_completed` | int | 成功完成的文件数 |
| `failed_at` | ISO datetime string \| null | **失败时间戳**（P2-10 修复后；旧版本错误地存路径，启动时自动迁移） |
| `error_source` | string \| null | **导致失败的具体文件路径**（P2-10 新增；从旧 `failed_at` 迁移而来） |
| `is_cross_fs` | bool | 是否为跨文件系统搬运 |
| `total_size` | int \| null | 源路径总大小（字节），扫描时填入 |

写入策略：每次状态变化立即写入（先写临时文件再 `rename`，避免写入中断导致文件损坏）。

> **done + error 非 null**：当 target 已完整就位（`os.rename` 成功），但清理源文件时发生异常，任务仍标记为 `done`，同时 `error` 字段写入警告（如 `"搬运成功但源文件清理失败：..."`）。调用方可以定期扫描 `status=done && error is not null` 的任务进行手动清理。

---

## 失败恢复（启动时）

```
mover 启动
    │
    ├─ 1. 加载 mover_state.json
    │
    ├─ 2. 扫描所有 status=copying 的任务
    │      ├─ 在 target_parent 下查找 .mover_staging_* 目录
    │      ├─ 找到 → shutil.rmtree(staging)
    │      └─ 标记任务为 failed（error: "进程中断，staging 已清理"）
    │
    ├─ 3. 扫描所有已知 target_parent 下的孤儿 .mover_staging_* 目录
    │      （可能来自未记录在 state.json 中的旧版 staging）
    │      └─ shutil.rmtree(孤儿目录)
    │
    └─ 4. 启动完成，开始接受请求
```

**孤儿目录扫描范围**：启动时从 `mover_state.json` 收集所有出现过的 `target_parent` 路径，逐一扫描。首次启动无已知路径时跳过。

---

## 并发控制

```python
_semaphore = asyncio.Semaphore(config.MOVER_MAX_CONCURRENT)

async def _do_move(task_id: str):
    async with _semaphore:
        state.tasks[task_id]["status"] = "copying"
        await _broadcast()
        try:
            await _execute_move(task_id)
            state.tasks[task_id]["status"] = "done"
        except Exception as e:
            state.tasks[task_id]["status"] = "failed"
            state.tasks[task_id]["error"] = str(e)
        finally:
            storage.save_tasks(state.tasks)
            await _broadcast()
```

与 unzipper 的 `asyncio.Semaphore` 模式完全一致。`status=pending` 的任务已入队但尚未获取 Semaphore。

---

## 与 downloader / unzipper 的交互时序

```
downloader                    mover                    文件系统           unzipper
    │                           │                          │                  │
    │ POST /api/move             │                          │                  │
    │ {source, target, task_id} │                          │                  │
    │──────────────────────────▶│                          │                  │
    │◀── {ok, task_id} ─────────│                          │                  │
    │                           │  mkdir .staging_xxx/     │                  │
    │                           │─────────────────────────▶│                  │
    │                           │  copytree(source → stg)  │                  │
    │                           │─────────────────────────▶│                  │
    │                           │  rename(stg → final)     │                  │
    │                           │─────────────────────────▶│                  │
    │                           │                          │  inotify IN_MOVED_TO │
    │                           │                          │─────────────────▶│
    │  WebSocket: {done}        │                          │    触发解压       │
    │◀──────────────────────────│                          │                  │
    │                           │                          │                  │
```
