# 监听列表优化设计

> **状态**：✅ 已实现。本文档定义 `watched_chats.json` 的结构升级、计数语义、UI 排序与统计控制。

## 背景

当前监听列表只显示频道名，无排序、无统计、无折叠。`watched_chats.json` 结构是 `{cid: name}` 扁平 dict，缺少元信息。

## 数据结构变更

### 新结构

```json
{
  "{chat_id}": {
    "name": "频道名",
    "watched_since":         "2026-04-27T10:30:00.123456",
    "task_count":            47,
    "task_count_reset_at":   null
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 频道显示名（与旧字段同语义）|
| `watched_since` | ISO 8601 | 开始监听的时间戳；监听一旦添加不变 |
| `task_count` | int | 累计触发的下载任务数（从 `watched_since` 或上次重置至今）|
| `task_count_reset_at` | ISO 8601 \| null | 上次重置统计的时间戳（`null` 表示从未重置） |

### 加载时迁移

`storage.load_watched()` 检测到旧结构（值是 `str`）自动迁移：

```python
def load_watched():
    raw = json.load(...)
    migrated = {}
    for cid, val in raw.items():
        if isinstance(val, str):
            # 旧格式 {cid: name}
            migrated[cid] = {
                "name": val,
                "watched_since": datetime.now().isoformat(),
                "task_count": 0,
                "task_count_reset_at": None,
            }
        else:
            migrated[cid] = val
    if any(isinstance(v, str) for v in raw.values()):
        save_watched(migrated)  # 一次性持久化迁移结果
    return migrated
```

迁移后保存到磁盘——下次启动不再需要迁移。`watched_since` 对旧条目用**迁移时刻**作为占位（无法恢复真实历史）。

---

## 计数触发

### 触发位置

**`handle_media` 入口**——一旦开始处理消息（创建 `download_one` task），就 +1：

```python
@client.on(events.NewMessage(incoming=True))
async def handle_media(event):
    if state.monitoring_paused:
        return
    if event.message.date < state.bot_start_time:
        return
    cid = str(event.chat_id)
    if cid not in state.watched:
        return
    if not message.media or isinstance(message.media, MessageMediaWebPage):
        return

    # P1-7：计数（不管后续成功失败，触发即计）
    state.watched[cid]["task_count"] += 1
    storage.save_watched(state.watched)

    # ... (existing logic)
```

### 计数语义（明确）

- **触发即计**：消息到达 + 通过白名单/暂停/类型过滤 + 进入下载流水线 = +1
- **不区分成功/失败**：done / error / timeout / cancelled 都计数
- **dedup 跳过的消息（P1-5b）不计数**：因为它们在更早的判断里 return（在计数代码之前）
- **同一 grouped_id 内的多条消息**：每条单独计数（一个 group 5 个媒体 = task_count +5）

理由：`task_count` 反映"该频道触发了多少下载尝试"，不是"成功收到多少文件"。计数逻辑简单、写入位置唯一，避免分布在多个回调里。

### 持久化时机

- 每次 `task_count += 1` 后立即 `save_watched`
- 高频触发时可优化（节流到 1s 一次），v1 不做

---

## UI 功能规格

### 折叠

复用 P1-5a Q3 的 `setupToggle()` 机制：

- 监听列表区域 h2 加 `id="wl-toggle"` + `id="wl-arrow"`
- 内容包裹层加 `id="wl-panel"`
- localStorage key: `wl_section_collapsed`
- 默认展开

### 四维排序

| 排序维度 | 字段 |
|---|---|
| 频道名 | `name`（中文用 localeCompare）|
| 监听时间 | `watched_since`（ISO 字符串可直接字典序比较）|
| 任务数 | `task_count` |
| 添加顺序（默认）| 字典 key 的迭代顺序（Python 3.7+ 保证）|

每种维度支持**升序 / 降序**。点击表头切换。

### 排序状态持久化

localStorage：

- `wl_sort_by` ∈ `name` / `watched_since` / `task_count` / `default`
- `wl_sort_order` ∈ `asc` / `desc`

默认：`default` + `asc`（跟现状一致）。

### 每行显示

```
┌──────────────────────────────────────────────────────────────┐
│ 频道名                监听: 2026-04-15 10:30   任务: 47   ✕  │
│ ID: -100123456789                              🔄            │
└──────────────────────────────────────────────────────────────┘
```

字段：

- 频道名（粗体）
- ID（小字色暗）
- 监听时间：`watched_since`，格式 `YYYY-MM-DD HH:MM`
- 任务数：`task_count`（如果 `task_count_reset_at` 不是 null，显示 tooltip "自 YYYY-MM-DD 起"）
- 🔄 单行清零按钮：仅重置该频道 `task_count = 0`，`task_count_reset_at = now`，`watched_since` **不变**
- ✕ 删除监听按钮（现有功能保留）

### 列表顶部控制

```
┌─ 监听列表 ▼  [⏸ 暂停监听]  ─────────────────────────────────┐
│ 排序：[频道名 ↓] [监听时间 ↓] [任务数 ↓] [默认 ↓]             │
│ [重置所有统计]                                                  │
├──────────────────────────────────────────────────────────────┤
│ ... entries ...                                                 │
└──────────────────────────────────────────────────────────────┘
```

[重置所有统计] 按钮：所有频道 `task_count = 0`，`task_count_reset_at = now`，需二次确认（`confirm()`）。

---

## API 变更

### 现有 `/api/state`（修改）

`watched` 字段从 `{cid: name}` 改为新结构：

```json
"watched": {
  "{cid}": {
    "name": "...",
    "watched_since": "...",
    "task_count": 47,
    "task_count_reset_at": null
  }
}
```

前端旧代码可能假设 `watched[cid]` 是字符串——升级前检查。

### 新增端点

| 端点 | 方法 | 行为 |
|---|---|---|
| `/api/watch/reset-stats` | POST | 全部归零；返回 `{"ok": true, "reset_count": N}` |
| `/api/watch/{cid}/reset-stats` | POST | 单频道归零；不存在返回 404 |

均需 `X-API-Key`（走 `auth_middleware`）。

注意 `cid` 可能是负数（`-100123...`），路由变量需要 URL-decode。

---

## 兼容性

- **旧 `watched_chats.json` 自动迁移**——加载时检测旧格式 + 持久化迁移结果（一次性）
- **前端代码必须假设新结构**——旧代码 `entries[i][1]` 是字符串的逻辑要改成 `entries[i][1].name`

---

## 不在本次范围

- 自动节流持久化（高频更新触发频繁 disk IO 时再做）
- 频道分组 / 标签
- 跨频道统计（如"过去 7 天每个频道任务数"图表）
