# 下载队列分页设计

> **状态**：✅ 已实现

## 背景

`active_downloads` 是任务级 dict，可同时容纳几百个 `status=waiting` 任务（无任务数上限，仅靠连接预算 `_acquire_connections` 限流，详见 `调研报告 §1.3`）。

当前 `downloader/web/templates.py:782 renderActiveList` 把 active 数组全量 `map(renderCard)`，N 大时 DOM 规模 = N 张卡片，明显卡顿。

## 改造目标

- 「下载中」与「排队中」两个独立列表，各自渲染、各自标题
- 「排队中」加分页（每页 20 条）
- 「下载中」**不分页**（实际并发数受连接预算限制，最多 ~20 个）
- 不改后端，纯前端拆分 + 分页

## 状态归类

| status | 归类 | 备注 |
|--------|------|------|
| `downloading` | 下载中 | 实际下载流量 |
| `flood_wait`  | 下载中 | 限速等待，但持有连接 |
| `paused`      | 下载中 | 用户软暂停 |
| `cancelling`  | 下载中 | 已发取消信号、未到 `_finish` |
| `waiting`     | 排队中 | 在等连接预算 |
| `done` / `error` / `timeout` | 已完成 | 不在 active 列表（已转 completed） |

`tasks.filter(t => t.status === 'waiting')` 即排队中；其余即下载中。

## UI 改造

`downloader/web/templates.py`：

```html
<!-- 原: <h2 id="dl-toggle">下载中 ... <span id="ac"></span></h2><div id="al">...</div> -->

<!-- 改后 -->
<h2 id="dl-toggle">下载中
  <span id="dl-arrow">▶</span>
  <span id="ac"></span>
  <span id="spd"></span>
</h2>
<div id="dl-section">
  <div id="al"><p class="empty">暂无下载任务</p></div>
</div>

<h2 id="queue-toggle" style="cursor:pointer">排队中
  <span id="queue-arrow">▶</span>
  <span id="queue-count" class="muted"></span>
</h2>
<div id="queue-section">
  <div id="queue-list"><p class="empty">暂无排队任务</p></div>
  <div id="queue-pager" style="display:none">
    <button id="queue-prev">上一页</button>
    <span id="queue-page-info">第 1 / 1 页</span>
    <button id="queue-next">下一页</button>
  </div>
</div>
```

两个区域都复用现有 `setupToggle` 折叠机制。

## 卡片简化

「排队中」复用 `renderCard()` 即可（waiting 的字段集合与 downloading 相同，详见 §1.2 调研）。但因排队卡多、信息冗余，可选**简化版渲染** `renderQueueCard(t)`：

- 单行布局：`📄 {filename}  ·  {label}  ·  {size_mb}MB  ·  入队 {queued_at}  [终止]`
- 不显示进度条、不显示分块详情、不显示 chunks 详情按钮
- 只保留「终止」按钮

如要改用简化版，需补充小型 CSS。**默认按 spec 走完整 renderCard，简化版列入未做项**。

## 分页逻辑

```js
const QUEUE_PAGE_SIZE = 20;
let queueCurrentPage = 1;

function renderQueueList(active) {
  const queued = active.filter(t => t.status === 'waiting');
  const total = queued.length;
  const totalPages = Math.max(1, Math.ceil(total / QUEUE_PAGE_SIZE));

  // 当前页超出 → 回最后一页（任务被消费、用户停在已不存在的页）
  if (queueCurrentPage > totalPages) queueCurrentPage = totalPages;
  if (queueCurrentPage < 1) queueCurrentPage = 1;

  document.getElementById('queue-count').textContent = total ? ` (共 ${total} 个)` : '';

  const start = (queueCurrentPage - 1) * QUEUE_PAGE_SIZE;
  const slice = queued.slice(start, start + QUEUE_PAGE_SIZE);
  const list = document.getElementById('queue-list');
  list.innerHTML = slice.length
    ? slice.map(renderCard).join('')
    : '<p class="empty">暂无排队任务</p>';

  const pager = document.getElementById('queue-pager');
  pager.style.display = total > QUEUE_PAGE_SIZE ? 'flex' : 'none';
  document.getElementById('queue-page-info').textContent =
    `第 ${queueCurrentPage} / ${totalPages} 页`;
  document.getElementById('queue-prev').disabled = queueCurrentPage <= 1;
  document.getElementById('queue-next').disabled = queueCurrentPage >= totalPages;
}

document.getElementById('queue-prev').onclick = () => {
  queueCurrentPage--; renderQueueList(lastActive);
};
document.getElementById('queue-next').onclick = () => {
  queueCurrentPage++; renderQueueList(lastActive);
};
```

`renderActiveList(active)` 拆成两步：

```js
function renderActiveList(active) {
  lastActive = active;
  const dling = active.filter(t => t.status !== 'waiting');
  document.getElementById('al').innerHTML = dling.length
    ? dling.map(renderCard).join('')
    : '<p class="empty">暂无下载任务</p>';
  renderQueueList(active);
}
```

## 顶部统计行调整

现有 `templates.py:818-826` 已经分别算 `dlCount` / `wCount`，沿用：

```js
const dlCount = active.filter(t => t.status !== 'waiting').length;
const wCount  = d.waiting_count || 0;
// dlCount 显示在「下载中」标题旁的 #ac
// wCount 显示在「排队中」标题旁的 #queue-count
```

将 `#ac` 文案改为 `${dlCount} 个文件，${conns}/${maxC} 连接`，**不再混排 wCount**。

## 排序

排队中列表按 `state.active_downloads` 的 dict 插入顺序（FIFO）展示，不提供前端排序。`Object.values()` 在 Python 3.7+ 保序，前端 `Array.prototype.filter` 也保序，符合预期。

## 无 WS 字段改动

后端 WS payload 已包含完整 active 列表（`websocket.py:13`），分页纯前端实现，无需后端改动。

## 边界 case

| 场景 | 行为 |
|------|------|
| 排队中为空 | `<p class="empty">` 占位，分页器隐藏 |
| 当前在第 5 页，任务被消费完只剩 60 个（3 页） | `queueCurrentPage = 3`，渲染最后一页 |
| 用户切到第 3 页时 WS 推送来了 | 保持 `queueCurrentPage = 3`，仅当超出范围才回退 |
| 页面刷新 | 不持久化，回到第 1 页 |
| 几百个 waiting 任务 | DOM 永远只渲染 ≤20 张卡，不会卡顿 |

## 验收

- 注入大量假任务（或真实场景下监听繁忙频道）→ 排队中数量超过 20 时分页器显示
- 上一页/下一页按钮正确响应、首尾页禁用
- 任务从 waiting 转 downloading → 自动从排队列表移除并出现在下载中
- 终止按钮在排队卡上有效（`/api/task/{id}/cancel` 已支持 waiting 状态）
