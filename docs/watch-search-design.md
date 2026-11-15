# 监听列表搜索设计

> **状态**：✅ 已实现。本文档定义监听列表搜索框的 UI 行为和交互。

## 背景

P1-7 上线后监听列表已超 50 个频道，无搜索功能时只能滚动找目标频道。

## 关键设计决策

### 决策 1：纯前端 filter，不新增后端 API

`/api/status` WebSocket 推送时已经把完整 `watched` 字典发给前端，前端 `lastWatched` 持有所有数据。58 个频道做 `name.includes(q)` 是 JavaScript 微秒级操作。

**理由**：

- 监听数 < 1000 时新建 API 端点无任何收益
- 输入框 `input` 事件实时触发，无 HTTP 往返延迟
- 与 WebSocket 已推送的数据零重复
- 后端零改动

**触发新增 API 的条件**（未来）：监听数 > 5000 时再考虑（届时可加 `GET /api/watch?q=`）。

## 功能规格

### UI 位置

监听列表折叠区（`#wl-panel`）内、排序控件同一行右侧：

```
┌─ 监听列表 ▼  [⏸ 暂停监听]  ─────────────────────────────────┐
│ 排序：[频道名 ↓] [监听时间 ↓] [任务数 ↓] [默认 ↓] [重置全部] │
│       [🔍 搜索: ___________________ ✕ ]                       │
├──────────────────────────────────────────────────────────────┤
│ ... entries ...                                                 │
└──────────────────────────────────────────────────────────────┘
```

不放标题栏，避免与折叠交互冲突；与排序控件同一区域便于"先排再搜"组合操作。

### 输入框

- **id**：`wl-search`
- **placeholder**：`搜索频道名 / ID...`
- **触发**：`input` 事件即时过滤（无防抖——前端纯 JS，微秒级）
- **清空按钮**：输入框右侧固定一个 `✕`（id `wl-search-clear`），点击清空 + 重渲染 + focus 回输入框

### 匹配逻辑

```javascript
function matchesSearch(cid, info, query) {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  return info.name.toLowerCase().includes(q) || cid.includes(q);
}
```

- 大小写不敏感（仅对 name；cid 是数字字符串，大小写无关）
- 部分匹配（contains，不是 startsWith）
- 同时匹配 `name` 和 `cid`
- 空 / 纯空格搜索词 = 显示全部

### 与排序的交互

- 搜索结果按**当前排序维度**排列（`wlSortBy` / `wlSortOrder` 不变）
- 切换排序时**保留**当前搜索词
- 折叠/展开监听列表区域不影响搜索词（**搜索词不持久化到 localStorage**）

### 空结果

| 状态 | 显示 |
|------|------|
| 无搜索词 + 监听列表空 | `监听列表为空`（现有文案，`#wl` 容器）|
| 有搜索词 + 0 命中 | `没有找到匹配「{keyword}」的频道` |
| 有搜索词 + N 命中 | 渲染 N 行；列表区顶部加灰色小字 `匹配 N / 共 {总数}` |

**计数显示位置**：当前 `#wl-toggle` 标题没有计数 span。新方案不改标题——在 `#wl` 容器最上方插一个 `<div id="wl-search-info">`，仅有搜索词时显示，无搜索词时隐藏（`display:none`）。理由：避免动标题区，最小侵入。

### 搜索词不持久化

`wl-search` 输入框值**不**写 `localStorage`。重启 / 刷新页面后清空。理由：搜索是临时操作；持久化反而让用户困惑"为什么打开页面只看到几条"。

## 实现要点

### 状态变量（`templates.py` 顶部 let 块）

```javascript
let wlSearchQuery = '';   // 当前搜索词（不持久化）
```

### `renderWatched` 改造

现有 `renderWatched(watched)` 把渲染输出到 `#wl` 容器。新签名（保持入口签名兼容）：

```javascript
function renderWatched(watched) {
  const all = watched || {};
  const wl = document.getElementById('wl');

  // 应用搜索过滤
  const filtered = wlSearchQuery
    ? Object.fromEntries(
        Object.entries(all).filter(([cid, info]) =>
          matchesSearch(cid, info, wlSearchQuery)
        )
      )
    : all;

  const totalCount  = Object.keys(all).length;
  const filterCount = Object.keys(filtered).length;

  // 搜索信息条（仅搜索词非空时显示）
  const info = document.getElementById('wl-search-info');
  if (wlSearchQuery) {
    info.style.display = '';
    info.textContent = `匹配 ${filterCount} / 共 ${totalCount}`;
  } else {
    info.style.display = 'none';
  }

  // 空结果（区分有/无搜索词）
  if (totalCount === 0) {
    wl.innerHTML = '<p class="empty">监听列表为空</p>';
    return;
  }
  if (wlSearchQuery && filterCount === 0) {
    wl.innerHTML = `<p class="empty">没有找到匹配「${esc(wlSearchQuery)}」的频道</p>`;
    return;
  }

  // 现有排序 + 渲染逻辑（基于 `filtered` 而非 `all`）
  ...
}
```

注意：`esc()` 是 templates.py 里已有的 HTML 转义函数（防 XSS）；不要新写一个。

### 事件绑定

```javascript
document.getElementById('wl-search').addEventListener('input', (e) => {
  wlSearchQuery = e.target.value;
  renderWatched(lastWatched);
});

document.getElementById('wl-search-clear').addEventListener('click', () => {
  wlSearchQuery = '';
  document.getElementById('wl-search').value = '';
  document.getElementById('wl-search').focus();
  renderWatched(lastWatched);
});
```

### WebSocket 推送时保留搜索词

`render(d)` 中现有 `lastWatched = d.watched; renderWatched(lastWatched);` 流程**不变**——`renderWatched` 内部读 `wlSearchQuery` 自动应用过滤。

## 不在本次范围

- 后端 `/api/watch/search` 端点（按上方决策 1 不做）
- 高亮匹配片段（`<mark>` 标签）——v1 不做，简化实现
- 多关键词支持（如 `news +tech`）——v1 不做
- 模糊匹配（拼音 / 编辑距离）——v1 不做
