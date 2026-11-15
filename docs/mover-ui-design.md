# Mover 前端 UI 设计

> **状态**：✅ 已实现。本文档定义 mover 的完整 Web 前端，参考 downloader / unzipper 的样式与交互风格。

## 背景

`mover/web/templates.py` 自项目创建以来只有占位注释（`WEB_HTML = "<!-- mover web UI: not yet implemented -->"`），从未实现。`mover/web/api.py:_index_handler` 返回 76 字节 inline HTML：

```python
text=f"<html><body><h1>Mover Service</h1><p>Running: {running} | Total: {len(tasks)}</p></body></html>"
```

dashboard 卡片虽展示 mover 状态（搬运中 / 失败 / 总数），但用户无法在 mover 自己的页面查看详细任务流、错误原因或重试。

---

## 设计目标

1. 与 downloader / unzipper 前端**风格一致**（深色主题、CSS Grid 响应式）
2. **移动端友好**（手机竖屏单列）
3. 复用已有约定：`__API_KEY__` 占位符注入、apiFetch 包装、setupToggle 折叠
4. 暴露 P1-5a Q4 已实现但缺前端的**软暂停**功能
5. **不**做控制路径修改的 UI（mover 不持有 WATCH_PATH，详见 `path-config-design.md`）

---

## 页面结构

