# 下载历史分页、排序与解压状态追踪设计

> **状态**：✅ 已实现。本文档定义 `completed.json` 上限调整、新增 `/api/history` 分页接口、8 状态解压追踪机制和前端 UI。

## 背景

- 当前 `MAX_HISTORY=100` 太小，超出即裁剪
- 完成的下载记录里**没有解压状态信息**——用户只能跳到 unzipper UI 才能查
- 没有分页、排序、筛选支持

## 总览

| 功能 | 改动 |
|---|---|
| 历史存储 | `MAX_HISTORY` 100 → 5000（仍是硬上限）|
| 分页接口 | 新建 `GET /api/history`；`/api/status` 不变 |
| 解压状态追踪 | 8 状态 + downloader 同时查 mover + unzipper |
| 前端 | 分页 + 排序 + 筛选 + 状态徽章 |

---

## 存储变更

| 变量 | 旧 | 新 |
|---|---|---|
| `MAX_HISTORY` | 100 | **5000**（硬上限）|
| `completed.json` 文件大小估算（5000 条） | — | ~5 MB |
| `json.load()` 实测耗时 | ~1ms | ~40ms |

`MAX_HISTORY` 仍是硬上限（与 `MOVER_MAX_HISTORY=500` 命名风格一致）。超过 5000 时按 `finished_at` 倒序裁剪最旧。

前端"已完成"区域标题旁显示：`共 1234 条 / 上限 5000 条`。

---

## API 设计

### `GET /api/status`（不改语义，仅加字段）

现有响应基础上**新增字段**：

```json
{
  "active":           [...],
  "completed":        [... 最近 100 条 ...],   // 兼容：仍返回前 100 条
  "completed_total":  1234,                     // 新增：历史总数
  "watched":          {...},
  "total_speed":      ...,
  "paused":           false
}
```

`completed` 字段保持"返回最近 100 条"，dashboard 等现有 caller 不受影响。

### `GET /api/history`（新建）

专做分页、排序、筛选。

#### 查询参数

| 参数 | 默认 | 范围 / 取值 |
|---|---|---|
| `limit` | `50` | 1–200 |
| `offset` | `0` | ≥ 0 |
| `sort_by` | `finished_at` | `filename` / `filesize` / `status` / `finished_at` / `queued_at` / `extract_status` |
| `sort_order` | `desc` | `asc` / `desc` |
| `filter_status` | 不传 | 逗号分隔的解压状态（见下），多值取并集；不传 = 不过滤 |

#### 响应

```json
{
  "ok": true,
  "items": [
    {
      "task_id":             "...",
      "label":               "...",
      "filename":            "...",
      "size_mb":             123.4,
      "status":              "done",
      "queued_at":           1777200000.0,
      "started_at":          1777200015.0,
      "finished_at":         1777200120.0,
      "path":                "...",
      "chat_id":             ...,
      "message_id":          ...,
      "extract_status":      "extracted",
      "extract_output_path": "/HydenFileSystem/Extracted/foo/"
    }
  ],
  "total":  1234,
  "offset": 0,
  "limit":  50
}
```

`extract_status` / `extract_output_path` 是新加字段（详见下方"解压状态追踪"）。

#### 排序逻辑

后端在内存里对 `state.completed_downloads` 切片前临时排序：

```python
key_map = {
    "filename":       lambda r: r.get("filename") or "",
    "filesize":       lambda r: r.get("total") or 0,
    "status":         lambda r: r.get("status") or "",
    "finished_at":    lambda r: r.get("finished_at") or 0,
    "queued_at":      lambda r: r.get("queued_at") or 0,
    "extract_status": lambda r: r.get("extract_status") or "",
}
items = sorted(state.completed_downloads, key=key_map[sort_by], reverse=(sort_order == "desc"))
if filter_status:
    items = [i for i in items if i.get("extract_status") in filter_status_set]
total = len(items)
items = items[offset:offset+limit]
```

每次 API 请求**临时**排序——在 5000 条数据上 `sorted()` 耗时 ~5ms，加上切片 ~10ms，可接受。

