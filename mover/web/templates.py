# SPDX-License-Identifier: AGPL-3.0-or-later
"""嵌入式前端模板：mover Web UI（深色主题，参考 unzipper/downloader 风格）。"""

MOVER_HTML: str = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mover</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1a1a1a;color:#e0e0e0;padding:20px 24px 60px}
h1{color:#4caf50;margin-bottom:20px;font-size:1.3rem;font-weight:600;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h2{color:#81c784;font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
   margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #2a2a2a}
section{margin-bottom:28px}
.btn{background:#2e7d32;color:#fff;border:1px solid transparent;border-radius:6px;padding:8px 16px;
     font-size:.85rem;cursor:pointer;transition:background .2s}
.btn:hover{background:#388e3c}
.btn:disabled{opacity:.5;cursor:default}
.btn-sm{padding:4px 10px;font-size:.75rem}
.btn-danger{background:#7f1d1d;color:#fca5a5}
.btn-danger:hover{background:#991b1b}
.btn-warn{background:#4a3010;color:#ff9800;border-color:#ff9800}
.btn-warn:hover{background:#5a3a14}
.card{background:#222;border:1px solid #2a2a2a;border-radius:8px;padding:14px 16px;margin-bottom:10px}
.card-name{font-weight:600;margin-bottom:8px;word-break:break-all;font-size:.95rem}
.card-paths{font-size:.78rem;color:#9e9e9e;margin:6px 0;line-height:1.5;word-break:break-all}
.card-paths .arrow{color:#4caf50;margin:0 6px}
.card-meta{font-size:.75rem;color:#777;display:flex;gap:16px;flex-wrap:wrap;margin-top:6px}
.badge{display:inline-block;font-size:.72rem;font-weight:500;padding:2px 10px;border-radius:12px;
       vertical-align:middle;margin-left:6px}
.badge-pending{background:#2a2a2a;color:#9e9e9e}
.badge-copying{background:#0d2840;color:#42a5f5}
.badge-done{background:#1a3a1a;color:#66bb6a}
.badge-failed{background:#3a1a1a;color:#ef5350}
#bot-status{font-size:.65rem;font-weight:500;padding:3px 10px;border-radius:10px;
            margin-left:6px;vertical-align:middle}
.status-idle{background:#2a2a2a;color:#9e9e9e}
.status-busy{background:#1a3a1a;color:#66bb6a}
.status-paused{background:#4a3010;color:#ff9800}
#pause-btn{margin-left:auto;font-weight:normal;font-size:.75rem}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.stat-card{background:#222;border:1px solid #2a2a2a;border-radius:8px;padding:14px 16px}
.stat-label{font-size:.7rem;color:#777;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.stat-value{font-size:1.5rem;font-weight:600;color:#e0e0e0}
.stat-value.warn{color:#ffc107}
.stat-value.busy{color:#4caf50}
.target-card{background:#222;border:1px solid #2a2a2a;border-radius:8px;padding:14px 16px}
.target-row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid #2a2a2a;font-size:.85rem}
.target-row:last-child{border-bottom:none}
.target-path{color:#e0e0e0;font-family:'Consolas',monospace;word-break:break-all}
.target-count{color:#81c784;font-size:.78rem;flex-shrink:0;margin-left:12px}
.target-hint{font-size:.72rem;color:#666;margin-top:10px;padding-top:10px;border-top:1px solid #2a2a2a}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;color:#777;font-weight:500;padding:6px 10px;border-bottom:1px solid #2a2a2a;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #1f1f1f;vertical-align:middle}
tr:last-child td{border-bottom:none}
.td-name{max-width:280px;word-break:break-all}
.td-muted{color:#777;font-size:.75rem;white-space:nowrap}
.td-error{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
          color:#ef9a9a;font-size:.75rem;cursor:default}
tr.row-failed td{color:#ef5350;background:rgba(239,83,80,.05)}
.empty{color:#555;font-style:italic;font-size:.82rem;padding:10px 4px}
.section-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #2a2a2a;gap:10px;flex-wrap:wrap}
.section-title{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;
               color:#81c784;font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;flex:1}
.section-title .arrow{display:inline-block;transition:transform .2s;font-size:.7rem;color:#666}
#sb{position:fixed;bottom:0;left:0;right:0;background:#0e0e0e;padding:5px 20px;
    font-size:.72rem;color:#555;border-top:1px solid #1a1a1a;display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.on{background:#66bb6a}.dot.off{background:#ef5350}
@media (max-width:480px){
  body{padding:14px 12px 60px}
  h1{font-size:1.1rem}
  #pause-btn{margin-left:0;margin-top:4px}
  .td-name{max-width:160px}
}
.scroll-top-btn{position:fixed;bottom:24px;right:24px;z-index:999;
  width:44px;height:44px;border-radius:50%;
  background:#1f1f1f;color:#888;border:1px solid #333;
  font-size:1.4rem;cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:color .2s,border-color .2s,background .2s;padding:0;line-height:1}
.scroll-top-btn:hover{color:#4fc3f7;border-color:#4fc3f7;background:#262626}
</style>
</head>
<body>
<h1>🚚 Mover <span id="bot-status" class="status-idle">● 待机</span>
  <button id="pause-btn" class="btn btn-sm" title="暂停后新提交的搬运任务排队不执行">⏸ 暂停</button>
</h1>

<section>
  <h2>统计</h2>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-label">搬运中</div><div class="stat-value" id="stat-running">0</div></div>
    <div class="stat-card"><div class="stat-label">历史总数</div><div class="stat-value" id="stat-total">0</div></div>
    <div class="stat-card"><div class="stat-label">失败</div><div class="stat-value" id="stat-failed">0</div></div>
  </div>
</section>

<section>
  <h2>集合点路径（只读）</h2>
  <div class="target-card">
    <div id="target-list"><div class="empty">暂无搬运任务</div></div>
    <div class="target-hint">ℹ 集合点路径在 Downloader 或 Unzipper 页面修改</div>
  </div>
</section>

<section>
  <div class="section-header">
    <div class="section-title" id="active-toggle">
      <span class="arrow" id="active-arrow">▶</span>
      <span>搬运中（<span id="active-count">0</span>）</span>
    </div>
  </div>
  <div id="active-panel"><div id="active-wrap"><div class="empty">暂无搬运任务</div></div></div>
</section>

<section>
  <div class="section-header">
    <div class="section-title" id="history-toggle">
      <span class="arrow" id="history-arrow">▶</span>
      <span>历史（<span id="history-count">0</span>）</span>
    </div>
    <button class="btn btn-sm btn-danger" id="clear-history-btn">清空历史</button>
  </div>
  <div id="history-panel">
    <table>
      <thead><tr>
        <th>文件名</th><th>状态</th><th>大小</th><th>完成时间</th><th>错误原因</th><th>操作</th>
      </tr></thead>
      <tbody id="history-body">
        <tr><td colspan="6" class="empty">暂无记录</td></tr>
      </tbody>
    </table>
  </div>
</section>

<div id="sb"><span class="dot off" id="dot"></span><span id="sb-text">连接中...</span></div>

<script>
const API_KEY = '__API_KEY__';
async function apiFetch(url, opts={}) {
  const headers = Object.assign({'X-API-Key': API_KEY}, opts.headers || {});
  return fetch(url, {...opts, headers});
}

let ws, reconnTimer;
let lastPaused = false;

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function basename(p) {
  if (!p) return '';
  const s = String(p);
  const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\\\'));
  return i >= 0 ? s.slice(i + 1) : s;
}

function dirname(p) {
  if (!p) return '';
  const s = String(p);
  const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\\\'));
  return i > 0 ? s.slice(0, i) : (i === 0 ? '/' : '');
}

function fmtBytes(n) {
  if (n == null || n < 0) return '—';
  if (n < 1024) return n + ' B';
  const units = ['KB','MB','GB','TB'];
  let i = -1, v = n;
  do { v /= 1024; i++; } while (v >= 1024 && i < units.length - 1);
  return v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2) + ' ' + units[i];
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  } catch (e) { return iso; }
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  } catch (e) { return iso; }
}

function fmtRelative(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const diff = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diff < 60) return diff + 's 前';
  if (diff < 3600) return Math.floor(diff / 60) + 'm 前';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h 前';
  return Math.floor(diff / 86400) + 'd 前';
}

function statusBadge(status) {
  const cls   = {pending:'badge-pending',copying:'badge-copying',done:'badge-done',failed:'badge-failed'}[status] || 'badge-pending';
  const label = {pending:'等待中',copying:'搬运中',done:'完成',failed:'失败'}[status] || status;
  return '<span class="badge ' + cls + '">' + label + '</span>';
}

// ── 暂停按钮 (P1-5a Q4) ─────────────────────────────────────────────────────
function updatePauseBtn(paused) {
  lastPaused = !!paused;
  const btn = document.getElementById('pause-btn');
  if (lastPaused) {
    btn.textContent = '▶ 恢复';
    btn.className = 'btn btn-sm btn-warn';
  } else {
    btn.textContent = '⏸ 暂停';
    btn.className = 'btn btn-sm';
  }
}

document.getElementById('pause-btn').addEventListener('click', async () => {
  const url = lastPaused ? '/api/resume' : '/api/pause';
  const btn = document.getElementById('pause-btn');
  btn.disabled = true;
  try {
    const r = await apiFetch(url, {method: 'POST'});
    if (r.ok) {
      const j = await r.json();
      updatePauseBtn(j.paused);
    }
  } catch (e) {
    alert('请求失败：' + e.message);
  } finally {
    btn.disabled = false;
  }
});

// ── setupToggle 折叠（参考 downloader/web/templates.py）────────────────────
function setupToggle(toggleId, arrowId, panelId, storageKey) {
  const tgl   = document.getElementById(toggleId);
  const arrow = document.getElementById(arrowId);
  const panel = document.getElementById(panelId);
  const collapsed = localStorage.getItem(storageKey) === '1';
  panel.style.display   = collapsed ? 'none' : 'block';
  arrow.style.transform = collapsed ? '' : 'rotate(90deg)';
  tgl.addEventListener('click', () => {
    const willShow = panel.style.display === 'none';
    panel.style.display   = willShow ? 'block' : 'none';
    arrow.style.transform = willShow ? 'rotate(90deg)' : '';
    localStorage.setItem(storageKey, willShow ? '0' : '1');
  });
}

// 默认：搬运中展开（key 不存在 → collapsed=false）；历史折叠（首次访问写入 '1'）
if (localStorage.getItem('mover_history_collapsed') === null) {
  localStorage.setItem('mover_history_collapsed', '1');
}
setupToggle('active-toggle',  'active-arrow',  'active-panel',  'mover_active_collapsed');
setupToggle('history-toggle', 'history-arrow', 'history-panel', 'mover_history_collapsed');

// 阻止历史区按钮触发折叠
document.getElementById('clear-history-btn').addEventListener('click', (e) => e.stopPropagation());

// ── 渲染 ───────────────────────────────────────────────────────────────────
function render(data) {
  const tasks = data.tasks || {};
  const taskList = Object.values(tasks);

  // P1-9 polish：从 WebSocket data 读 paused（_build_state 已加 paused 字段）
  if (typeof data.paused === 'boolean') {
    updatePauseBtn(data.paused);
  }

  const active  = taskList.filter(t => t.status === 'copying' || t.status === 'pending');
  const history = taskList.filter(t => t.status === 'done' || t.status === 'failed');
  const failedCount = history.filter(t => t.status === 'failed').length;
  const runningCount = (typeof data.running === 'number') ? data.running
                       : taskList.filter(t => t.status === 'copying').length;

  // Top status badge
  const statusEl = document.getElementById('bot-status');
  if (lastPaused) {
    statusEl.textContent = '● 已暂停';
    statusEl.className = 'status-paused';
  } else if (runningCount > 0) {
    statusEl.textContent = '● 搬运中';
    statusEl.className = 'status-busy';
  } else {
    statusEl.textContent = '● 待机';
    statusEl.className = 'status-idle';
  }

  // Stats
  const sr = document.getElementById('stat-running');
  sr.textContent = runningCount;
  sr.className = 'stat-value' + (runningCount > 0 ? ' busy' : '');

  document.getElementById('stat-total').textContent = taskList.length;

  const sf = document.getElementById('stat-failed');
  sf.textContent = failedCount + (failedCount > 0 ? ' ⚠' : '');
  sf.className = 'stat-value' + (failedCount > 0 ? ' warn' : '');

  // Section counts
  document.getElementById('active-count').textContent = active.length;
  document.getElementById('history-count').textContent = history.length;

  // Target paths aggregation (active tasks only)
  const targetCounts = {};
  active.forEach(t => {
    const dir = dirname(t.target);
    if (dir) targetCounts[dir] = (targetCounts[dir] || 0) + 1;
  });
  const tl = document.getElementById('target-list');
  const targetEntries = Object.entries(targetCounts);
  if (targetEntries.length === 0) {
    tl.innerHTML = '<div class="empty">暂无搬运任务</div>';
  } else {
    tl.innerHTML = targetEntries.map(([dir, cnt]) =>
      '<div class="target-row">'
      + '<span class="target-path">' + esc(dir) + '</span>'
      + '<span style="display:flex;align-items:center;gap:10px">'
      + '<span class="target-count">← ' + cnt + ' 个进行中任务</span>'
      + '<button class="btn btn-sm target-open" data-path="' + esc(dir) + '" title="在文件管理器中打开">📂 打开</button>'
      + '</span>'
      + '</div>'
    ).join('');
  }

  // Active tasks
  const aw = document.getElementById('active-wrap');
  if (active.length === 0) {
    aw.innerHTML = '<div class="empty">暂无搬运任务</div>';
  } else {
    // Sort: copying first, then pending; within group by created_at asc
    active.sort((a, b) => {
      if (a.status !== b.status) return a.status === 'copying' ? -1 : 1;
      return String(a.created_at).localeCompare(String(b.created_at));
    });
    aw.innerHTML = active.map(t => {
      const name = basename(t.source);
      const startTime = t.created_at ? fmtTime(t.created_at) : '—';
      const rel = t.created_at ? ' (' + fmtRelative(t.created_at) + ')' : '';
      return '<div class="card">'
        + '<div class="card-name">' + esc(name) + statusBadge(t.status) + '</div>'
        + '<div class="card-paths">'
        + '<div>' + esc(t.source) + '</div>'
        + '<div><span class="arrow">↓</span></div>'
        + '<div>' + esc(t.target) + '</div>'
        + '</div>'
        + '<div class="card-meta">'
        + '<span>开始: ' + startTime + rel + '</span>'
        + '</div>'
        + '</div>';
    }).join('');
  }

  // History (newest first by completed_at)
  const hb = document.getElementById('history-body');
  if (history.length === 0) {
    hb.innerHTML = '<tr><td colspan="6" class="empty">暂无记录</td></tr>';
  } else {
    history.sort((a, b) => {
      const ka = a.completed_at || a.failed_at || a.created_at || '';
      const kb = b.completed_at || b.failed_at || b.created_at || '';
      return String(kb).localeCompare(String(ka));
    });
    hb.innerHTML = history.map(t => {
      const name = basename(t.source);
      const isFailed = t.status === 'failed';
      const rowCls = isFailed ? ' class="row-failed"' : '';
      const completedTime = t.completed_at || t.failed_at;
      const errText = t.error || '';
      const tid = t.task_id || '';
      let opCell = '';
      if (isFailed && tid) {
        opCell = '<button class="btn btn-sm retry-btn" data-tid="' + esc(tid) + '">🔄 重试</button>';
      }
      return '<tr' + rowCls + '>'
        + '<td class="td-name" title="' + esc(t.source) + '">' + esc(name) + '</td>'
        + '<td>' + statusBadge(t.status) + '</td>'
        + '<td class="td-muted">' + fmtBytes(t.total_size) + '</td>'
        + '<td class="td-muted">' + fmtDateTime(completedTime) + '</td>'
        + '<td class="td-error" title="' + esc(errText) + '">' + (errText ? esc(errText) : '—') + '</td>'
        + '<td>' + opCell + '</td>'
        + '</tr>';
    }).join('');
  }
}

// ── WebSocket ──────────────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws' + (API_KEY ? ('?key=' + encodeURIComponent(API_KEY)) : ''));
  ws.onopen = () => {
    document.getElementById('dot').className = 'dot on';
    document.getElementById('sb-text').textContent = '已连接';
    clearTimeout(reconnTimer);
  };
  ws.onclose = () => {
    document.getElementById('dot').className = 'dot off';
    document.getElementById('sb-text').textContent = '已断开，3s 后重连…';
    reconnTimer = setTimeout(connect, 3000);
  };
  ws.onmessage = e => {
    try { render(JSON.parse(e.data)); }
    catch (err) { console.error('render error', err); }
  };
}

// 历史按钮（事件委托：处理 retry 按钮）
document.addEventListener('click', async (e) => {
  const retryBtn = e.target.closest('.retry-btn');
  if (retryBtn) {
    const tid = retryBtn.dataset.tid;
    if (!tid) return;
    retryBtn.disabled = true;
    try {
      const r = await apiFetch('/api/tasks/' + encodeURIComponent(tid) + '/retry', {method: 'POST'});
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        alert('重试失败：' + (j.error || ('HTTP ' + r.status)));
      }
    } catch (err) {
      alert('请求失败：' + err.message);
    } finally {
      retryBtn.disabled = false;
    }
  }
});

document.getElementById('clear-history-btn').addEventListener('click', async function() {
  if (!confirm('清空所有历史记录？（不删除本地文件）')) return;
  this.disabled = true;
  try {
    const r = await apiFetch('/api/tasks/clear', {method: 'POST'});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) {
      alert('清空失败：' + (j.error || ('HTTP ' + r.status)));
    }
  } catch (e) {
    alert('请求失败：' + e.message);
  } finally {
    this.disabled = false;
  }
});

// 打开集合点目录（事件代理：target-list 行内按钮）
document.getElementById('target-list').addEventListener('click', async (e) => {
  const btn = e.target.closest('.target-open');
  if (!btn) return;
  const path = btn.dataset.path;
  if (!path) return;
  btn.disabled = true;
  try {
    const r = await apiFetch('/api/open', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path})
    });
    const j = await r.json();
    if (!j.ok) alert('打开失败：' + (j.error || r.status));
  } catch (err) {
    alert('请求失败：' + err.message);
  } finally {
    btn.disabled = false;
  }
});

// 启动
connect();
</script>
<button class="scroll-top-btn" title="回到顶部" onclick="window.scrollTo({top:0,behavior:'smooth'})">↑</button>
</body>
</html>"""
