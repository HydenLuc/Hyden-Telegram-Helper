# 三模块协作规范

本文档描述 downloader、mover、unzipper 三个模块的集成协议。

---

## 交互模式

```
downloader._finish() 检测到压缩包
    │
    │  POST http://localhost:{MOVER_PORT}/api/move
    │  {"source": "/downloads/x.zip", "target": "/watch/"}
    ▼
mover.manager.submit(source, target)
    │
    │  两步原子搬运：
    │    1. 创建 /watch/.mover_staging_<uuid>/x.zip（watchdog 不可见）
    │    2. os.rename → /watch/x.zip（原子，watchdog 仅看到完整文件）
    ▼
文件系统（watchdog 检测到 /watch/x.zip 的 rename 事件）
    │
    ▼
unzipper.manager.submit(path)
    ▼
解压流程
```

**为什么需要 mover？**

不经过 mover 直接 `POST /api/submit` 存在两个问题：
1. **竞争条件**：下载期间文件未写完，watchdog 就可能触发（大文件尤甚）
2. **重复提交**：若 `WATCH_PATH == DOWNLOAD_DIR`，直接调用和 watchdog 会对同一文件各提交一次

mover 的两步原子搬运彻底解决这两个问题：暂存目录以 `.` 开头，watchdog 不感知；`os.rename` 是内核原子操作，watchdog 只看到完整文件。

---

## 配置

```dotenv
AUTO_MOVE=true           # 下载完成后自动通知 mover，默认 true
MOVER_PORT=8092          # mover API 端口
```

`config.py` 读取：

```python
AUTO_MOVE: bool = os.getenv("AUTO_MOVE", "true").lower() == "true"
MOVER_PORT: int = int(os.getenv("MOVER_PORT", 8092))
```

---

## 触发点

> **实现状态**：已实现；downloader 在 `_finish()` fire-and-forget 调用 `auto_submit_to_mover`。

**文件**：`downloader/download/manager.py`，`_finish()` 函数

**触发条件**：
- `status == "done"`（下载成功）
- `config.AUTO_MOVE is True`
- 文件扩展名在 `ARCHIVE_EXTS` 中，或文件名匹配 `.7z\.\d+$`

```python
MULTIPART_RE = re.compile(r'\.7z\.\d+$')

def _should_auto_move(file_path: Path) -> bool:
    return (
        config.AUTO_MOVE
        and (file_path.suffix.lower() in ARCHIVE_EXTS
             or bool(MULTIPART_RE.search(file_path.name)))
    )
```

---

## HTTP 接口协议

### 请求

```
POST http://localhost:{MOVER_PORT}/api/move
Content-Type: application/json

{
  "source": "/abs/path/to/archive.zip",
  "target": "/abs/path/to/watch_dir/"
}
```

`source` 和 `target` 必须是绝对路径，`source` 文件必须已存在。

### 成功响应

任务新建：

```json
{
  "ok": true,
  "task_id": "abc123",
  "status": "pending"
}
```

幂等（任务已完成）：

```json
{
  "ok": true,
  "task_id": "abc123",
  "status": "done",
  "already_moved": true
}
```

任务进行中：

```json
{
  "ok": true,
  "task_id": "abc123",
  "status": "copying",
  "in_progress": true
}
```

### 失败响应

```json
{"ok": false, "error": "source does not exist"}
```