需 `X-API-Key`（走 `auth_middleware`）。

---

## 解压状态追踪

### 8 个状态值

| 状态 | 含义 | 来源 |
|---|---|---|
| `not_archive` | 不是压缩包（扩展名不在 ARCHIVE_EXTS）| **downloader 本地判断**（无需查询）|
| `ready` | 是压缩包，未提交 mover（如 `AUTO_MOVE=false` 或 mover 暂停未执行）| downloader 本地判断 |
| `moving` | mover 任务 status=`copying` 或 `pending` | **mover 查询** |
| `move_failed` | mover 任务 status=`failed` | mover 查询 |
| `pending_extract` | mover done，但 unzipper 还没看到 / 或在 unzipper 队列里等待 | **unzipper 查询** |
| `extracting` | 在 unzipper `current_tasks` 里 | unzipper 查询 |
| `extracted` | unzipper history 中 status=`done` | unzipper 查询 |
| `extract_failed` | unzipper history 中 status=`failed` | unzipper 查询 |

### downloader 同时查 mover + unzipper

每 5 秒（与 WebSocket 广播协调），downloader 后端**并发**：

```python
async def refresh_extract_statuses():
    # 1) 收集需要查询的任务
    archive_tasks = [r for r in state.completed_downloads
                     if _is_archive(r["filename"])]
    if not archive_tasks:
        return

    # 2) 并发查 mover 和 unzipper
    mover_tasks = [r["task_id"] for r in archive_tasks]
    unzipper_filenames = [Path(r["filename"]).name for r in archive_tasks]

    mover_states, unzipper_states = await asyncio.gather(
        _fetch_mover_states(mover_tasks),       # 见下
        _fetch_unzipper_states(unzipper_filenames),
    )

    # 3) 融合
    for r in archive_tasks:
        r["extract_status"], r["extract_output_path"] = _compute_status(
            r, mover_states.get(r["task_id"]), unzipper_states.get(Path(r["filename"]).name)
        )
```

#### `_fetch_mover_states(task_ids)`

调用 mover 已有的 `GET /api/tasks/{task_id}`：

```python
async def _fetch_mover_states(task_ids):
    headers = {"X-API-Key": config.API_KEY}
    async with aiohttp.ClientSession(headers=headers) as session:
        results = await asyncio.gather(
            *(_fetch_one_mover(session, tid) for tid in task_ids),
            return_exceptions=True,
        )
    return {tid: r for tid, r in zip(task_ids, results) if not isinstance(r, Exception)}

async def _fetch_one_mover(session, task_id):
    url = f"http://127.0.0.1:{config.MOVER_PORT}/api/tasks/{task_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
            if resp.status == 200:
                return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass
    return None
```

可优化：mover 加批量查询 `POST /api/tasks/batch` body=`{"ids":[...]}`（v1 不做，逐个 GET 也够用，task_id 数量不大）。

#### `_fetch_unzipper_states(filenames)`

调用 unzipper **新增**的 `POST /api/extract-status`：

```python
async def _fetch_unzipper_states(filenames):
    url = f"http://127.0.0.1:{config.UNZIPPER_PORT}/api/extract-status"
    payload = {"filenames": filenames}
    headers = {"X-API-Key": config.API_KEY, "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
    return {}
```

#### `_compute_status` 融合规则

```python
def _compute_status(record, mover_state, unzipper_state):
    if not _is_archive(record["filename"]):
        return ("not_archive", None)

    # 优先看 unzipper（终态）
    if unzipper_state:
        s = unzipper_state.get("status")
        if s == "extracted":
            return ("extracted", unzipper_state.get("output_path"))
        if s == "extract_failed":
            return ("extract_failed", None)
        if s == "extracting":
            return ("extracting", None)
        if s == "pending_extract":
            return ("pending_extract", None)

    # 再看 mover
    if mover_state:
        s = mover_state.get("status")
        if s in ("copying", "pending"):
            return ("moving", None)
        if s == "failed":
            return ("move_failed", None)
        if s == "done":
            # mover done 但 unzipper 还没看到
            return ("pending_extract", None)

    # 不在 mover（如 AUTO_MOVE=false）
    return ("ready", None)
```

