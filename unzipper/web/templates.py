# SPDX-License-Identifier: AGPL-3.0-or-later
UNZIPPER_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unzipper</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d0d0d;color:#e0e0e0;padding:20px 24px 60px}
h1{color:#4fc3f7;margin-bottom:24px;font-size:1.3rem;font-weight:600}
h2{color:#81d4fa;font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
   margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e1e1e}
section{margin-bottom:32px}
.btn{background:#1565c0;color:#fff;border:none;border-radius:6px;padding:8px 16px;
     font-size:.85rem;cursor:pointer;transition:background .2s}
.btn:hover{background:#1976d2}
.btn:disabled{opacity:.5;cursor:default}
.btn-sm{padding:4px 10px;font-size:.75rem}
.btn-danger{background:#7f1d1d;color:#fca5a5}
.btn-danger:hover{background:#991b1b}
.card{background:#161616;border:1px solid #1e1e1e;border-radius:8px;padding:14px 16px;margin-bottom:10px}
.card-name{font-weight:600;margin-bottom:8px;word-break:break-all;font-size:.95rem}
.card-meta{font-size:.75rem;color:#777;display:flex;gap:16px;flex-wrap:wrap}
.badge{display:inline-block;font-size:.72rem;font-weight:500;padding:2px 10px;border-radius:12px;
       vertical-align:middle;margin-left:6px}
.badge-extracting{background:#1a3a1a;color:#66bb6a}
.badge-failed{background:#3a1a1a;color:#ef5350}
.badge-done{background:#1a2a3a;color:#4fc3f7}
.badge-partial{background:#2a1a3a;color:#ce93d8}
.badge-waiting{background:#2a2a1a;color:#ffd54f}
.badge-cancelled{background:#2a2a2a;color:#aaa}
tr.row-cancelled td{color:#aaa;background:rgba(120,120,120,.06)}
.pending-row{display:flex;align-items:center;justify-content:space-between;gap:12px;
             padding:10px 14px;background:#161616;border:1px solid #1e1e1e;border-radius:8px;margin-bottom:8px}
.pending-name{font-weight:500;word-break:break-all;font-size:.9rem}
.pending-id{font-size:.72rem;color:#555;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;color:#555;font-weight:500;padding:6px 10px;border-bottom:1px solid #1e1e1e;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #161616;vertical-align:middle}
tr:last-child td{border-bottom:none}
.td-name{max-width:260px;word-break:break-all}
.td-muted{color:#666;font-size:.75rem;white-space:nowrap}
.empty{color:#444;font-style:italic;font-size:.82rem;padding:6px 0}
#sb{position:fixed;bottom:0;left:0;right:0;background:#0a0a0a;padding:5px 20px;
    font-size:.72rem;color:#444;border-top:1px solid #1a1a1a;display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.on{background:#66bb6a}.dot.off{background:#ef5350}
.error-banner{background:#2a1010;border:1px solid #5a2020;border-radius:8px;
              padding:10px 14px;margin-bottom:20px;color:#ef9a9a;font-size:.85rem}
.partial-banner{background:#1a1a2a;border:1px solid #3a2060;border-radius:8px;
                padding:10px 14px;margin-bottom:20px;color:#ce93d8;font-size:.85rem}
tr.row-failed td{color:#ef5350;background:rgba(239,83,80,.06)}
tr.row-partial td{color:#ce93d8;background:rgba(206,147,216,.04)}
.td-error{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
          color:#ef9a9a;font-size:.75rem;cursor:default}
.toggle-btn{background:none;border:1px solid #333;border-radius:4px;color:#888;
            font-size:.72rem;cursor:pointer;padding:2px 8px;transition:color .15s}
.toggle-btn:hover{color:#ccc}
.detail-row{display:none}
.detail-row.open{display:table-row}
.detail-cell{padding:0 10px 12px 24px !important;border-bottom:1px solid #1e1e1e !important}
.detail-table{width:100%;border-collapse:collapse;font-size:.78rem;margin-top:4px}
.detail-table th{color:#444;padding:4px 8px;border-bottom:1px solid #1a1a1a;font-weight:500}
.detail-table td{padding:4px 8px;border-bottom:1px solid #111;color:#aaa}
.detail-table tr:last-child td{border-bottom:none}
.residual-warn{margin-top:8px;font-size:.75rem;color:#ffd54f;background:#1a1800;
               border:1px solid #3a3000;border-radius:4px;padding:4px 10px}
#bot-status{font-size:.65rem;font-weight:500;padding:3px 10px;border-radius:10px;
            margin-left:10px;vertical-align:middle}
.status-idle{background:#1a2a3a;color:#4fc3f7}
.status-busy{background:#1a3a1a;color:#66bb6a}
/* P1-pwd: 密码管理 */
.pwd-row{display:flex;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid #1e1e1e;background:#161616}
.pwd-row:last-child{border-bottom:none}
.pwd-row[draggable="true"]{cursor:default}
.pwd-handle{cursor:grab;color:#666;user-select:none;font-size:1rem}
.pwd-handle:active{cursor:grabbing}
.pwd-text{flex:1;font-family:'Consolas',monospace;color:#e0e0e0;letter-spacing:.05em;word-break:break-all;min-width:0}
/* P2-2 解压进度条 */
.extract-progress{display:flex;align-items:center;gap:8px;margin-top:6px}
.extract-progress-bar{flex:1;height:6px;background:#222;border-radius:3px;overflow:hidden}
.extract-progress-fill{height:100%;background:linear-gradient(90deg,#1976d2,#4fc3f7);transition:width .25s ease-out}
.extract-progress-pct{color:#4fc3f7;font-size:.72rem;font-variant-numeric:tabular-nums;min-width:36px;text-align:right}
.extract-progress-unknown{color:#888;font-size:.72rem;margin-top:6px;font-style:italic}
.scroll-top-btn{position:fixed;bottom:24px;right:24px;z-index:999;
  width:44px;height:44px;border-radius:50%;
  background:#1f1f1f;color:#888;border:1px solid #333;
  font-size:1.4rem;cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:color .2s,border-color .2s,background .2s;padding:0;line-height:1}
.scroll-top-btn:hover{color:#4fc3f7;border-color:#4fc3f7;background:#262626}
</style>
</head>
<body>
<h1>📦 Unzipper <span id="bot-status" class="status-idle">待机中</span><button id="pause-btn" class="btn btn-sm" style="float:right;font-weight:normal;font-size:.75rem;margin-top:6px" title="暂停后 watcher 不再入队；当前解压和已排队的任务不受影响">⏸ 暂停</button></h1>
<div id="error-banner"   class="error-banner"   style="display:none"></div>
<div id="partial-banner" class="partial-banner" style="display:none"></div>

<section>
  <h2 id="st-toggle" style="cursor:pointer;user-select:none">设置 <span id="st-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span></h2>
  <div id="st-panel" style="display:none">
    <div style="font-size:.85rem;color:#bbb;margin-bottom:10px">输出路径管理</div>

    <div style="margin-bottom:14px">
      <div style="font-size:.78rem;color:#888;margin-bottom:4px">监听路径 (WATCH_PATH，watchdog 监听此目录新增的压缩包)</div>
      <div id="wp-current" style="font-family:monospace;font-size:.78rem;color:#5db" data-default=""></div>
      <div style="display:flex;gap:6px;margin-top:6px;align-items:center;flex-wrap:wrap">
        <input id="wp-input" type="text" style="flex:1;min-width:280px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem" placeholder="/绝对路径">
        <select id="wp-history" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:3px 6px;font-size:.78rem;max-width:240px"></select>
        <label style="display:flex;align-items:center;gap:4px;font-size:.76rem;color:#aaa">
          <input id="wp-sync" type="checkbox" checked> 同步到 Downloader
        </label>
        <button class="btn btn-sm" id="wp-save">应用</button>
        <button class="btn btn-sm" id="wp-open" title="在文件管理器中打开监听目录">📂 打开</button>
      </div>
    </div>

    <div style="margin-bottom:8px">
      <div style="font-size:.78rem;color:#888;margin-bottom:4px">输出路径 (OUTPUT_PATH，解压结果输出目录)</div>
      <div id="op-current" style="font-family:monospace;font-size:.78rem;color:#5db" data-default=""></div>
      <div style="display:flex;gap:6px;margin-top:6px;align-items:center;flex-wrap:wrap">
        <input id="op-input" type="text" style="flex:1;min-width:280px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem" placeholder="/绝对路径">
        <select id="op-history" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:3px 6px;font-size:.78rem;max-width:240px"></select>
        <button class="btn btn-sm" id="op-save">应用</button>
        <button class="btn btn-sm" id="op-open" title="在文件管理器中打开输出目录">📂 打开</button>
      </div>
    </div>

    <div id="path-warn" style="color:#ffd54f;font-size:.78rem;min-height:18px;margin-top:6px"></div>
    <div style="color:#444;font-size:.72rem">改路径只影响新任务；监听路径修改需重启 unzipper 后生效（watchdog 不支持热切换）。下拉框第一项是系统默认路径。</div>
  </div>
</section>

<section>
  <h2 id="pwd-toggle" style="cursor:pointer;user-select:none">
    密码管理
    <span id="pwd-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span>
    <span id="pwd-count" style="color:#888;font-size:.78rem;margin-left:8px;font-weight:normal">0</span>
    <span style="color:#666;font-size:.7rem;margin-left:8px;font-weight:normal">顺序 = 解压尝试顺序</span>
  </h2>
  <div id="pwd-panel" style="display:none">
    <div id="pwd-list"><p class="empty">暂无解压密码，点击下方添加</p></div>
    <div style="display:flex;gap:6px;margin-top:10px;align-items:center">
      <input id="pwd-input" type="password" placeholder="输入新密码..." style="flex:1;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 8px;font-size:.85rem">
      <button class="btn btn-sm" id="pwd-add">添加</button>
      <button class="btn btn-sm" id="pwd-sort" title="按字典序排序">↕ A-Z</button>
    </div>
    <div id="pwd-warn" style="color:#ef9a9a;font-size:.78rem;min-height:16px;margin-top:6px"></div>
  </div>
</section>

<section>
  <h2>正在运行的任务</h2>
  <div id="current-wrap"><p class="empty">暂无任务</p></div>
</section>

<section>
  <h2>待确认任务</h2>
  <div id="pending-wrap"><p class="empty">无</p></div>
</section>

<section>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e1e1e">
    <span style="color:#81d4fa;font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em">历史记录</span>
    <button class="btn btn-sm btn-danger" id="clear-history-btn">清除历史</button>
  </div>
  <table>
    <thead><tr>
      <th></th><th>文件名</th><th>状态</th><th>密码</th>
      <th>失败原因</th><th>完成时间</th><th>操作</th>
    </tr></thead>
    <tbody id="history-body">
      <tr><td colspan="7" class="empty" style="padding:10px">暂无记录</td></tr>
    </tbody>
  </table>
</section>

<div id="sb"><span class="dot off" id="dot"></span><span id="sb-text">连接中...</span></div>

<script>
const API_KEY = '__API_KEY__';
async function apiFetch(url, opts={}) {
  const headers = Object.assign({'X-API-Key': API_KEY}, opts.headers || {});
  return fetch(url, {...opts, headers});
}
const openDetails = new Set();
// Map<task_id, intervalId> — one elapsed timer per running task
const elapsedTimers = new Map();
let ws, reconnTimer;

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
  ws.onmessage = e => render(JSON.parse(e.data));
}

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function badge(status) {
  const cls   = {extracting:'badge-extracting',done:'badge-done',failed:'badge-failed',partial:'badge-partial',cancelled:'badge-cancelled'}[status] || 'badge-waiting';
  const label = {extracting:'解压中',done:'完成',failed:'失败',partial:'部分失败',waiting:'等待中',cancelled:'已取消'}[status] || status;
  return '<span class="badge ' + cls + '">' + label + '</span>';
}

function fmtTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
  catch(e) { return iso; }
}

function formatDuration(ms) {
  if (ms < 0) ms = 0;
  const s   = Math.floor(ms / 1000);
  const h   = Math.floor(s / 3600);
  const m   = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm  = String(m).padStart(2, '0');
  const ss  = String(sec).padStart(2, '0');
  return h > 0 ? h + ':' + mm + ':' + ss : mm + ':' + ss;
}

function syncElapsedTimers(currentTasks) {
  const liveIds = new Set(Object.keys(currentTasks));
  // Stop timers for tasks that have finished
  for (const [tid, iv] of elapsedTimers) {
    if (!liveIds.has(tid)) {
      clearInterval(iv);
      elapsedTimers.delete(tid);
    }
  }
  // Start timers for newly appeared tasks
  for (const [tid, t] of Object.entries(currentTasks)) {
    if (!elapsedTimers.has(tid) && t.started_at) {
      const startMs = new Date(t.started_at).getTime();
      const iv = setInterval(function() {
        const el = document.getElementById('elapsed_' + tid);
        if (el) el.textContent = formatDuration(Date.now() - startMs);
      }, 1000);
      elapsedTimers.set(tid, iv);
    }
  }
}

// ── P1-5a Q4 软暂停按钮 ──────────────────────────────────────────────────
let lastPaused = false;
function updatePauseBtn(paused) {
  lastPaused = !!paused;
  const btn = document.getElementById('pause-btn');
  if (lastPaused) {
    btn.textContent = '▶ 恢复';
    btn.style.cssText = 'float:right;font-weight:normal;font-size:.75rem;margin-top:6px;background:#4a3010;color:#ff9800;border-color:#ff9800';
  } else {
    btn.textContent = '⏸ 暂停';
    btn.style.cssText = 'float:right;font-weight:normal;font-size:.75rem;margin-top:6px';
  }
}
document.getElementById('pause-btn').addEventListener('click', async () => {
  const url = lastPaused ? '/api/resume' : '/api/pause';
  const r = await apiFetch(url, {method:'POST'});
  if (r.ok) {
    const j = await r.json();
    updatePauseBtn(j.paused);
  }
});

function render(data) {
  const currentTasks = data.current_tasks || {};
  const taskEntries  = Object.entries(currentTasks);

  // Pause button state (P1-5a Q4)
  updatePauseBtn(data.paused);

  // Bot status
  const statusEl = document.getElementById('bot-status');
  if (taskEntries.length > 0) {
    statusEl.textContent = '解压中';
    statusEl.className = 'status-busy';
  } else {
    statusEl.textContent = '待机中';
    statusEl.className = 'status-idle';
  }

  // Banners
  const eb = document.getElementById('error-banner');
  const pb = document.getElementById('partial-banner');
  const lastItem = data.history && data.history.length > 0 ? data.history[data.history.length - 1] : null;
  eb.style.display = 'none';
  pb.style.display = 'none';
  if (taskEntries.length === 0 && lastItem) {
    if (lastItem.status === 'failed') {
      eb.style.display = '';
      eb.textContent = '⚠️ 上次解压失败：' + esc(lastItem.name) + (lastItem.error ? '  (' + esc(lastItem.error) + ')' : '');
    } else if (lastItem.status === 'partial') {
      pb.style.display = '';
      pb.textContent = '⚠️ 上次文件夹部分失败：' + esc(lastItem.name);
    }
  }

  // Current tasks (one card per running task)
  const cw = document.getElementById('current-wrap');
  syncElapsedTimers(currentTasks);
  if (taskEntries.length > 0) {
    cw.innerHTML = taskEntries.map(function(entry) {
      const tid = entry[0], t = entry[1];
      let meta = '';
      if (t.kind === 'folder') {
        if (t.total_archives != null) {
          const cur = t.current_archive ? esc(t.current_archive) : '…';
          meta += '<span>📁 第 ' + (t.current_archive_idx || 0) + '/' + t.total_archives + ' 个：' + cur + '</span>';
        }
        if (t.trying_password) meta += '<span>🔑 ' + esc(t.trying_password) + '</span>';
      } else {
        if (t.trying_password) meta += '<span>🔑 尝试密码：' + esc(t.trying_password) + '</span>';
      }
      const startMs   = t.started_at ? new Date(t.started_at).getTime() : null;
      const initElapsed = startMs ? formatDuration(Date.now() - startMs) : '…';
      meta += '<span>⏱ <span id="elapsed_' + esc(tid) + '">' + initElapsed + '</span></span>';
      // P2-2 进度条
      const pct = (typeof t.progress_pct === 'number') ? t.progress_pct : -1;
      let progressHtml = '';
      if (pct >= 0) {
        progressHtml = '<div class="extract-progress">'
          + '<div class="extract-progress-bar"><div class="extract-progress-fill" style="width:' + pct + '%"></div></div>'
          + '<span class="extract-progress-pct">' + pct + '%</span>'
          + '</div>';
      } else {
        progressHtml = '<div class="extract-progress-unknown">解压中…</div>';
      }
      const cancelBtn = '<button class="btn btn-sm uz-cancel-btn" data-task-id="' + esc(tid) + '" style="color:#ef9a9a;float:right">取消</button>';
      return '<div class="card">'
        + '<div class="card-name">' + esc(t.name) + badge(t.status) + cancelBtn + '</div>'
        + '<div class="card-meta">' + meta + '</div>'
        + progressHtml
        + '</div>';
    }).join('');
  } else {
    cw.innerHTML = '<p class="empty">暂无任务</p>';
  }

  // Pending
  const pw = document.getElementById('pending-wrap');
  if (data.pending && data.pending.length > 0) {
    pw.innerHTML = data.pending.map(function(p) {
      const icon  = p.kind === 'folder' ? '📁' : '📦';
      const label = p.kind === 'folder' ? '确认解压文件夹' : '确认解压多卷包';
      return '<div class="pending-row">'
        + '<div><div class="pending-name">' + icon + ' ' + esc(p.name) + '</div>'
        + '<div class="pending-id">ID: ' + esc(p.id) + '</div></div>'
        + '<button class="btn btn-sm" onclick="confirmPkg(&quot;' + esc(p.id) + '&quot;)">' + label + '</button>'
        + '</div>';
    }).join('');
  } else {
    pw.innerHTML = '<p class="empty">无</p>';
  }

  // History (newest first)
  const hb = document.getElementById('history-body');
  if (data.history && data.history.length > 0) {
    const rows = [];
    data.history.slice().reverse().forEach(function(h, revIdx) {
      const origIdx  = data.history.length - 1 - revIdx;
      const detailId = 'detail_' + origIdx;
      const isOpen   = openDetails.has(detailId);
      const isFailed  = h.status === 'failed';
      const isPartial = h.status === 'partial';
      const isCancelled = h.status === 'cancelled';
      const isFolder  = h.kind === 'folder' && Array.isArray(h.archives) && h.archives.length > 0;
      const errText   = h.error || '';
      const rowCls    = isFailed ? ' class="row-failed"' : isPartial ? ' class="row-partial"' : isCancelled ? ' class="row-cancelled"' : '';

      let toggleBtn = '';
      if (isFolder) {
        toggleBtn = '<button class="toggle-btn" onclick="toggleDetail(&quot;' + detailId + '&quot;,this)">'
          + (isOpen ? '▼' : '▶') + '</button>';
      }

      let openBtn = '';
      if ((h.status === 'done' || h.status === 'partial') && h.out_dir) {
        openBtn = '<button class="btn btn-sm open-btn" data-path="' + esc(h.out_dir) + '">打开文件夹</button>';
      }

      let timeCell = fmtTime(h.finished_at);
      if (h.started_at && h.finished_at) {
        const dur = formatDuration(new Date(h.finished_at) - new Date(h.started_at));
        timeCell += ' <span style="color:#555">(' + dur + ')</span>';
      }

      rows.push('<tr' + rowCls + '>'
        + '<td style="width:28px">' + toggleBtn + '</td>'
        + '<td class="td-name">' + esc(h.name) + '</td>'
        + '<td>' + badge(h.status) + '</td>'
        + '<td class="td-muted">' + (h.password ? esc(h.password) : '—') + '</td>'
        + '<td class="td-error" title="' + esc(errText) + '">' + (errText ? esc(errText) : '—') + '</td>'
        + '<td class="td-muted">' + timeCell + '</td>'
        + '<td>' + openBtn + '</td>'
        + '</tr>');

      if (isFolder) {
        let subRows = h.archives.map(function(a) {
          const aCls     = a.status === 'failed' ? ' style="color:#ef5350"' : '';
          const aFullDir = h.out_dir && a.out_subdir ? h.out_dir + '/' + a.out_subdir : '';
          let aOpenBtn = '';
          if (aFullDir) {
            if (a.status === 'done') {
              aOpenBtn = '<button class="btn btn-sm open-btn" data-path="' + esc(aFullDir) + '">打开</button>';
            } else if (a.status === 'failed') {
              aOpenBtn = '<button class="btn btn-sm open-btn" data-path="' + esc(aFullDir) + '">打开所在目录</button>';
            }
          }
          return '<tr>'
            + '<td' + aCls + '>' + esc(a.name) + '</td>'
            + '<td>' + badge(a.status) + '</td>'
            + '<td class="td-muted">' + (a.password ? esc(a.password) : '—') + '</td>'
            + '<td class="td-error">' + (a.error ? esc(a.error) : '—') + '</td>'
            + '<td>' + aOpenBtn + '</td>'
            + '</tr>';
        }).join('');

        let residualHtml = '';
        if (h.residuals && h.residuals.length > 0) {
          residualHtml = '<div class="residual-warn">⚠️ 残留 ' + h.residuals.length + ' 个文件，原文件夹已保留</div>';
        }

        rows.push('<tr id="' + detailId + '" class="detail-row' + (isOpen ? ' open' : '') + '">'
          + '<td class="detail-cell" colspan="7">'
          + '<table class="detail-table">'
          + '<thead><tr><th>文件名</th><th>状态</th><th>密码</th><th>失败原因</th><th>操作</th></tr></thead>'
          + '<tbody>' + subRows + '</tbody>'
          + '</table>'
          + residualHtml
          + '</td></tr>');
      }
    });
    hb.innerHTML = rows.join('');
  } else {
    hb.innerHTML = '<tr><td colspan="7" class="empty" style="padding:10px">暂无记录</td></tr>';
  }
}

function toggleDetail(id, btn) {
  const row = document.getElementById(id);
  if (!row) return;
  if (openDetails.has(id)) {
    openDetails.delete(id);
    row.classList.remove('open');
    btn.textContent = '▶';
  } else {
    openDetails.add(id);
    row.classList.add('open');
    btn.textContent = '▼';
  }
}

document.addEventListener('click', async function(e) {
  const btn = e.target.closest('.open-btn');
  if (btn) {
    btn.disabled = true;
    try {
      const r = await apiFetch('/api/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: btn.dataset.path})
      });
      if (!r.ok) {
        const j = await r.json();
        alert(j.error || '打开失败');
      }
    } finally {
      btn.disabled = false;
    }
    return;
  }
  // P2-4 取消按钮
  const cb = e.target.closest('.uz-cancel-btn');
  if (cb) {
    if (!confirm('确认取消该解压任务？\\n输出目录会被删除回滚到初始状态。')) return;
    cb.disabled = true;
    cb.textContent = '取消中…';
    try {
      const r = await apiFetch('/api/cancel/' + encodeURIComponent(cb.dataset.taskId), {method:'POST'});
      if (!r.ok) {
        const j = await r.json().catch(()=>({}));
        alert(j.error || '取消失败');
        cb.disabled = false;
        cb.textContent = '取消';
      }
    } catch(err) {
      alert('请求失败：' + err);
      cb.disabled = false;
      cb.textContent = '取消';
    }
  }
});

async function confirmPkg(id) {
  try {
    const r = await apiFetch('/api/confirm/' + id, {method:'POST'});
    const j = await r.json();
    if (!j.ok) alert('确认失败：' + (j.error || '未知错误'));
  } catch(e) { alert('请求失败：' + e.message); }
}

connect();

document.getElementById('clear-history-btn').addEventListener('click', async function() {
  if (!confirm('清除所有历史记录？（不删除本地文件）')) return;
  this.disabled = true;
  try {
    const r = await apiFetch('/api/history', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({all: true})
    });
    const j = await r.json();
    if (!j.ok) alert('清除失败：' + (j.error || '未知错误'));
  } catch(e) {
    alert('请求失败：' + e.message);
  } finally {
    this.disabled = false;
  }
});

// ── P1-6 Path management ─────────────────────────────────────────────────────
document.getElementById('st-toggle').addEventListener('click', () => {
  const panel = document.getElementById('st-panel');
  const arrow = document.getElementById('st-arrow');
  const show  = panel.style.display === 'none';
  panel.style.display   = show ? 'block' : 'none';
  arrow.style.transform = show ? 'rotate(90deg)' : '';
});

function escapeHtmlPath(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function buildHistoryOptions(selectId, currentValue, defaultValue, history) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const opts = [];
  opts.push('<option value="">-- 选择历史路径 --</option>');
  opts.push('<option value="' + escapeHtmlPath(defaultValue) + '">系统默认: ' + escapeHtmlPath(defaultValue) + '</option>');
  (history || []).forEach(p => {
    if (p && p !== defaultValue) {
      opts.push('<option value="' + escapeHtmlPath(p) + '">' + escapeHtmlPath(p) + '</option>');
    }
  });
  sel.innerHTML = opts.join('');
}

async function loadPathSettings() {
  try {
    const r = await apiFetch('/api/settings');
    const s = await r.json();
    if (!s.ok) return;
    document.getElementById('wp-current').textContent = s.watch_path;
    document.getElementById('wp-current').dataset.default = s.default_watch_path;
    const wpInput = document.getElementById('wp-input');
    if (document.activeElement !== wpInput) wpInput.value = s.watch_path;
    buildHistoryOptions('wp-history', s.watch_path, s.default_watch_path, s.watch_path_history);

    document.getElementById('op-current').textContent = s.output_path;
    document.getElementById('op-current').dataset.default = s.default_output_path;
    const opInput = document.getElementById('op-input');
    if (document.activeElement !== opInput) opInput.value = s.output_path;
    buildHistoryOptions('op-history', s.output_path, s.default_output_path, s.output_path_history);
  } catch(e) { /* ignore */ }
}

document.getElementById('wp-history').addEventListener('change', e => {
  if (e.target.value) document.getElementById('wp-input').value = e.target.value;
});
document.getElementById('op-history').addEventListener('change', e => {
  if (e.target.value) document.getElementById('op-input').value = e.target.value;
});

async function savePath(field, inputId, btnId, extra) {
  const val   = document.getElementById(inputId).value.trim();
  const btn   = document.getElementById(btnId);
  const warn  = document.getElementById('path-warn');
  warn.textContent = ''; warn.style.color = '#ffd54f';
  if (!val) { warn.textContent = '路径不能为空'; return; }
  btn.disabled = true; const oldText = btn.textContent; btn.textContent = '保存中…';
  try {
    const body = Object.assign({[field]: val}, extra || {});
    const r = await apiFetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const j = await r.json();
    if (j.ok) {
      btn.style.background = '#2e7d32'; btn.textContent = '已保存 ✓';
      warn.style.color = '#81c784';
      warn.textContent = j.requires_restart
        ? (j.restart_reason || '需重启服务后生效')
        : '已生效（仅影响新任务）';
      setTimeout(() => { btn.style.background=''; btn.textContent=oldText; btn.disabled=false; }, 2500);
      await loadPathSettings();
    } else {
      warn.textContent = j.error || '保存失败';
      btn.disabled = false; btn.textContent = oldText;
    }
  } catch(e) {
    warn.textContent = '请求失败'; btn.disabled = false; btn.textContent = oldText;
  }
}

document.getElementById('wp-save').addEventListener('click', () => {
  const sync = document.getElementById('wp-sync').checked;
  savePath('watch_path', 'wp-input', 'wp-save', {sync_downloader: sync});
});
document.getElementById('wp-open').addEventListener('click', () => {
  openLocalPath(document.getElementById('wp-current').textContent.trim());
});
document.getElementById('op-save').addEventListener('click', () => {
  savePath('output_path', 'op-input', 'op-save');
});

async function openLocalPath(path) {
  if (!path) return;
  try {
    const r = await apiFetch('/api/open', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path})
    });
    const j = await r.json();
    if (!j.ok) {
      const warn = document.getElementById('path-warn');
      warn.style.color = '#ef5350';
      warn.textContent = '打开失败：' + (j.error || r.status);
      setTimeout(() => { warn.textContent = ''; }, 3000);
    }
  } catch(e) { /* ignore */ }
}

document.getElementById('op-open').addEventListener('click', () => {
  openLocalPath(document.getElementById('op-current').textContent.trim());
});

loadPathSettings();

// ── P1-pwd: 密码管理 ─────────────────────────────────────────────────
let currentPasswords = [];
let pwdReorderTimer = null;

document.getElementById('pwd-toggle').addEventListener('click', () => {
  const panel = document.getElementById('pwd-panel');
  const arrow = document.getElementById('pwd-arrow');
  const show  = panel.style.display === 'none';
  panel.style.display   = show ? 'block' : 'none';
  arrow.style.transform = show ? 'rotate(90deg)' : '';
});

function renderPasswordList() {
  const list = document.getElementById('pwd-list');
  document.getElementById('pwd-count').textContent = '(' + currentPasswords.length + ')';
  if (!currentPasswords.length) {
    list.innerHTML = '<p class="empty">暂无解压密码，点击下方添加</p>';
    return;
  }
  list.innerHTML = currentPasswords.map((pw, idx) => {
    const masked = '•'.repeat(Math.min(pw.length, 20));
    return '<div class="pwd-row" draggable="true" data-idx="' + idx + '">'
      + '<span class="pwd-handle" title="拖动重排">⠿</span>'
      + '<span class="pwd-text" data-pw="' + esc(pw) + '" data-show="0">' + esc(masked) + '</span>'
      + '<button class="btn btn-sm pwd-toggle-btn" data-idx="' + idx + '" title="显示/隐藏" style="padding:2px 8px">👁</button>'
      + '<button class="btn btn-sm pwd-del-btn" data-idx="' + idx + '" title="删除" style="padding:2px 8px;color:#ef9a9a">✕</button>'
      + '</div>';
  }).join('');
}

async function loadPasswords() {
  try {
    const r = await apiFetch('/api/passwords');
    const j = await r.json();
    if (j.ok) {
      currentPasswords = j.passwords || [];
      renderPasswordList();
    }
  } catch (e) { /* ignore */ }
}

async function addPassword() {
  const inp  = document.getElementById('pwd-input');
  const warn = document.getElementById('pwd-warn');
  const pw   = inp.value;
  warn.textContent = '';

  if (!pw.trim()) { warn.textContent = '密码不能为空'; return; }
  if (pw.includes('\\n') || pw.includes('\\r')) {
    warn.textContent = '密码不能包含换行符'; return;
  }
  if (currentPasswords.includes(pw)) {
    warn.textContent = '密码已存在'; return;
  }

  try {
    const r = await apiFetch('/api/passwords', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({password: pw}),
    });
    const j = await r.json();
    if (j.ok) {
      currentPasswords = j.passwords || [];
      inp.value = '';
      renderPasswordList();
    } else {
      warn.textContent = j.error || '添加失败';
    }
  } catch (e) {
    warn.textContent = '请求失败：' + e.message;
  }
}

document.getElementById('pwd-add').addEventListener('click', addPassword);
document.getElementById('pwd-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') addPassword();
});

// ✕ 删除 / 👁 切换显示（事件代理）
document.getElementById('pwd-list').addEventListener('click', async (e) => {
  const delBtn = e.target.closest('.pwd-del-btn');
  if (delBtn) {
    const idx = parseInt(delBtn.dataset.idx);
    const pw  = currentPasswords[idx];
    if (pw === undefined) return;
    try {
      const r = await apiFetch('/api/passwords', {
        method:'DELETE', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({password: pw}),
      });
      const j = await r.json();
      if (j.ok) {
        currentPasswords = j.passwords || [];
        renderPasswordList();
      } else {
        document.getElementById('pwd-warn').textContent = '删除失败：' + (j.error || '未知错误');
      }
    } catch (err) {
      document.getElementById('pwd-warn').textContent = '请求失败：' + err.message;
    }
    return;
  }

  const tgBtn = e.target.closest('.pwd-toggle-btn');
  if (tgBtn) {
    const row = tgBtn.closest('.pwd-row');
    const txt = row.querySelector('.pwd-text');
    const show = txt.dataset.show === '1';
    if (show) {
      const pw = txt.dataset.pw;
      const masked = '•'.repeat(Math.min(pw.length, 20));
      txt.textContent = masked;
      txt.dataset.show = '0';
    } else {
      txt.textContent = txt.dataset.pw;
      txt.dataset.show = '1';
    }
  }
});

// 拖拽重排（HTML5 drag-and-drop + 500ms debounce）
(function setupDrag(){
  const list = document.getElementById('pwd-list');
  let dragSrcIdx = null;

  list.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.pwd-row');
    if (!row) return;
    dragSrcIdx = parseInt(row.dataset.idx);
    row.style.opacity = '0.4';
    e.dataTransfer.effectAllowed = 'move';
  });

  list.addEventListener('dragend', (e) => {
    const row = e.target.closest('.pwd-row');
    if (row) row.style.opacity = '';
  });

  list.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  });

  list.addEventListener('drop', (e) => {
    e.preventDefault();
    const targetRow = e.target.closest('.pwd-row');
    if (!targetRow || dragSrcIdx === null) return;
    const dstIdx = parseInt(targetRow.dataset.idx);
    if (dstIdx === dragSrcIdx) return;

    const moved = currentPasswords.splice(dragSrcIdx, 1)[0];
    currentPasswords.splice(dstIdx, 0, moved);
    renderPasswordList();
    dragSrcIdx = null;

    clearTimeout(pwdReorderTimer);
    pwdReorderTimer = setTimeout(persistReorder, 500);
  });
})();

async function persistReorder() {
  try {
    const r = await apiFetch('/api/passwords/reorder', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({passwords: currentPasswords}),
    });
    const j = await r.json();
    if (!j.ok) {
      document.getElementById('pwd-warn').textContent = '重排失败：' + (j.error || '未知错误');
      await loadPasswords();   // 拉回真实顺序
    }
  } catch (e) {
    document.getElementById('pwd-warn').textContent = '请求失败：' + e.message;
    await loadPasswords();
  }
}

document.getElementById('pwd-sort').addEventListener('click', async () => {
  if (currentPasswords.length < 2) return;
  const sorted = [...currentPasswords].sort((a, b) => a.localeCompare(b));
  if (sorted.every((p, i) => p === currentPasswords[i])) return;
  currentPasswords = sorted;
  renderPasswordList();
  // 立即持久化（不走 debounce）
  clearTimeout(pwdReorderTimer);
  await persistReorder();
});

loadPasswords();
</script>
<button class="scroll-top-btn" title="回到顶部" onclick="window.scrollTo({top:0,behavior:'smooth'})">↑</button>
</body>
</html>"""