```
┌─────────────────────────────────────────────────────────────────┐
│ 🚚 Mover  [● 待机]                          [⏸ 暂停] [▶ 恢复] │  ← 顶部
├─────────────────────────────────────────────────────────────────┤
│ ┌─ 统计 ─────────────────────────────────────────────────────┐ │
│ │ 搬运中: 2    历史总数: 137    失败: 1 ⚠                     │ │
│ └────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ 集合点路径（只读）──────────────────────────────────────────┐│
│ │ /HydenFileSystem/Archives        ← 5 个进行中任务            ││
│ │ /legacy/path/old                  ← 2 个进行中任务           ││
│ │ ℹ 集合点路径在 Downloader 或 Unzipper 页面修改               ││
│ └────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ 搬运中（2） ▼ ────────────────────────────────────────────┐ │
│ │ ▸ archive_001.zip                                           │ │
│ │   /Telegram/foo/archive_001.zip → /HydenFileSystem/Archives │ │
│ │   开始: 14:23:01 | 状态: 搬运中...                           │ │
│ │ ▸ video_pack.7z                                             │ │
│ │   ...                                                        │ │
│ └────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ 历史（135） ▶ ─ [清空历史] ─────────────────────────────┐ │
│ │ (折叠中)                                                    │ │
│ └────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ [● 已连接]                                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 各区域规格

### 1. 顶部状态栏

| 元素 | 行为 |
|---|---|
| `🚚 Mover` 标题 | 静态 |
| 状态 badge | `● 待机`（idle）/ `● 搬运中`（busy = running_tasks > 0）；颜色随状态切换 |
| 暂停 / 恢复按钮 | P1-5a Q4 的 API 已存在；按钮文案与配色复用 downloader / unzipper 模式：未暂停 → 灰色「⏸ 暂停」；已暂停 → 橙色「▶ 恢复」|

### 2. 统计区域

横向排列三个数字：

| 字段 | 数据源（`/api/health` 已有）|
|---|---|
| 搬运中 | `running_tasks` |
| 历史总数 | `total_tasks` |
| 失败 | `failed_tasks`（> 0 时高亮黄色 + ⚠ icon）|

### 3. 集合点路径（只读聚合显示）

mover **不持有 `WATCH_PATH` 配置**，但 UI 上有用户价值显示"当前任务都流向哪里"——聚合 `mover_state.json` 里**活跃**任务（`pending` / `copying`）的 `target` 字段：

```js
// 前端聚合
const targetCounts = {};
activeTasks.forEach(t => {
  const dir = path.dirname(t.target);
  targetCounts[dir] = (targetCounts[dir] || 0) + 1;
});
```

显示规则：

- 列出所有不同的 target 目录 + 任务数
- 如果只有一个 target（最常见情况）：单行显示
- 如果多个 target：每个一行
- 如果没有活跃任务：显示"暂无搬运任务"

固定提示文案：「集合点路径在 Downloader 或 Unzipper 页面修改」（链接到 path-config-design.md 的语义）。

### 4. 搬运中区域（折叠）

**默认展开**。复用 setupToggle 折叠机制（localStorage key: `mover_active_collapsed`）。

每条任务卡片：

```
┌─ archive_001.zip ─────────────────────────────┐
│ /old/path/archive_001.zip                     │  ← source
│   ↓                                            │
│ /HydenFileSystem/Archives/archive_001.zip     │  ← target
│ 开始: 14:23:01 (3s 前)  |  状态: 搬运中...     │
└────────────────────────────────────────────────┘
```

字段映射：
- 文件名 = `Path(task.source).name`
- 源 / 目标 = `task.source` / `task.target`
- 开始时间 = 用 `task.created_at`（ISO）格式化为 `HH:MM:SS`，加相对时间标注
- 状态文案：
  - `pending` → 「等待中」（灰色）
  - `copying` → 「搬运中...」（蓝色）

### 5. 历史区域（折叠）

**默认折叠**（与 downloader 已完成区域一致）。localStorage key: `mover_history_collapsed`。

显示 `done` 和 `failed` 任务（按 `completed_at` 倒序）。

#### 表格列

| 列 | 字段 |
|---|---|
| 文件名 | `Path(source).name` |
| 状态 | `done` 绿色 / `failed` 红色 |
| 大小 | `total_size` 字节 → 人类可读（KB/MB/GB） |
| 完成时间 | `completed_at` ISO → `YYYY-MM-DD HH:MM:SS` |
| 错误原因 | `failed` 时显示 `error` 字段（小字色暗）|
| 操作 | `failed` 时显示 [重试] 按钮（调 `POST /api/tasks/{task_id}/retry`） |

#### 标题旁按钮

- [清空历史]（红色警示）→ 调 `POST /api/tasks/clear`（已有 API），二次确认

### 6. 底部连接状态

`<div id="sb">` 显示 WebSocket 连接状态（连接中 / 已连接 / 断开）。复用已有约定。

---

## 数据流

### WebSocket 实时推送

`mover/web/websocket.py` 已有 `_broadcast_loop`（1s 周期推 `_build_state`）。前端 onmessage 中 render。

`_build_state` 当前返回：

```python
return {
    "running_tasks": [...],
    "queue_depth":   ...,
    ...
}
```

新前端需要的字段（部分已有）：

```python
return {
    "running_tasks": [active task dicts],
    "history":       [done/failed task dicts],   # 新增 / 调整
    "stats": {
        "running": ..., "total": ..., "failed": ...
    },
    "paused":        state.paused,                # P1-5a Q4
}
```

如果当前 `_build_state` 字段不完全，需轻微调整（向后兼容现有 dashboard 不要破坏）。

### 初次加载（HTTP）

`GET /api/tasks?limit=100&offset=0`（已有）拉取最新 100 条作为初始 state；之后靠 WebSocket 增量更新。

---

## 实现要点

### 文件改动

| 文件 | 改动 |
|---|---|
| `mover/web/templates.py` | **完整改写**：参考 `unzipper/web/templates.py` 结构，复用 `__API_KEY__` 注入 + apiFetch + setupToggle |
| `mover/web/api.py` | `_index_handler` 改为：`html = MOVER_HTML.replace('__API_KEY__', config.API_KEY)`；返回 HTML（参考 unzipper/web/api.py 的 `_index_handler`）|
| `mover/web/websocket.py` | 如需扩展 `_build_state` 输出 |

### apiFetch 注入

```javascript
const API_KEY = '__API_KEY__';
async function apiFetch(url, opts={}) {
  const headers = Object.assign({'X-API-Key': API_KEY}, opts.headers || {});
  return fetch(url, {...opts, headers});
}
```

所有 `/api/*` 调用走 apiFetch。

### 暂停按钮

复用 P1-5a Q4 中 downloader / unzipper 的相同模式（参考 `pause-design.md`）：

```javascript
let lastPaused = false;
function updatePauseBtn(paused) {
  lastPaused = !!paused;
  const btn = document.getElementById('pause-btn');
  btn.textContent = lastPaused ? '▶ 恢复' : '⏸ 暂停';
  btn.style.cssText = lastPaused
    ? 'background:#4a3010;color:#ff9800;border-color:#ff9800'
    : '';
}
document.getElementById('pause-btn').addEventListener('click', async () => {
  const url = lastPaused ? '/api/resume' : '/api/pause';
  const r = await apiFetch(url, {method: 'POST'});
  if (r.ok) updatePauseBtn((await r.json()).paused);
});
```

### 折叠（搬运中 / 历史）

复用 P1-5a Q3 的 `setupToggle()` helper（待提取到共享 JS 或重复实现）：

```javascript
setupToggle('active-toggle',  'active-arrow',  'active-panel',  'mover_active_collapsed');
setupToggle('history-toggle', 'history-arrow', 'history-panel', 'mover_history_collapsed');
```

---

## 风格参考

- **深色主题色卡**：`#1a1a1a` 背景 / `#222` card / `#e0e0e0` 文字 / `#4caf50` 主色（成功）/ `#ffc107` 警告 / `#f44336` 错误
- **响应式 grid**：`grid-template-columns: repeat(auto-fit, minmax(260px, 1fr))`
- **字体**：与现有模块一致 system-ui stack
- **图标**：emoji（🚚 ⏸ ▶ ⚠ 🔄 ✕）+ 几何符号（▶ ▼ ↓）

---

## 不在本次范围

- **路径配置 UI**（移到 `path-config-design.md` 的范围；mover UI 只读显示集合点路径分布）
- **搬运进度百分比**：v1 仅显示"搬运中..."；进度条留待 v2（mover 实现进度回调，类似 downloader chunker）
- **批量操作**：v1 重试是单条；批量选择多个 failed 重试留 v2
- **手动提交搬运任务**（用户通过 UI 手动调 `/api/move`）：当前 mover 是被调用方，UI 暴露此入口属于反向用例，留待视需求