#### 融合优先级理由

unzipper 的状态比 mover **更新**——文件先经过 mover，再进 unzipper。如果 unzipper 已经看到（任意状态），那 mover 必然已 done。所以 unzipper 状态是 truth-of-record；只有 unzipper 没数据时才 fallback 到 mover。

### Unzipper 新增端点：`POST /api/extract-status`

#### 协议

```
POST /api/extract-status
Content-Type: application/json
X-API-Key: ...

Body:
{
  "filenames": ["x.zip", "y.rar", "z.7z.001"]
}

Response:
{
  "x.zip": {
    "status": "extracted",
    "output_path": "/HydenFileSystem/Extracted/x/",
    "finished_at": "2026-04-27T10:00:00"
  },
  "y.rar": {
    "status": "extracting",
    "output_path": null,
    "finished_at": null
  },
  "z.7z.001": null
}
```

`null` 值表示 unzipper 不知道这个文件（可能还在 mover 流程中、或不曾出现）。

#### filename 索引规则

unzipper 内部按 `name`（文件名，不含路径）索引：

```python
# unzipper/web/api.py
async def _api_extract_status(request):
    body = await request.json()
    filenames = body.get("filenames", [])
    result = {}
    for fname in filenames:
        # 1) current_tasks
        for task in state.current_tasks.values():
            if Path(task.get("path", "")).name == fname:
                result[fname] = {"status": "extracting", "output_path": None, "finished_at": None}
                break
        else:
            # 2) pending_multipart
            for rec in state.pending_multipart.values():
                if Path(rec.get("path", "")).name == fname:
                    result[fname] = {"status": "pending_extract", "output_path": None, "finished_at": None}
                    break
            else:
                # 3) history
                for h in reversed(state.history):
                    if h.get("name") == fname:
                        s = h.get("status")
                        if s == "done":
                            result[fname] = {"status": "extracted", "output_path": h.get("out_dir"), "finished_at": h.get("finished_at")}
                        else:
                            result[fname] = {"status": "extract_failed", "output_path": None, "finished_at": h.get("finished_at")}
                        break
                else:
                    result[fname] = None
    return web.json_response(result)
```

需 `X-API-Key`。

#### 同名文件冲突

理论场景：两次下载 `archive.zip`（来自不同消息）。unzipper 以 filename 索引，可能返回错误的状态。

实际场景：mover 不允许覆盖（之前测试过冲突会标 `failed`），所以 WATCH_PATH 永远只会有一个 `archive.zip`。unzipper 处理后移到 OUTPUT_PATH 子目录里，不在 WATCH_PATH 留同名。

**结论**：filename 唯一在实际系统行为下成立。如果未来发现问题，再升级到"path 全匹配"或"task_id 持久化"。

---

## 关联键策略（前端聚合）

### 后端无概念

**API 协议层只用 filename**——后端不知道 group_id 或 task_id 的聚合关系。

### 前端聚合规则

下载历史展示时，多文件 group 合并成一行：

| 关联场景 | 聚合键 | 行为 |
|---|---|---|
| `grouped_id` 不为 null | `group_id` | 同 group 多条合并为一行（已有 `_group_dirs` 设计）|
| `grouped_id` 为 null | `task_id`（即 `{chat_id}_{message_id}`）| 单独一行 |
| 查重跳过的（P1-5b 后）| `task_id` | 单独一行 |

### 行级状态聚合（前端 JS）

```js
function aggregateGroupStatus(items) {
  // items: 同一 group_id 下的多条记录
  const statuses = items.map(i => i.extract_status);
  if (statuses.every(s => s === "extracted"))     return "extracted";
  if (statuses.some(s => s === "extract_failed")) return "extract_failed";
  if (statuses.some(s => s === "extracting"))     return "extracting";
  if (statuses.some(s => s === "moving"))         return "moving";
  if (statuses.some(s => s === "move_failed"))    return "move_failed";
  if (statuses.some(s => s === "pending_extract")) return "pending_extract";
  if (statuses.every(s => s === "ready"))         return "ready";
  if (statuses.every(s => s === "not_archive"))   return "not_archive";
  return "ready";  // 混合 fallback
}
```