完整错误码见 [mover/docs/api.md](../mover/docs/api.md#post-apimove)。

---

## 失败处理

| 场景 | 处理方式 |
|------|----------|
| mover 服务未启动（连接拒绝） | 静默忽略，打印 `[downloader→mover] 跳过：mover 不可达` |
| mover 返回 4xx（路径问题） | 静默忽略，打印错误信息 |
| mover 返回 5xx | 静默忽略，打印错误信息 |
| `AUTO_MOVE=false` | 不发请求，watchdog 作为兜底（若 WATCH_PATH 覆盖 DOWNLOAD_DIR） |

所有失败均**不影响下载完成流程**（`_finish` 已完成，`completed_downloads` 已更新）。

---

## 日志约定

```
[downloader→mover] 提交搬运：archive.zip → task_id=abc123
[downloader→mover] 提交搬运失败（mover 不可达）：archive.zip
[downloader→mover] 提交搬运失败（400 source does not exist）：archive.zip
```

前缀格式：`[downloader→mover]` 表明跨模块调用，便于日志过滤。

---

## 实现示例（伪代码）

```python
# downloader/download/manager.py

import aiohttp

async def _auto_submit_to_mover(file_path: Path, target: Path):
    url = f"http://localhost:{config.MOVER_PORT}/api/move"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url,
                                    json={"source": str(file_path),
                                          "target": str(target)},
                                    timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    print(f"[downloader→mover] 提交搬运：{file_path.name} → task_id={data.get('task_id')}")
                else:
                    print(f"[downloader→mover] 提交搬运失败（{data.get('error')}）：{file_path.name}")
    except aiohttp.ClientConnectorError:
        print(f"[downloader→mover] 提交搬运失败（mover 不可达）：{file_path.name}")
    except Exception as e:
        print(f"[downloader→mover] 提交搬运失败（{e}）：{file_path.name}")


def _finish(task_id: str, status: str, error_msg: str = ""):
    rec = state.active_downloads.pop(task_id, None)
    # ... 原有逻辑 ...

    if status == "done" and rec:
        file_path = Path(rec.get("path", ""))
        if file_path.exists() and _should_auto_move(file_path):
            target = Path(config.WATCH_PATH)
            asyncio.create_task(_auto_submit_to_mover(file_path, target))
```

---

## Mover → Unzipper 衔接

mover 完成搬运后，unzipper 的 watchdog 通过以下流程接手：

| 步骤 | 说明 |
|------|------|
| `os.rename` 触发事件 | watchdog 收到 `FileMovedEvent`（dest=`WATCH_PATH/filename`），仅感知目标路径；暂存源路径因 `.` 前缀被过滤（见 P1-3） |
| 文件命名约定 | 最终文件名 = `target` 父目录 + `source` 的 basename。mover 不对文件名做任何修改。 |
| 稳定性检测 | watcher 等待 2s 内大小不变后入队；文件已通过 `os.rename` 完整落盘，通常立即通过 |
| 提交解压 | `unzipper.manager.submit(WATCH_PATH / filename)` |

**暂存目录位置**：`.mover_staging_<uuid>/` 创建在 `target` 目录内（即 `WATCH_PATH` 内），确保 `os.rename` 在同一文件系统上执行（内核原子操作）。unzipper 通过 P1-3 的隐藏目录过滤屏蔽暂存目录的中间事件。

---

## unzipper 侧：隐藏目录过滤

mover 暂存目录以 `.mover_staging_` 开头。unzipper 的 watchdog 需过滤这类目录，避免对中间状态文件触发解压：

```python
# unzipper/watcher.py

def on_created(self, event):
    if any(p.startswith('.') for p in Path(event.src_path).parts):
        return
    # ... 原有逻辑 ...
```

---

## 推荐目录配置

```dotenv
DOWNLOAD_DIR=/downloads/telegram    # downloader 写入目录
WATCH_PATH=/downloads/watch         # mover 搬运目标 = unzipper 监听目录
OUTPUT_PATH=/extracted               # unzipper 解压输出目录
```

三个目录不重叠，数据流清晰：`DOWNLOAD_DIR → WATCH_PATH → OUTPUT_PATH`。

---

## 与旧直接调用方案的对比

旧方案：下载完成后直接 `POST /api/submit` 给 unzipper，跳过 mover。

| | 旧方案（直接调用 /api/submit） | 新方案（经过 mover） |
|-|-------------------------------|----------------------|
| 竞争条件 | ❌ 可能在文件写入期间触发 | ✅ 两步暂存，watchdog 只看到完整文件 |
| 重复解压 | ❌ watchdog + 直接调用各触发一次 | ✅ watchdog 只触发 rename 事件，单次 |
| 原子性 | ❌ 文件可能半写 | ✅ `os.rename` 内核原子操作 |
| 跨 FS | ❌ 未处理 | ✅ `shutil.copytree` + 验证 |
| 可观测性 | ❌ fire-and-forget，无状态 | ✅ REST API 查询任务状态，WebSocket 实时推送 |