---

## 前端变更

### 分页控件（已完成区域底部）

```
┌────────────────────────────────────────────┐
│ [< 上一页]  第 3 页 / 共 47 页  [下一页 >]   │
│                       每页：[50 ▼]           │
└────────────────────────────────────────────┘
```

每页选项：20 / 50 / 100。状态持久化到 localStorage（`history_page_size`）。

### 排序控件（已完成区域标题行）

```
排序: [文件名 ↑↓] [文件大小 ↑↓] [状态 ↑↓] [完成时间 ↑↓ ✓] [解压状态 ↑↓]
```

点击切换升序/降序；当前排序维度高亮（如打勾）。

localStorage：`history_sort_by` / `history_sort_order`。

### 完成时间格式

改为 `YYYY-MM-DD HH:MM:SS`（含日期）。前端工具函数：

```js
const fdatetime = ts => ts
  ? new Date(ts*1000).toLocaleString('sv-SE').replace('T', ' ')   // sv-SE locale 给 ISO 风格
  : '-';
```

### 筛选 UI

多选下拉位于已完成区域标题行旁：

```
筛选解压状态: [全部 ▼]
              □ not_archive
              □ ready
              □ moving
              □ move_failed
              □ pending_extract
              □ extracting
              □ extracted
              □ extract_failed
              [清空] [应用]
```

选中的状态拼成 `?filter_status=extracted,extract_failed` 传给 `/api/history`。

### 解压状态徽章

每行右侧显示徽章：

| 状态 | 颜色 | 文案 | 交互 |
|---|---|---|---|
| `not_archive` | 灰色 | 「非压缩」 | — |
| `ready` | 蓝色 | 「可解压」 | 鼠标悬停："等待 mover 触发"|
| `moving` | 黄色 | 「搬运中」 | — |
| `move_failed` | 红色 | 「搬运失败」 | 鼠标悬停显示错误；点击重试（调 mover `POST /api/tasks/{id}/retry`） |
| `pending_extract` | 黄色 | 「等待解压」 | — |
| `extracting` | 蓝色（动画）| 「解压中」 | — |
| `extracted` | 绿色 | 「已解压」 | 点击显示输出路径 + [打开] 按钮 |
| `extract_failed` | 红色 | 「解压失败」 | 鼠标悬停显示错误 |

---

## 与折叠功能（P1-5a Q3）的兼容

折叠状态独立：

- 折叠后整个已完成区域（含分页 + 排序控件 + 列表）一起隐藏
- 展开恢复，但**当前页码、排序、筛选状态保留**（localStorage）

---

## 性能与扩展性边界

| 数据规模 | 文件大小 | `json.load` | `sorted` + 切片 | 总响应 |
|---|---|---|---|---|
| 100 条 | ~95 KB | ~1ms | <1ms | <5ms |
| 1000 条 | ~1 MB | ~10ms | ~1ms | <15ms |
| 5000 条（上限）| ~5 MB | ~40ms | ~5ms | ~50ms |
| 10000 条（超限，被裁剪不会发生）| ~10 MB | ~80ms | ~10ms | ~100ms |

5000 条上限保证响应在 50ms 内，可接受。

如未来用户真需要更大规模，迁移到 JSON Lines 格式 + 行索引（详见 `调研报告` C2 / C3 方案，留作 v2）。

---

## 不在本次范围

- **手动触发解压按钮**（`ready` 状态徽章上的"立即解压"功能）—— 需要 downloader 主动调 mover，超出 P1-8 范围
- **解压进度百分比**（`extracting` 状态显示百分比）—— P2-2 的范围
- **跨 session 持久化排序/筛选偏好**（除 localStorage 外的服务端持久化）
- **批量重试**（多选 `move_failed` / `extract_failed` 一起重试）
