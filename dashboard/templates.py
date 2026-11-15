# SPDX-License-Identifier: AGPL-3.0-or-later
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TGhelper</title>
<style>
  :root{
    --bg:#16181c; --panel:#1f2228; --panel2:#23262d; --line:#2e323b;
    --txt:#e3e6ea; --dim:#8b929c; --dim2:#666c76;
    /* --grn = TGhelper 品牌绿（与安卓 App 图标/主题同色 #2E9E5B），网页+手机端统一主色调 */
    --grn:#2E9E5B; --grn-dark:#1F6E43; --blu:#3d9be0; --amb:#ffb020; --red:#ef5350; --pur:#a678e0;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg);color:var(--txt);line-height:1.5;font-size:14px;-webkit-font-smoothing:antialiased}
  button{font-family:inherit}
  a{color:var(--blu);text-decoration:none}

  /* 顶栏 */
  .topbar{position:sticky;top:0;z-index:50;background:rgba(22,24,28,.92);backdrop-filter:blur(8px);
    border-bottom:1px solid var(--line);padding:.7rem 1.1rem}
  .topbar-row{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
  /* 品牌字：名字用白、后半截 TGhelper 用主色强调 */
  .brand{font-size:18px;font-weight:700;letter-spacing:.5px;color:var(--txt);display:flex;align-items:center;gap:.5rem}
  .brand .brand-accent{color:var(--grn)}
  .brand .logo{font-size:1.3rem;letter-spacing:normal}
  .top-right{display:flex;align-items:center;gap:.9rem}
  .updated{font-size:.76rem;color:var(--dim2);font-variant-numeric:tabular-nums}
  /* 右上角吞吐量小窗：当前总速率 + 最近 60 个采样点的迷你走势 */
  .thr{display:flex;align-items:center;gap:.5rem;padding:.28rem .6rem;border:1px solid var(--line);
       border-radius:8px;background:var(--panel2);line-height:1.15}
  .thr-num{font-size:.95rem;font-weight:600;font-variant-numeric:tabular-nums;color:var(--grn)}
  .thr-num.idle{color:var(--dim2)}
  .thr-unit{font-size:.68rem;color:var(--dim);margin-left:.1rem}
  .thr-sub{font-size:.64rem;color:var(--dim2);font-variant-numeric:tabular-nums}
  .thr-spark{display:block}
  @media(max-width:620px){ .thr-spark{display:none} .thr{padding:.24rem .45rem} }

  /* 流水线状态条 */
  .pipeline{display:flex;align-items:stretch;gap:0;margin-top:.7rem;flex-wrap:wrap}
  .stage{flex:1;min-width:150px;display:flex;align-items:center;gap:.6rem;
    background:var(--panel);border:1px solid var(--line);padding:.55rem .8rem}
  .stage:first-child{border-radius:8px 0 0 8px}
  .stage:last-child{border-radius:0 8px 8px 0}
  .stage+.stage{border-left:none}
  .stage .dot{width:9px;height:9px;border-radius:50%;background:var(--dim2);flex:none;transition:background .2s}
  .stage .dot.on{background:var(--grn)} .stage .dot.off{background:var(--red)}
  .stage .dot.busy{background:var(--blu);box-shadow:0 0 0 3px rgba(61,155,224,.2)}
  .stage .dot.paused{background:var(--amb)}
  .stage-body{display:flex;flex-direction:column;line-height:1.25;min-width:0}
  .stage-name{font-size:.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
  .stage-stat{font-size:.95rem;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
  .stage-arrow{display:flex;align-items:center;color:var(--dim2);font-size:1rem;padding:0 .15rem}

  /* 标签导航 */
  .tabs{display:flex;gap:.25rem;margin-top:.8rem;flex-wrap:wrap}
  .tab{background:none;border:none;color:var(--dim);padding:.45rem .9rem;border-radius:6px;
    font-size:.92rem;cursor:pointer;position:relative;display:flex;align-items:center;gap:.4rem}
  .tab:hover{color:var(--txt);background:var(--panel)}
  .tab.active{color:var(--grn);background:var(--panel)}
  .tab .badge{background:var(--red);color:#fff;font-size:.68rem;font-weight:700;border-radius:10px;
    padding:0 .35rem;min-width:16px;text-align:center;display:none}
  .tab .badge.show{display:inline-block}

  /* 主区 */
  main{max-width:1100px;margin:0 auto;padding:1.1rem}
  .panel-view{display:none} .panel-view.active{display:block}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:1rem 1.1rem;margin-bottom:1rem}
  .card h3{margin:0 0 .8rem;font-size:.82rem;font-weight:600;color:var(--dim);
    text-transform:uppercase;letter-spacing:.05em;display:flex;align-items:center;justify-content:space-between}
  .empty{color:var(--dim2);font-size:.9rem;padding:1.2rem;text-align:center}

  /* 进度行 */
  .prog-item{padding:.6rem 0;border-bottom:1px solid var(--line)}
  .queue-item{display:flex;align-items:center;gap:.5rem;padding:.28rem 0;border-bottom:1px solid var(--line);font-size:.86rem}
  .queue-item .q-idx{flex:none;min-width:1.6rem;text-align:right;color:var(--dim2);font-variant-numeric:tabular-nums}
  .queue-item .q-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dim)}
  .prog-item:last-child{border-bottom:none}
  .prog-head{display:flex;justify-content:space-between;gap:.8rem;margin-bottom:.35rem}
  .prog-name{font-size:.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
  .prog-meta{font-size:.78rem;color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap;flex:none}
  .bar{height:6px;background:var(--panel2);border-radius:3px;overflow:hidden}
  .bar>i{display:block;height:100%;background:var(--blu);border-radius:3px;transition:width .5s ease}

  /* 通用列表/表 */
  .row{display:flex;align-items:center;gap:.7rem;padding:.55rem .2rem;border-bottom:1px solid var(--line)}
  .row:last-child{border-bottom:none}
  .row .grow{flex:1;min-width:0}
  .row .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .row .sub{font-size:.76rem;color:var(--dim2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .pill{font-size:.72rem;padding:.1rem .5rem;border-radius:10px;font-weight:600;white-space:nowrap}
  .pill.done{background:rgba(46,158,91,.15);color:var(--grn)}
  .pill.run{background:rgba(61,155,224,.15);color:var(--blu)}
  .pill.fail{background:rgba(239,83,80,.15);color:var(--red)}
  .pill.wait{background:rgba(255,176,32,.15);color:var(--amb)}
  .pill.stage-dl{background:rgba(166,120,224,.15);color:var(--pur)}

  /* 按钮 */
  .btn{background:var(--panel2);border:1px solid var(--line);color:var(--txt);border-radius:6px;
    padding:.4rem .8rem;font-size:.85rem;cursor:pointer;transition:all .15s;white-space:nowrap}
  .btn:hover{border-color:var(--grn);color:var(--grn)}
  .btn.sm{padding:.25rem .55rem;font-size:.78rem}
  .btn.danger:hover{border-color:var(--red);color:var(--red)}
  .btn.primary{background:var(--grn-dark);border-color:var(--grn-dark);color:#fff}
  .btn.primary:hover{background:var(--grn);color:#fff}
  .btn:disabled{opacity:.5;cursor:not-allowed}
  .btn-group{display:flex;gap:.4rem;flex-wrap:wrap}
  .filters{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.8rem}
  .chip{background:var(--panel2);border:1px solid var(--line);color:var(--dim);border-radius:14px;
    padding:.25rem .8rem;font-size:.82rem;cursor:pointer}
  .chip.active{background:var(--grn);border-color:var(--grn);color:#0d1f0e;font-weight:600}
  /* 列表工具栏（搜索/排序/筛选） */
  .list-tools{display:flex;gap:.45rem;flex-wrap:wrap;align-items:center;margin:0 0 .7rem}
  .list-tools input[type=search]{flex:1;min-width:150px;padding:.38rem .65rem;background:var(--panel2);
    border:1px solid var(--line);border-radius:6px;color:var(--txt);font-size:.85rem;outline:none}
  .list-tools input[type=search]:focus{border-color:var(--grn)}
  .list-tools select{padding:.38rem .5rem;background:var(--panel2);border:1px solid var(--line);
    border-radius:6px;color:var(--txt);font-size:.83rem}
  /* 任务行可展开的完整路径 */
  .paths{display:none;margin-top:.35rem;padding:.4rem .55rem;background:var(--panel2);border-radius:6px;
    font-family:ui-monospace,monospace;font-size:.74rem;color:var(--dim);word-break:break-all;line-height:1.5}
  .paths.show{display:block}
  input[type=text],input[type=number],select{background:var(--bg);border:1px solid var(--line);color:var(--txt);
    border-radius:6px;padding:.45rem .6rem;font-size:.88rem;font-family:inherit}
  input:focus,select:focus{outline:none;border-color:var(--grn)}

  /* 设置 */
  .field{display:flex;align-items:center;gap:.8rem;margin-bottom:.6rem;flex-wrap:wrap}
  .field label{flex:0 0 210px;color:var(--dim)}
  .field input,.field select{flex:1;min-width:160px}
  .field .eff{flex-basis:100%;color:var(--dim2);font-size:.74rem;padding-left:210px;word-break:break-all}
  .banner{background:rgba(61,155,224,.1);border:1px solid var(--blu);color:#a9d5f2;
    border-radius:6px;padding:.6rem .8rem;font-size:.82rem;margin-bottom:1rem;display:none}
  .banner.show{display:block}
  .msg{font-size:.85rem;margin-left:.5rem}
  .msg.ok{color:var(--grn)} .msg.err{color:var(--red)}
  .msg code{background:var(--bg);border:1px solid var(--line);border-radius:3px;padding:.05rem .35rem}

  /* toast 通知 */
  #toaster{position:fixed;bottom:20px;right:20px;z-index:200;display:flex;flex-direction:column;gap:.5rem}
  .toast{background:var(--panel2);border:1px solid var(--line);border-left:3px solid var(--grn);
    border-radius:6px;padding:.6rem .9rem;font-size:.85rem;max-width:320px;box-shadow:0 4px 16px rgba(0,0,0,.4)}
  .toast.err{border-left-color:var(--red)}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-row">
    <div class="brand"><span class="logo">📥</span> <span id="brand-name">Hyden</span><span class="brand-accent">TGhelper</span></div>
    <div class="top-right">
      <div class="thr" id="thr" title="下载总吞吐量（所有并发任务之和）">
        <div>
          <div><span class="thr-num idle" id="thr-num">—</span><span class="thr-unit" id="thr-unit"></span></div>
          <div class="thr-sub" id="thr-sub">吞吐量</div>
        </div>
        <svg class="thr-spark" id="thr-spark" width="62" height="22" viewBox="0 0 62 22" preserveAspectRatio="none">
          <polyline id="thr-line" fill="none" stroke="var(--grn)" stroke-width="1.5"
                    stroke-linejoin="round" stroke-linecap="round" points=""></polyline>
        </svg>
      </div>
      <span class="updated" id="updated">连接中…</span>
    </div>
  </div>

  <div class="pipeline">
    <div class="stage"><span class="dot" id="pdot-dl"></span>
      <div class="stage-body"><span class="stage-name">下载 Downloader</span>
        <span class="stage-stat" id="pstat-dl">—</span></div></div>
    <span class="stage-arrow">→</span>
    <div class="stage"><span class="dot" id="pdot-mv"></span>
      <div class="stage-body"><span class="stage-name">搬运 Mover</span>
        <span class="stage-stat" id="pstat-mv">—</span></div></div>
    <span class="stage-arrow">→</span>
    <div class="stage"><span class="dot" id="pdot-uz"></span>
      <div class="stage-body"><span class="stage-name">解压 Unzipper</span>
        <span class="stage-stat" id="pstat-uz">—</span></div></div>
  </div>

  <div class="tabs">
    <button class="tab active" data-tab="home">🏠 总览</button>
    <button class="tab" data-tab="channels">📡 频道</button>
    <button class="tab" data-tab="tasks">📋 任务</button>
    <button class="tab" data-tab="inbox">🔔 待办<span class="badge" id="badge-inbox"></span></button>
    <button class="tab" data-tab="settings">⚙️ 设置</button>
  </div>
</div>

<main>
  <!-- 总览 -->
  <div class="panel-view active" id="view-home">
    <div class="card"><h3>正在下载 <span id="home-dl-count" class="dim"></span></h3>
      <div class="list-tools"><input type="search" id="home-dl-search" placeholder="搜索下载中 / 排队…"></div>
      <div id="home-downloads"><div class="empty">加载中…</div></div></div>
    <div class="card"><h3>正在解压</h3>
      <div id="home-unzips"><div class="empty">—</div></div></div>
    <div class="card"><h3>最近完成</h3>
      <div class="list-tools"><input type="search" id="recent-search" placeholder="搜索最近完成…">
        <select id="recent-stage"><option value="all">全部阶段</option><option value="下载">📥 下载</option><option value="搬运">🚚 搬运</option><option value="解压">📦 解压</option></select></div>
      <div id="home-recent"><div class="empty">—</div></div></div>
  </div>

  <!-- 频道 -->
  <div class="panel-view" id="view-channels">
    <div class="card"><h3>添加监听（搜索你的对话）</h3>
      <div class="field"><input type="text" id="ch-search-input" placeholder="输入频道/群组名称关键词">
        <button class="btn primary" id="ch-search-btn">搜索</button></div>
      <div id="ch-search-results"></div></div>
    <div class="card"><h3>监听中 <span class="dim" id="ch-count"></span>
      <button class="btn sm" id="ch-pause-btn">全局暂停:—</button>
      <button class="btn sm" id="ch-expause-btn" title="只管例外频道；开了之后例外频道也停收">例外暂停:—</button>
      <button class="btn sm" id="ch-savedpause-btn" title="只管「我的收藏」；不受另外两个开关和监听列表影响，重启后保持">收藏暂停:—</button></h3>
      <div class="list-tools"><input type="search" id="ch-filter" placeholder="搜索监听中的频道（名称 / ID）…">
        <select id="ch-kind"><option value="all">全部</option><option value="normal">正常监听</option><option value="exempt">例外频道</option><option value="fav">⭐ 喜爱</option></select>
        <select id="ch-sort">
          <option value="name">按名称</option>
          <option value="status">按监听状态</option>
          <option value="added">按添加时间</option>
          <option value="tasks">按任务数</option>
          <option value="exempt">按是否例外</option>
          <option value="fav">按喜爱</option>
        </select>
        <button class="btn sm" id="ch-sort-dir" title="切换升序/降序">↓ 降序</button></div>
      <div id="ch-list"><div class="empty">加载中…</div></div></div>
  </div>

  <!-- 任务 -->
  <div class="panel-view" id="view-tasks">
    <div class="card">
      <h3>任务流<span class="btn-group"><button class="btn sm" id="tasks-retry-dl">↻ 重试下载失败</button><button class="btn sm" id="tasks-retry-mv">↻ 重试搬运失败</button><button class="btn sm" id="tasks-retry-uz">↻ 重试解压失败</button><button class="btn sm danger" id="tasks-clear-done">🗑 删除完成记录</button><button class="btn sm danger" id="tasks-clear-failed">🗑 删除失败记录</button></span></h3>
      <div class="filters" id="task-stage-filters">
        <span class="chip active" data-s="all">全部阶段</span>
        <span class="chip" data-s="下载">📥 下载</span>
        <span class="chip" data-s="搬运">🚚 搬运</span>
        <span class="chip" data-s="解压">📦 解压</span>
      </div>
      <div class="filters" id="task-filters">
        <span class="chip active" data-f="all">全部状态</span>
        <span class="chip" data-f="active">进行中</span>
        <span class="chip" data-f="done">已完成</span>
        <span class="chip" data-f="failed">失败</span>
      </div>
      <div class="list-tools"><input type="search" id="task-search" placeholder="搜索任务（文件名 / 路径 / 错误信息）…">
        <select id="task-sort"><option value="tdesc">最新在前</option><option value="tasc">最旧在前</option><option value="name">按名称</option></select></div>
      <div id="tasks-list"><div class="empty">加载中…</div></div>
    </div>
  </div>

  <!-- 待办 -->
  <div class="panel-view" id="view-inbox">
    <div class="card"><h3>需要你确认</h3>
      <div class="list-tools"><input type="search" id="inbox-search" placeholder="搜索待办…">
        <select id="inbox-kind"><option value="all">全部类型</option><option value="dl">下载确认</option><option value="uz">解压确认</option></select></div>
      <div id="inbox-list"><div class="empty">加载中…</div></div></div>
  </div>

  <!-- 设置 -->
  <div class="panel-view" id="view-settings">
    <div class="banner" id="docker-banner">🐳 Docker 部署：数据目录由宿主机映射决定（改宿主 <b>.env</b> 的
      <b>HOST_DATA_ROOT</b> 后 <b>docker compose up -d</b>），此处路径为只读。</div>

    <div class="card" id="branding-card"><h3>页面标题</h3>
      <div class="field"><label>显示的名字</label>
        <input type="text" id="brand-input" maxlength="30" placeholder="留空 = 用登录的 Telegram 账号名"></div>
      <div class="field"><label></label>
        <span style="display:flex;align-items:center;gap:.4rem;color:var(--txt)"><input type="checkbox" id="brand-hide" style="flex:none;min-width:0;margin:0">
        <span>隐藏名字，只显示「TGhelper」</span></span></div>
      <div style="margin-top:.5rem"><button class="btn primary" id="brand-save">保存</button><span class="msg" id="brand-msg"></span></div>
      <div class="eff">左上角显示「名字 + TGhelper」。保存后马上生效，不用重启。</div>
    </div>

    <div class="card" id="autostart-card"><h3>开机自动启动</h3>
      <div class="row" style="justify-content:space-between;align-items:center">
        <div id="autostart-state" class="dim">读取中…</div>
        <button class="btn btn-sm" id="autostart-btn" style="display:none"></button>
      </div>
      <div class="eff" id="autostart-note" style="margin-top:.5rem"></div>
    </div>

    <!-- 服务启停：只有 Docker 部署有（经 control 服务启停本项目容器）；原生部署整张卡片隐藏 -->
    <div class="card" id="svc-card"><h3>服务启停 <span class="dim" id="svc-hint">（下载 · 搬运 · 解压）</span></h3>
      <div id="svc-list"><div class="empty">加载中…</div></div>
      <div class="eff" style="margin-top:.5rem">
        · 停掉的服务会一直停着，直到你在这里点「启动」（健康检查也不会去拉它）。
        · <b>dashboard</b> 只显示状态、不给按钮——它就是本页面，停了页面就没了。
      </div>
    </div>

    <div class="card"><h3>数据目录 <span class="dim" id="env-path"></span></h3>
      <div class="field"><label>DATA_ROOT（推荐只填这个）</label>
        <input type="text" id="f-DATA_ROOT" placeholder="留空 = 用下方逐项/默认值">
        <div class="eff">保存后自动创建 telegramDMZ/{download,move,unzip}</div></div>
      <div class="field"><label>DOWNLOAD_DIR（下载）</label>
        <input type="text" id="f-DOWNLOAD_DIR" placeholder="留空 = 由 DATA_ROOT 派生">
        <div class="eff" id="eff-DOWNLOAD_DIR"></div></div>
      <div class="field"><label>WATCH_PATH（搬运目标 = 解压监听）</label>
        <input type="text" id="f-WATCH_PATH" placeholder="留空 = 由 DATA_ROOT 派生">
        <div class="eff" id="eff-WATCH_PATH"></div></div>
      <div class="field"><label>OUTPUT_PATH（解压输出）</label>
        <input type="text" id="f-OUTPUT_PATH" placeholder="留空 = 由 DATA_ROOT 派生">
        <div class="eff" id="eff-OUTPUT_PATH"></div></div>
    </div>
    <div class="card"><h3>性能与行为</h3>
      <div class="field"><label>总连接数上限</label><input type="number" id="f-MAX_TOTAL_CONNECTIONS" min="1" max="100"></div>
      <div class="field"><label>解压并发上限</label><input type="number" id="f-MAX_CONCURRENT_TASKS" min="1" max="20"></div>
      <div class="field"><label>搬运并发上限</label><input type="number" id="f-MOVER_MAX_CONCURRENT" min="1" max="20"></div>
      <div class="field"><label>下载超时（秒）</label><input type="number" id="f-DOWNLOAD_TIMEOUT" min="10" max="3600"></div>
      <div class="field"><label>下载完自动搬运</label>
        <select id="f-AUTO_MOVE"><option value="">（默认 true）</option><option value="true">true</option><option value="false">false</option></select></div>
      <div class="field"><label>重启 / 断电来电后</label>
        <select id="f-RESTART_MODE"><option value="">（默认：恢复上次状态）</option><option value="RESUME">恢复上次状态</option><option value="PAUSED">下载监听一律暂停</option></select>
        <div class="eff">「恢复上次状态」：各个暂停开关回到关机前的样子。离线期间积压太多、不想一开机就全开下时，临时改成「一律暂停」。下次启动生效。</div></div>
      <div class="field"><label>日志级别</label>
        <select id="f-LOG_LEVEL"><option value="">（默认 INFO）</option><option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option></select></div>
      <div style="margin-top:1rem"><button class="btn primary" id="save-btn">保存设置</button><span class="msg" id="save-msg"></span></div>
    </div>

    <div class="card"><h3>解压密码库 <span class="dim" id="pw-count"></span></h3>
      <div class="field">
        <input type="text" id="pw-input" placeholder="添加一个解压密码（解密时按顺序尝试）" style="flex:1">
        <button class="btn primary" id="pw-add-btn">添加</button>
      </div>
      <div class="list-tools"><input type="search" id="pw-search" placeholder="搜索密码…"></div>
      <div id="pw-list"><div class="empty">加载中…</div></div>
    </div>
  </div>
</main>
<footer style="text-align:center;padding:1.2rem 0 1.6rem;font-size:12px;color:var(--dim2)">
  Hyden TGhelper · <a href="https://github.com/HydenLuc/Hyden-Telegram-Helper" target="_blank" rel="noopener" style="color:var(--dim)">源码</a> · AGPL-3.0-or-later
</footer>

<div id="toaster"></div>

<script>
// ═══════════ 基础：代理请求 + API Key ═══════════
function apiKey(){ return localStorage.getItem('hyden_api_key') || ''; }
function setKey(k){ localStorage.setItem('hyden_api_key', k); }

async function req(path, opts={}, retried){
  const headers = Object.assign({}, opts.headers||{});
  const k = apiKey();
  if(k) headers['X-API-Key'] = k;
  if(opts.body && !headers['Content-Type']) headers['Content-Type']='application/json';
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  if(r.status===401){
    // 并发请求：若别处已设了新 key，直接静默重试，不再弹框
    if(!retried && apiKey() && apiKey()!==k) return req(path, opts, true);
    if(retried){ localStorage.removeItem('hyden_api_key'); alert('API Key 不正确，请重新输入完整的 key。'); }
    const key = prompt('该服务启用了 API Key，请粘贴完整 key（不含 API_KEY= 前缀）：', apiKey());
    if(key && key.trim()){ setKey(key.trim()); return req(path, opts, true); }
    throw new Error('需要 API Key');
  }
  return r;
}
// 代理到三模块：px('mv','/api/tasks')  → /api/proxy/mv/api/tasks
function px(mod, path, opts){ return req('/api/proxy/'+mod+path, opts); }
async function pxj(mod, path, opts){ const r = await px(mod,path,opts); return r.ok ? r.json() : null; }

function toast(msg, isErr){
  const t=document.createElement('div'); t.className='toast'+(isErr?' err':'');
  t.textContent=msg; document.getElementById('toaster').appendChild(t);
  setTimeout(()=>{t.style.opacity='0';t.style.transition='opacity .4s';setTimeout(()=>t.remove(),400)}, 3200);
}

// ═══════════ 工具 ═══════════
function fmtBytes(b){ if(b==null) return '-'; if(b>=1073741824) return (b/1073741824).toFixed(1)+' GB';
  if(b>=1048576) return (b/1048576).toFixed(1)+' MB'; if(b>=1024) return (b/1024).toFixed(0)+' KB'; return b+' B'; }
function fmtSpeed(bps){ const m=bps/1048576; return m>=0.1?m.toFixed(1)+' MB/s':(bps/1024).toFixed(0)+' KB/s'; }
function fmtTime(d){ return d.toLocaleTimeString('zh-CN',{hour12:false}); }
// 队列积压能到几万，加千位分隔——「28354」和「28,354」扫一眼的差别很大
function fmtCount(n){ return Number(n||0).toLocaleString('en-US'); }

// ═══════════ 右上角吞吐量小窗 ═══════════
// 数据源是 downloader 的 total_speed（所有并发任务速率之和，字节/秒）。
// 保留最近 60 个采样点画迷你走势；轮询间隔 3 秒，即约 3 分钟的窗口。
const THR_KEEP=60; let thrHist=[];
function renderThroughput(bps, online){
  const numEl=document.getElementById('thr-num'), unitEl=document.getElementById('thr-unit'),
        subEl=document.getElementById('thr-sub'), lineEl=document.getElementById('thr-line');
  if(!online){
    numEl.textContent='—'; numEl.className='thr-num idle';
    unitEl.textContent=''; subEl.textContent='离线'; lineEl.setAttribute('points',''); return;
  }
  bps=bps||0;
  thrHist.push(bps); if(thrHist.length>THR_KEEP) thrHist.shift();
  const mb=bps/1048576;
  numEl.textContent = mb>=0.1 ? mb.toFixed(1) : (bps/1024).toFixed(0);
  unitEl.textContent = mb>=0.1 ? ' MB/s' : ' KB/s';
  numEl.className = 'thr-num' + (bps>0?'':' idle');
  // 副行给峰值，让「现在是不是慢了」一眼能判断
  const peak=Math.max.apply(null, thrHist);
  subEl.textContent = bps>0 ? ('峰值 '+fmtSpeed(peak)) : '空闲';
  // 迷你走势：62x22 的 viewBox，按窗口内峰值归一化
  if(thrHist.length>1){
    const max=peak||1, n=thrHist.length, stepX=62/(THR_KEEP-1);
    lineEl.setAttribute('points', thrHist.map((v,i)=>{
      const x=(i+(THR_KEEP-n))*stepX;          // 右对齐，新数据在右边
      return x.toFixed(1)+','+(21-(v/max)*19).toFixed(1);
    }).join(' '));
  }
}
function ago(t){ if(!t) return '';
  const d=(typeof t==='number')?new Date(t<1e12?t*1000:t):new Date(t);  // downloader 用 unix 秒，其它用 ISO
  const s=(Date.now()-d)/1000; if(s<0||isNaN(s)) return '';
  if(s<60) return Math.floor(s)+'秒前'; if(s<3600) return Math.floor(s/60)+'分钟前';
  if(s<86400) return Math.floor(s/3600)+'小时前'; return Math.floor(s/86400)+'天前'; }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function base(p){ if(!p) return ''; return String(p).split('/').pop().split('\\\\').pop(); }

// ═══════════ 标签切换 ═══════════
let activeTab='home';
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  activeTab=t.dataset.tab;
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===t));
  document.querySelectorAll('.panel-view').forEach(v=>v.classList.toggle('active',v.id==='view-'+activeTab));
  renderTab(activeTab);
}));
function renderTab(name){
  if(name==='channels') loadChannels();
  else if(name==='tasks') loadTasks();
  else if(name==='inbox') loadInbox();
  else if(name==='settings') loadSettings();
}

// ═══════════ 总览 + 流水线状态条（/api/overview 聚合） ═══════════
function setStage(mod, dotCls, stat){
  document.getElementById('pdot-'+mod).className='dot '+dotCls;
  document.getElementById('pstat-'+mod).textContent=stat;
}
let lastO=null;
// 标题「<名字> TGhelper」：名字由服务端算好（自定义 > 登录的 Telegram 账号名 > Hyden；勾了隐藏就是空）
function setBrand(name){
  if(typeof name!=='string') return;
  const el=document.getElementById('brand-name');
  el.textContent=name; el.style.display=name?'':'none';
  document.title=name?(name+' TGhelper'):'TGhelper';
}
async function pollOverview(){
  try{
    const r=await req('/api/overview'); const o=await r.json(); lastO=o;
    setBrand(o.brand_name);
    // 下载
    const dd=o.downloader;
    if(!dd.online){ setStage('dl','off','离线'); renderThroughput(0,false); }
    else if(dd.data){ const d=dd.data;
      // ⚠️ 三个数，2026-08-21 之前把后两个混为一谈了：
      //   active   正在传字节的
      //   waiting  **已占了任务槽、在等连接**的
      //   backlog  **还没开工的整个积压**（pending - active_count）
      // 原来把 waiting 显示成「排队」，于是队列里躺着数万条时首页写着「+2 排队」，
      // 看着像只剩两个要下 —— 差了四个数量级。backlog 才是人想知道的那个。
      //
      // 🔴 前两个一律用**服务端计数**，别自己数 d.active ——
      //    slim=1 会把列表整个剥空、limit 会截断，数出来是 0。
      //    (|| 分支只为兼容还没更新的旧 downloader，新版走不到)
      const active=(d.downloading_count!=null)?d.downloading_count
                   :(d.active||[]).filter(t=>t.status==='downloading').length;
      const waiting=(d.waiting_count!=null)?d.waiting_count
                    :Math.max(0,(d.active_count||0)-active);
      // ⚠️ backlog 里混着「真排队」和「搁置」两种，后者不会自己动 —— 拆开显示
      const stalled=(d.stalled_count!=null)?d.stalled_count:0;
      const backlog=Math.max(0,(d.pending||0)-(d.active_count||0)-stalled);
      setStage('dl', d.paused?'paused':(active>0?'busy':'on'),
        (d.paused?'⏸ ':'')+active+' 下载中'
        +(waiting>0?' · '+waiting+' 等连接':'')
        +(backlog>0?' · 队列 '+fmtCount(backlog):'')
        +(stalled>0?' · ⚠️搁置 '+fmtCount(stalled):''));
      renderThroughput(d.total_speed, true);
    }
    // 搬运
    const md=o.mover;
    if(!md.online){ setStage('mv','off','离线'); }
    else if(md.data){ const d=md.data; const run=d.running_tasks||0; const fail=d.failed_tasks||0;
      setStage('mv', d.paused?'paused':(run>0?'busy':'on'),
        (d.paused?'⏸ ':'')+run+' 搬运中'+(fail>0?' · '+fail+' 失败':'')); }
    // 解压
    const ud=o.unzipper;
    if(!ud.online){ setStage('uz','off','离线'); }
    else if(ud.data){ const d=ud.data;
      const run=Object.keys(d.current_tasks||{}).length; const pend=(d.pending||[]).length;
      setStage('uz', d.paused?'paused':(run>0?'busy':'on'),
        (d.paused?'⏸ ':'')+run+' 解压中'+(pend>0?' · '+pend+' 待确认':''));
      const badge=document.getElementById('badge-inbox');
      badge.textContent=pend; badge.classList.toggle('show',pend>0);
    }
    document.getElementById('updated').textContent='更新于 '+fmtTime(new Date());
    if(activeTab==='home'){ renderHome(o); loadRecent(); }
  }catch(e){ document.getElementById('updated').textContent='更新失败 '+fmtTime(new Date()); }
}

function renderHome(o){
  // 正在下载
  const d=o.downloader.data;
  const dl=document.getElementById('home-downloads');
  const cnt=document.getElementById('home-dl-count');
  if(!o.downloader.online){ dl.innerHTML='<div class="empty">下载模块离线</div>'; cnt.textContent=''; }
  else{
    const _q=(document.getElementById('home-dl-search').value||'').trim().toLowerCase();
    const _match=t=>!_q||((t.filename||t.label||'').toLowerCase().includes(_q));
    const _all=((d&&d.active)||[]).filter(_match);
    const act=_all.filter(t=>['downloading','paused','flood_wait'].includes(t.status));
    const wait=_all.filter(t=>t.status==='waiting');
    // ⚠️ 三个数分清楚（见上面 setStage 那段注释）。
    // 🔴 计数一律用服务端字段，不数列表 —— 列表会被 slim/limit 裁剪。
    //    下面的 act/wait 只用来**渲染条目**，不用来算数。
    const _dl=(d&&d.downloading_count!=null)?d.downloading_count:act.length;
    const _waiting=(d&&d.waiting_count!=null)?d.waiting_count
                   :Math.max(0,(d&&d.active_count||0)-act.length);
    // ⚠️「搁置」= 下过但失败、**没有任何东西会再碰它们**的任务（恢复扫描只在启动时跑一次）。
    //    2026-09-17 之前它们混在「队列」里，看着像在排队，实际躺了一个多月。
    const _stalled=(d&&d.stalled_count!=null)?d.stalled_count:0;
    const _backlog=Math.max(0,(d&&d.pending||0)-(d&&d.active_count||0)-_stalled);
    cnt.textContent=(_dl||_waiting||_backlog||_stalled)
      ?('· '+_dl+' 下载中'
        +(_waiting?(' · '+_waiting+' 等连接'):'')
        +(_backlog?(' · 队列 '+fmtCount(_backlog)):'')
        +(_stalled?(' · ⚠️搁置 '+fmtCount(_stalled)):'')
        +((d&&d.active_truncated)?(' · 仅显示前 '+_all.length+' 条'):''))
      :'';
    let _html = act.length ? act.map(t=>{
      const pct = (typeof t.pct==='number') ? t.pct : (t.total?100*(t.current||0)/t.total:0);
      const paused = t.status==='paused';
      return '<div class="prog-item"><div class="prog-head"><span class="prog-name">'+
        esc(t.filename||t.label||'下载中')+(paused?' <span class="pill wait">已暂停</span>':'')+
        (t.status==='flood_wait'?' <span class="pill wait">限流等待</span>':'')+'</span>'+
        '<span class="prog-meta">'+(t.speed?fmtSpeed(t.speed)+' · ':'')+
        (t.current_mb!=null?t.current_mb.toFixed(0)+' / '+(t.size_mb!=null?t.size_mb.toFixed(0):'?')+' MB':'')+'</span></div>'+
        '<div class="bar"><i style="width:'+Math.min(100,pct).toFixed(1)+'%"></i></div>'+
        '<div class="btn-group" style="margin-top:.4rem">'+
        '<button class="btn sm" data-dl-'+(paused?'resume':'pause')+'="'+esc(t.task_id)+'">'+(paused?'继续':'暂停')+'</button>'+
        '<button class="btn sm danger" data-dl-cancel="'+esc(t.task_id)+'">终止</button></div></div>';
    }).join('') : '<div class="empty">当前没有正在下载的任务</div>';
    if(wait.length){
      _html += '<div class="sub" style="margin:.7rem 0 .25rem;font-weight:600">⏳ 排队中 · '+wait.length+'</div>';
      _html += wait.slice(0,80).map((t,i)=>
        '<div class="queue-item"><span class="q-idx">'+(i+1)+'</span>'+
        '<span class="q-name">'+esc(t.filename||t.label||'?')+'</span>'+
        '<button class="btn sm danger" data-dl-cancel="'+esc(t.task_id)+'">取消</button></div>').join('');
      if(wait.length>80) _html += '<div class="sub">…共 '+wait.length+' 个，仅显示前 80</div>';
    }
    dl.innerHTML=_html;
    dl.querySelectorAll('[data-dl-pause]').forEach(b=>b.onclick=()=>dlTaskAct(b.dataset.dlPause,'pause'));
    dl.querySelectorAll('[data-dl-resume]').forEach(b=>b.onclick=()=>dlTaskAct(b.dataset.dlResume,'resume'));
    dl.querySelectorAll('[data-dl-cancel]').forEach(b=>b.onclick=()=>dlTaskAct(b.dataset.dlCancel,'cancel'));
  }
  // 正在解压
  const u=o.unzipper.data; const uz=document.getElementById('home-unzips');
  const cur=u?Object.values(u.current_tasks||{}):[];
  uz.innerHTML = cur.length ? cur.map(c=>'<div class="prog-item"><div class="prog-head"><span class="prog-name">'+
    esc(c.name||c.archive||'解压中')+'</span><span class="prog-meta">解压中…</span></div></div>').join('')
    : '<div class="empty">当前没有解压任务</div>';
}
async function dlTaskAct(id, act){
  const r=await px('dl','/api/task/'+encodeURIComponent(id)+'/'+act,{method:'POST'});
  toast(r.ok?({pause:'已暂停',resume:'已继续',cancel:'已终止'}[act]):'操作失败',!r.ok);
  pollOverview();
}
let recentItems=[];
async function loadRecent(){
  const [dl,mv,uz]=await Promise.all([
    pxj('dl','/api/history?limit=200'),
    pxj('mv','/api/tasks?limit=100'), pxj('uz','/api/state')]);
  recentItems=[];
  if(dl&&dl.items) dl.items.filter(t=>t.status==='done').slice(0,60).forEach(t=>
    recentItems.push({name:t.filename||t.label,stage:'下载',cls:'done',t:t.finished_at}));
  if(mv&&mv.items) mv.items.filter(t=>t.status==='done').slice(0,60).forEach(t=>
    recentItems.push({name:base(t.source),stage:'搬运',cls:'done',t:t.completed_at}));
  if(uz&&uz.history) uz.history.filter(h=>h.status==='done').slice(-60).reverse().forEach(h=>
    recentItems.push({name:h.name,stage:'解压',cls:'done',t:h.finished_at}));
  recentItems.sort((a,b)=>new Date(b.t||0)-new Date(a.t||0));
  renderRecent();
}
function renderRecent(){
  const box=document.getElementById('home-recent');
  const q=(document.getElementById('recent-search').value||'').trim().toLowerCase();
  const st=document.getElementById('recent-stage').value;
  const filtered=(q||st!=='all');
  let items=recentItems.filter(i=>(st==='all'||i.stage===st)&&(!q||(i.name||'').toLowerCase().includes(q)));
  items=items.slice(0, filtered?40:10);   // 默认精简 10 条；搜索/筛选时放宽
  box.innerHTML = items.length ? items.map(i=>'<div class="row"><span class="pill '+(i.stage==='下载'?'stage-dl':'run')+'">'+i.stage+
    '</span><div class="grow"><div class="name">'+esc(i.name)+'</div><div class="sub">'+ago(i.t)+
    '</div></div><span class="pill '+i.cls+'">完成</span></div>').join('')
    : '<div class="empty">'+(filtered?'没有匹配的记录':'暂无记录')+'</div>';
}

// ═══════════ 频道（列表来自 dl /api/status.watched；加监听走 搜索→POST {id,name}） ═══════════
let chWatched={};
let chPaused=false, chExemptPaused=false;   // 供「按监听状态」排序判断某频道此刻是否在收
let chSortDesc=true;
async function loadChannels(){
  // ⚠️ 走 slim overview，别直接调 dl 的 /api/status —— 后者是全量状态（队列达到数万条时
  // 序列化出 22MB），下载器忙的时候 30 秒都返回不了，反代直接 504、频道页变空白。
  // slim overview 只有 ~45KB，watched/paused/exempt_paused 都在里面（手机 App 也走这条）。
  const ov = await req('/api/overview?slim=1').then(r=>r.ok?r.json():null).catch(()=>null);
  const s = ov && ov.downloader && ov.downloader.data;   // 模块超时时这里是 null，下面全用可选取值
  chWatched=(s&&s.watched)||{};
  // 按钮直接显示当前状态（开=正在暂停收取），点一下切换
  chPaused = !!(s && s.paused); chExemptPaused = !!(s && s.exempt_paused);
  setPauseBtn('ch-pause-btn',   '全局暂停', chPaused);
  setPauseBtn('ch-expause-btn', '例外暂停', chExemptPaused);
  setPauseBtn('ch-savedpause-btn', '收藏暂停', !!(s && s.saved_paused));
  renderChannels();
}
function renderChannels(){
  const box=document.getElementById('ch-list');
  const w=chWatched;
  const q=(document.getElementById('ch-filter').value||'').trim().toLowerCase();
  const kind=document.getElementById('ch-kind').value;
  const sort=document.getElementById('ch-sort').value;
  const total=Object.keys(w).length;
  document.getElementById('ch-count').textContent = total?('· '+total):'';
  let keys=Object.keys(w).filter(cid=>{
    const info=w[cid]||{};
    if(kind==='exempt' && !info.exempt) return false;
    if(kind==='normal' && info.exempt) return false;
    if(kind==='fav' && !info.favorite) return false;
    if(q && !((info.name||'').toLowerCase().includes(q) || String(cid).includes(q))) return false;
    return true;
  });
  // 某频道此刻是否在收：例外频道看例外暂停，其余看全局暂停
  const isOn = info => (info.exempt ? !chExemptPaused : !chPaused);
  keys.sort((a,b)=>{
    const A=w[a]||{}, B=w[b]||{};
    const byName = (A.name||a).localeCompare(B.name||b,'zh');
    let r;
    switch(sort){
      case 'tasks':  r = (A.task_count||0)-(B.task_count||0); break;
      case 'added':  r = String(A.watched_since||'').localeCompare(String(B.watched_since||'')); break;
      case 'exempt': r = (A.exempt?1:0)-(B.exempt?1:0); break;
      case 'status': r = (isOn(A)?1:0)-(isOn(B)?1:0); break;
      case 'fav':    r = (A.favorite?1:0)-(B.favorite?1:0); break;
      default:       r = byName;
    }
    if(r === 0) r = byName;                       // 同值时按名称稳定排列
    const dir = chSortDesc ? -r : r;
    // ⭐ 喜爱恒置顶：不受升降序影响，否则「升序」会把喜爱的埋到最底下
    const favDiff = (B.favorite?1:0)-(A.favorite?1:0);
    return favDiff !== 0 ? favDiff : dir;
  });
  if(!keys.length){ box.innerHTML='<div class="empty">'+(total?'没有匹配的频道':'还没有监听任何频道，用上面的搜索添加')+'</div>'; return; }
  box.innerHTML=keys.map(cid=>{
    const info=w[cid]||{}; const name=info.name||cid;
    return '<div class="row"><div class="grow"><div class="name">'+(info.favorite?'⭐ ':'')+esc(name)+
      (info.exempt?' <span class="pill wait">例外频道</span>':'')+'</div>'+
      (isOn(info)?'':' <span class="pill fail">不收</span>')+'</div>'+
      '<div class="sub">ID '+esc(cid)+' · 任务 '+(info.task_count||0)+
        (info.watched_since?(' · 添加 '+String(info.watched_since).slice(0,10)):'')+'</div></div>'+
      '<div class="btn-group">'+
      '<button class="btn sm" data-fav="'+esc(cid)+'" data-favon="'+(info.favorite?1:0)+'">'+
      (info.favorite?'★ 取消喜爱':'☆ 喜爱')+'</button>'+
      '<button class="btn sm" data-exempt="'+esc(cid)+'" data-ex="'+(info.exempt?1:0)+'">'+
      (info.exempt?'取消例外':'设为例外')+'</button>'+
      '<button class="btn sm danger" data-unwatch="'+esc(cid)+'">取消监听</button></div></div>';
  }).join('');
  box.querySelectorAll('[data-unwatch]').forEach(b=>b.onclick=()=>unwatch(b.dataset.unwatch));
  box.querySelectorAll('[data-fav]').forEach(b=>b.onclick=async()=>{
    const on = b.dataset.favon==='1';
    const r=await px('dl','/api/watch/'+encodeURIComponent(b.dataset.fav)+'/favorite',
      {method:'POST',body:JSON.stringify({favorite:!on})});
    toast(r.ok?(on?'已取消喜爱':'已标记喜爱'):'操作失败',!r.ok); loadChannels();
  });
  box.querySelectorAll('[data-exempt]').forEach(b=>b.onclick=async()=>{
    const r=await px('dl','/api/watch/'+encodeURIComponent(b.dataset.exempt)+'/exempt',
      {method:'POST',body:JSON.stringify({exempt:b.dataset.ex!=='1'})});
    toast(r.ok?'已更新':'操作失败',!r.ok); loadChannels();
  });
}
async function unwatch(cid){
  const r=await px('dl','/api/watch/'+encodeURIComponent(cid),{method:'DELETE'});
  toast(r.ok?'已取消监听':'操作失败',!r.ok); if(r.ok) loadChannels();
}
let chResults=[];
async function chSearch(){
  const q=document.getElementById('ch-search-input').value.trim();
  const box=document.getElementById('ch-search-results');
  if(!q){ box.innerHTML=''; return; }
  box.innerHTML='<div class="empty">搜索中…</div>';
  const r=await px('dl','/api/search?q='+encodeURIComponent(q));
  if(r.status===403){ box.innerHTML='<div class="empty">需先登录 Telegram（打开下载页 :8091 完成验证码登录）</div>'; return; }
  chResults=await r.json().catch(()=>[]);
  if(!Array.isArray(chResults)||!chResults.length){ box.innerHTML='<div class="empty">没有匹配的对话</div>'; return; }
  box.innerHTML=chResults.map((it,i)=>'<div class="row"><div class="grow"><div class="name">'+esc(it.name)+
    '</div><div class="sub">ID '+esc(it.id)+'</div></div>'+
    '<button class="btn sm primary" data-add="'+i+'">添加监听</button></div>').join('');
  box.querySelectorAll('[data-add]').forEach(b=>b.onclick=async()=>{
    const it=chResults[+b.dataset.add]; if(!it) return;
    const r=await px('dl','/api/watch',{method:'POST',body:JSON.stringify({id:it.id,name:it.name})});
    if(r.ok){ const d=await r.json().catch(()=>({}));
      toast(d.already_watched?'已在监听中':'已添加监听'); loadChannels(); }
    else { const e=await r.json().catch(()=>({})); toast('添加失败：'+(e.error||r.status),true); }
  });
}
document.getElementById('ch-search-btn').onclick=chSearch;
document.getElementById('ch-search-input').addEventListener('keydown',e=>{ if(e.key==='Enter') chSearch(); });
// 暂停按钮：文字自带状态（「全局暂停:开」= 正在暂停），data-on 记真值供点击时取反
function setPauseBtn(id, label, on){
  const b=document.getElementById(id); if(!b) return;
  b.textContent = label + ':' + (on?'开':'关');
  b.dataset.on = on ? '1' : '0';
  b.classList.toggle('primary', on);   // 开 = 高亮，一眼看出正在拦
}
async function togglePause(id, label, pausePath, resumePath){
  const b=document.getElementById(id);
  const on = b.dataset.on === '1';
  const r = await px('dl', on ? resumePath : pausePath, {method:'POST'});
  toast(r.ok ? `${label}已${on?'关闭':'开启'}` : '操作失败', !r.ok);
  loadChannels();
}
document.getElementById('ch-pause-btn').onclick = () =>
  togglePause('ch-pause-btn', '全局暂停', '/api/pause', '/api/resume');
document.getElementById('ch-expause-btn').onclick = () =>
  togglePause('ch-expause-btn', '例外暂停', '/api/exempt-pause', '/api/exempt-resume');
document.getElementById('ch-savedpause-btn').onclick = () =>
  togglePause('ch-savedpause-btn', '收藏暂停', '/api/saved-pause', '/api/saved-resume');

// ═══════════ 任务（合并 mover + unzipper） ═══════════
let taskFilter='all', taskStage='all';
document.querySelectorAll('#task-filters .chip').forEach(c=>c.onclick=()=>{
  taskFilter=c.dataset.f;
  document.querySelectorAll('#task-filters .chip').forEach(x=>x.classList.toggle('active',x===c));
  renderTaskList();
});
document.querySelectorAll('#task-stage-filters .chip').forEach(c=>c.onclick=()=>{
  taskStage=c.dataset.s;
  document.querySelectorAll('#task-stage-filters .chip').forEach(x=>x.classList.toggle('active',x===c));
  renderTaskList();
});
function normStatus(st){
  if(['done','extracted'].includes(st)) return 'done';
  if(['failed','error','timeout','partial','cancelled','extract_failed','move_failed'].includes(st)) return 'failed';
  if(['downloading','copying','pending','running','extracting','moving','waiting','flood_wait'].includes(st)) return 'active';
  return 'active';
}
let taskItems=[];
function fmtSize(mb){
  if(mb==null||isNaN(mb)||mb<=0) return '';
  return mb>=1024?(mb/1024).toFixed(2)+' GB':(mb>=1?mb.toFixed(0)+' MB':(mb*1024).toFixed(0)+' KB');
}
function ts(t){ // 统一时间戳：unix秒 / unix毫秒 / ISO 字符串 → 毫秒数（用于排序）
  if(t==null) return 0;
  if(typeof t==='number') return t<1e12?t*1000:t;
  const d=new Date(t).getTime(); return isNaN(d)?0:d;
}
async function loadTasks(){
  // 注：downloader 的 filter_status 过滤的是 extract_status，不是下载状态；这里取全量在前端按 status 筛
  const [dl,dls,mv,uz]=await Promise.all([
    pxj('dl','/api/history?limit=200'), pxj('dl','/api/state'),
    pxj('mv','/api/tasks?limit=100'), pxj('uz','/api/state')]);
  taskItems=[];
  // 进行中/排队中的下载（重试后任务会出现在这里，显示为"进行中"）
  if(dls&&dls.active) dls.active.forEach(t=>taskItems.push({
    stage:'下载', scls:'stage-dl', name:t.filename||t.label, sub:t.dir||'', status:t.status,
    t:t.queued_at||t.started_at, id:t.task_id, mod:'dl', err:'',
    sz:fmtSize(t.size_mb), paths:t.path?[t.path]:[]}));
  if(dl&&dl.items) dl.items.forEach(t=>taskItems.push({
    stage:'下载', scls:'stage-dl', name:t.filename||t.label, sub:t.dir||t.path, status:t.status,
    t:t.finished_at||t.queued_at, id:t.task_id, mod:'dl', err:t.error_msg,
    sz:fmtSize(t.size_mb), paths:t.path?[t.path]:(t.dir?[t.dir]:[])}));
  if(mv&&mv.items) mv.items.forEach(t=>taskItems.push({
    stage:'搬运', scls:'run', name:base(t.source), sub:'→ '+t.target, status:t.status,
    t:t.completed_at||t.created_at, id:t.task_id, mod:'mv', err:t.error,
    sz:'', paths:['源：'+t.source,'目标：'+t.target+'/'+base(t.source)]}));
  if(uz&&uz.history) uz.history.slice().reverse().forEach(h=>taskItems.push({
    stage:'解压', scls:'done', name:h.name, sub:h.out_dir||'', status:h.status,
    t:h.finished_at||h.started_at, id:h.name, mod:'uz', err:h.error,
    sz:'', paths:h.out_dir?['输出：'+h.out_dir]:[]}));
  if(uz&&uz.current_tasks) Object.values(uz.current_tasks).forEach(c=>taskItems.push({
    stage:'解压', scls:'done', name:c.name, status:'extracting', t:c.started_at}));
  renderTaskList();
}
function renderTaskList(){
  const box=document.getElementById('tasks-list');
  const q=(document.getElementById('task-search').value||'').trim().toLowerCase();
  const sort=document.getElementById('task-sort').value;
  let items=taskItems.filter(i=>(taskStage==='all'||i.stage===taskStage)
                     && (taskFilter==='all'||normStatus(i.status)===taskFilter)
                     && (!q||((i.name||'')+' '+(i.sub||'')+' '+(i.err||'')).toLowerCase().includes(q)));
  if(sort==='name') items.sort((a,b)=>(a.name||'').localeCompare(b.name||'','zh'));
  else items.sort((a,b)=>{const d=ts(b.t)-ts(a.t); return sort==='tasc'?-d:d;});
  if(!items.length){ box.innerHTML='<div class="empty">没有符合条件的任务</div>'; return; }
  const label={done:['done','完成'],failed:['fail','失败'],active:['run','进行中']};
  box.innerHTML=items.slice(0,200).map((i,idx)=>{
    const p=label[normStatus(i.status)];
    const canRetry = normStatus(i.status)==='failed' && (i.mod==='dl'||i.mod==='mv'||i.mod==='uz') && i.id;
    const hasPaths = i.paths && i.paths.length;
    return '<div class="row"><span class="pill '+i.scls+'">'+i.stage+'</span>'+
      '<div class="grow"><div class="name">'+esc(i.name)+
        (i.sz?' <span class="dim" style="font-size:.78rem">· '+i.sz+'</span>':'')+'</div>'+
      '<div class="sub">'+(i.err?('⚠ '+esc(i.err)):esc(i.sub||''))+' · '+ago(i.t)+'</div>'+
      (hasPaths?'<div class="paths" id="paths-'+idx+'">'+i.paths.map(pp=>'<div>'+esc(pp)+'</div>').join('')+'</div>':'')+
      '</div>'+
      '<span class="pill '+p[0]+'">'+p[1]+'</span>'+
      (hasPaths?'<button class="btn sm" data-exp="'+idx+'" title="显示完整路径">📂</button>':'')+
      (canRetry?'<button class="btn sm" data-retry="'+idx+'">重试</button>':'')+'</div>';
  }).join('');
  box.querySelectorAll('[data-exp]').forEach(b=>b.onclick=()=>{
    document.getElementById('paths-'+b.dataset.exp).classList.toggle('show');
  });
  box.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{
    const i=items[+b.dataset.retry];
    let r;
    if(i.mod==='dl') r=await px('dl','/api/retry',{method:'POST',body:JSON.stringify({task_id:i.id})});
    else if(i.mod==='uz') r=await px('uz','/api/retry',{method:'POST',body:JSON.stringify({name:i.id})});
    else r=await px('mv','/api/tasks/'+encodeURIComponent(i.id)+'/retry',{method:'POST'});
    toast(r.ok?'已重试':'重试失败',!r.ok); loadTasks();
  });
}
document.getElementById('tasks-clear-done').onclick=async()=>{
  if(!confirm('删除三个阶段的所有「已完成」记录？（只删记录，不删文件）')) return;
  await Promise.all([
    px('dl','/api/history/done',{method:'DELETE'}),
    px('mv','/api/tasks/clear',{method:'POST',body:JSON.stringify({statuses:['done']})}),
    px('uz','/api/history',{method:'DELETE',body:JSON.stringify({status:['done']})}),
  ]);
  toast('已删除完成记录'); loadTasks();
};
document.getElementById('tasks-clear-failed').onclick=async()=>{
  if(!confirm('删除三个阶段的所有「失败」记录？（只删记录，不删文件；删除后这些任务将无法从列表重试）')) return;
  await Promise.all([
    px('dl','/api/history/failed',{method:'DELETE'}),
    px('mv','/api/tasks/clear',{method:'POST',body:JSON.stringify({statuses:['failed']})}),
    px('uz','/api/history',{method:'DELETE',body:JSON.stringify({status:['failed','partial','cancelled']})}),
  ]);
  toast('已删除失败记录'); loadTasks();
};
document.getElementById('tasks-retry-dl').onclick=async(ev)=>{
  const btn=ev.currentTarget;
  if(!confirm('重试所有失败的下载任务？')) return;
  btn.disabled=true;
  try{
    const rd=await px('dl','/api/retry-all-failed',{method:'POST'});
    const d=await rd.json().catch(()=>({}));
    toast(rd.ok?(d.queued?('已重试 '+d.queued+' 个下载'+(d.skipped&&d.skipped.length?('，跳过 '+d.skipped.length):'')):'没有可重试的失败下载'):'重试失败',!rd.ok);
  }catch(e){ toast('重试失败',true); }
  btn.disabled=false; loadTasks();
};
document.getElementById('tasks-retry-mv').onclick=async(ev)=>{
  const btn=ev.currentTarget;
  if(!confirm('重试所有失败的搬运任务？')) return;
  btn.disabled=true; let n=0;
  try{
    const mv=await pxj('mv','/api/tasks?limit=300');
    const mf=(mv&&mv.items||[]).filter(t=>t.status==='failed');
    for(const t of mf){ const r=await px('mv','/api/tasks/'+encodeURIComponent(t.task_id)+'/retry',{method:'POST'}); if(r.ok) n++; }
    toast(n?('已重试 '+n+' 个搬运'):'没有可重试的失败搬运');
  }catch(e){ toast('重试失败',true); }
  btn.disabled=false; loadTasks();
};
document.getElementById('tasks-retry-uz').onclick=async(ev)=>{
  const btn=ev.currentTarget;
  if(!confirm('重试所有失败的解压任务？')) return;
  btn.disabled=true; let n=0;
  try{
    const uz=await pxj('uz','/api/state');
    const uf=(uz&&uz.history||[]).filter(h=>['failed','partial','cancelled'].includes(h.status));
    for(const h of uf){ const r=await px('uz','/api/retry',{method:'POST',body:JSON.stringify({name:h.name})}); if(r.ok) n++; }
    toast(n?('已重试 '+n+' 个解压'):'没有可重试的失败解压');
  }catch(e){ toast('重试失败',true); }
  btn.disabled=false; loadTasks();
};

// ═══════════ 待办（downloader toasts + unzipper pending） ═══════════
let inboxData={toasts:[],pend:[]};
async function loadInbox(){
  const [ts,uz]=await Promise.all([pxj('dl','/api/toasts'), pxj('uz','/api/state')]);
  inboxData={toasts:(ts&&ts.toasts)||[], pend:(uz&&uz.pending)||[]};
  renderInbox();
}
function renderInbox(){
  const box=document.getElementById('inbox-list');
  const q=(document.getElementById('inbox-search').value||'').trim().toLowerCase();
  const kind=document.getElementById('inbox-kind').value;
  let html='';
  const toasts=kind==='uz'?[]:inboxData.toasts.filter(t=>!q||((t.filename||'')+' '+(t.matched_filename||'')+' '+(t.source_label||'')).toLowerCase().includes(q));
  const pend=kind==='dl'?[]:inboxData.pend.filter(p=>!q||(p.name||'').toLowerCase().includes(q));
  toasts.forEach(t=>{
    const finish = t.trigger_source==='finish';
    const dup = t.matched_filename ? ('与已有文件重复：'+esc(t.matched_filename)) : '重复文件';
    const btns = finish
      ? '<button class="btn sm primary" data-t="keep" data-id="'+esc(t.toast_id)+'">保留</button>'+
        '<button class="btn sm" data-t="open-matched" data-id="'+esc(t.toast_id)+'">查看重复</button>'+
        '<button class="btn sm danger" data-t="skip" data-id="'+esc(t.toast_id)+'">跳过</button>'
      : '<button class="btn sm primary" data-t="download" data-id="'+esc(t.toast_id)+'">直接下载</button>'+
        '<button class="btn sm" data-t="queue" data-id="'+esc(t.toast_id)+'">加入队列</button>'+
        '<button class="btn sm danger" data-t="skip" data-id="'+esc(t.toast_id)+'">跳过下载</button>';
    html+='<div class="row"><span class="pill wait">下载</span><div class="grow"><div class="name">'+
      esc(t.filename||'待确认')+(t.size_mb!=null?' · '+t.size_mb.toFixed(0)+'MB':'')+'</div>'+
      '<div class="sub">'+dup+(t.source_label?' · '+esc(t.source_label):'')+'</div></div>'+
      '<div class="btn-group">'+btns+'</div></div>';
  });
  pend.forEach(p=>{
    const id4=String(p.id).padStart(4,'0');
    const kindTxt = p.kind==='folder' ? '文件夹' : (p.kind==='multipart'?'多卷压缩包':'压缩包');
    html+='<div class="row"><span class="pill wait">解压</span><div class="grow"><div class="name">'+
      esc(p.name)+'</div><div class="sub">'+kindTxt+' · 需要你确认解压</div></div>'+
      '<button class="btn sm primary" data-uz-confirm="'+id4+'">确认解压</button></div>';
  });
  const _filtered=(q||kind!=='all')&&(inboxData.toasts.length+inboxData.pend.length>0);
  box.innerHTML = html || '<div class="empty">'+(_filtered?'没有匹配的待办':'✓ 没有需要确认的事项')+'</div>';
  box.querySelectorAll('[data-t]').forEach(b=>b.onclick=async()=>{
    const r=await px('dl','/api/toast/'+encodeURIComponent(b.dataset.id)+'/'+b.dataset.t,{method:'POST'});
    toast(r.ok?'已处理':'操作失败',!r.ok); loadInbox();
  });
  box.querySelectorAll('[data-uz-confirm]').forEach(b=>b.onclick=async()=>{
    const r=await px('uz','/api/confirm/'+encodeURIComponent(b.dataset.uzConfirm),{method:'POST'});
    toast(r.ok?'已确认解压':'操作失败',!r.ok); loadInbox();
  });
}

// ═══════════ 设置（同 /api/config，与旧设置页一致） ═══════════
const SK=['DATA_ROOT','DOWNLOAD_DIR','WATCH_PATH','OUTPUT_PATH','MAX_TOTAL_CONNECTIONS',
  'MAX_CONCURRENT_TASKS','MOVER_MAX_CONCURRENT','DOWNLOAD_TIMEOUT','AUTO_MOVE','LOG_LEVEL','RESTART_MODE'];
const PATHK=['DATA_ROOT','DOWNLOAD_DIR','WATCH_PATH','OUTPUT_PATH'];
let sInit={};
async function loadSettings(){
  const r=await req('/api/config'); if(!r.ok) return; const cfg=await r.json();
  document.getElementById('env-path').textContent=cfg.env_file;
  document.getElementById('docker-banner').className='banner'+(cfg.docker?' show':'');
  sInit={};
  SK.forEach(k=>{ const el=document.getElementById('f-'+k); if(!el) return;
    const v=(cfg.values&&cfg.values[k])||''; el.value=v; sInit[k]=v;
    if(PATHK.includes(k)) el.disabled=!!cfg.docker; });
  ['DOWNLOAD_DIR','WATCH_PATH','OUTPUT_PATH'].forEach(k=>{
    const eff=document.getElementById('eff-'+k);
    if(eff&&cfg.effective_dirs) eff.textContent='当前生效：'+cfg.effective_dirs[k]; });
  loadServices();
  loadPasswords();
  loadAutostart();
  loadBranding();
}

// ── 页面标题（/api/branding） ──
async function loadBranding(){
  const r=await req('/api/branding'); if(!r.ok) return; const d=await r.json();
  document.getElementById('brand-input').value=d.display_name||'';
  document.getElementById('brand-hide').checked=!!d.hide_name;
  document.getElementById('brand-input').disabled=!!d.hide_name;
}
document.getElementById('brand-hide').onchange=e=>{ document.getElementById('brand-input').disabled=e.target.checked; };
document.getElementById('brand-save').onclick=async()=>{
  const msg=document.getElementById('brand-msg');
  try{
    const r=await req('/api/branding',{method:'POST',body:JSON.stringify({
      display_name:document.getElementById('brand-input').value,
      hide_name:document.getElementById('brand-hide').checked})});
    const d=await r.json().catch(()=>({}));
    if(r.ok&&d.ok){ msg.className='msg ok'; msg.textContent='已保存'; pollOverview(); }
    else { msg.className='msg err'; msg.textContent=d.error||'保存失败'; }
  }catch(e){ msg.className='msg err'; msg.textContent='请求失败：'+e.message; }
};

// ── 开机自动启动（/api/autostart → tools/autostart.py） ──
// Docker 部署由 Docker 负责，只显示说明；原生 macOS / Linux 可以开关；Windows 原生不支持。
let autostartOn=false;
async function loadAutostart(){
  const st=document.getElementById('autostart-state'), btn=document.getElementById('autostart-btn');
  const r=await req('/api/autostart'); const d=await r.json().catch(()=>({}));
  document.getElementById('autostart-note').textContent=d.note||'';
  if(!r.ok){ st.textContent='读取失败'; btn.style.display='none'; return; }
  autostartOn=!!d.enabled;
  st.innerHTML=d.how==='docker' ? '<span style="color:#2E9E5B">✅ 由 Docker 负责</span>'
    : (d.enabled ? '<span style="color:#2E9E5B">✅ 已开启</span>' : '<span style="color:#888">⏹ 未开启</span>')
      + (d.how ? ' <span class="dim">（'+d.how+'）</span>' : '');
  if(d.supported){ btn.style.display=''; btn.textContent=d.enabled?'关闭开机自启':'开启开机自启'; }
  else btn.style.display='none';
}
document.getElementById('autostart-btn').onclick=async()=>{
  const btn=document.getElementById('autostart-btn'); btn.disabled=true;
  try{
    const r=await req('/api/autostart',{method:'POST',body:JSON.stringify({enabled:!autostartOn})});
    const d=await r.json().catch(()=>({}));
    if(r.ok&&d.ok) toast(d.enabled?'✅ 已开启开机自动启动':'已关闭开机自动启动');
    else toast('❌ 设置失败：'+(d.error||d.note||r.statusText), true);
  }catch(e){ toast('❌ 请求失败：'+e.message, true); }
  finally{ btn.disabled=false; loadAutostart(); }
};

// ── 服务启停面板（/api/services） ──
// 只有 Docker 部署有：dashboard → control 服务 → Docker，只能启停本项目的 downloader / mover / unzipper。
// 原生部署后端返回 supported=false，整张卡片隐藏（原生用 ./start.sh / ./stop.sh）。
// 状态每 3s 自动刷（仅当当前在 settings 标签页时；别的时候刷了没人看）。
const SVC_LABELS={downloader:'下载 Downloader',mover:'搬运 Mover',unzipper:'解压 Unzipper',dashboard:'仪表盘 Dashboard'};
// 服务状态直接内联颜色（不复用 CSS 类）——.ok/.err/.warn 都是消息 .msg 里限定的
const SVC_STATE_STYLE={
  running:{color:'#2E9E5B', text:'✅ 运行中'},
  starting:{color:'#ffb020', text:'⏳ 重启中'},
  stopped:{color:'#ef5350', text:'⏹ 已停止'},
  missing:{color:'#888', text:'— 容器不存在'},
  unknown:{color:'#ffb020', text:'❓ 未知'}
};
const SVC_ACTION_WORD={start:'启动',stop:'停止',restart:'重启'};
async function loadServices(){
  const card=document.getElementById('svc-card');
  const r=await req('/api/services');
  const d=await r.json().catch(()=>({}));
  if(d.supported===false){ card.style.display='none'; return; }
  card.style.display='';
  if(!r.ok || !d.ok){
    document.getElementById('svc-list').innerHTML='<div class="empty">读取失败：'+(d.message||r.statusText)+'</div>'; return;
  }
  const rows=(d.services||[]).map(s=>{
    const st=SVC_STATE_STYLE[s.state]||SVC_STATE_STYLE.unknown;
    const stateSpan='<span style="color:'+st.color+'">'+st.text+'</span>';
    const detail=s.status_text?(' <span class="dim">'+s.status_text+'</span>'):'';
    let btns='';
    if(s.controllable){
      const running=(s.state==='running');
      btns='<button class="btn btn-sm svc-act" data-action="start" data-name="'+s.name+'"'+(running?' disabled':'')+'>▶ 启动</button>'
         +' <button class="btn btn-sm svc-act" data-action="restart" data-name="'+s.name+'"'+(running?'':' disabled')+'>↻ 重启</button>'
         +' <button class="btn btn-sm svc-act" data-action="stop" data-name="'+s.name+'"'+(running?'':' disabled')+' style="color:#ef5350">⏹ 停止</button>';
    } else if(s.name==='dashboard'){
      btns='<span class="dim" title="dashboard 就是本页面，从这里停会立刻失去连接">只读</span>';
    }
    return '<div class="row" style="justify-content:space-between;padding:.4rem 0;border-bottom:1px solid #222">'
      +'<div><b>'+(SVC_LABELS[s.name]||s.name)+'</b> '+stateSpan+detail+'</div>'
      +'<div>'+btns+'</div></div>';
  }).join('');
  document.getElementById('svc-list').innerHTML=rows||'<div class="empty">—</div>';
}
document.getElementById('svc-list').addEventListener('click', async (e)=>{
  const b=e.target.closest('button.svc-act'); if(!b) return;
  const name=b.dataset.name, action=b.dataset.action;
  const label=SVC_LABELS[name]||name, word=SVC_ACTION_WORD[action]||action;
  if(action==='stop'){
    // ⚠️ JS 字符串里的换行必须转义 \\n（Python 会把裸 \\n 变成真换行，JS 就语法错误了）
    if(!confirm('确定停止 '+label+' ？\\n\\n它会一直停着，直到你再点「启动」。')) return;
  }
  b.disabled=true; const orig=b.textContent; b.textContent='…';
  try{
    const r=await req('/api/services/'+encodeURIComponent(name)+'/'+action, {method:'POST'});
    const d=await r.json().catch(()=>({message:'解析失败'}));
    if(r.ok && d.ok){ toast('✅ '+(d.message||label+' 已'+word)); }
    else { toast('❌ '+label+' '+word+'失败：'+(d.message||r.statusText), true); }
  }catch(err){ toast('❌ 请求失败：'+err.message, true); }
  finally{ b.textContent=orig; loadServices(); }
});
// 只在 settings 标签下轮询，别的标签下浪费请求
setInterval(()=>{ if(activeTab==='settings') loadServices(); }, 3000);

// ── 解压密码库（uz /api/passwords） ──
let pwCache=[];
async function loadPasswords(){
  const d=await pxj('uz','/api/passwords');
  pwCache=(d&&d.passwords)||[];
  renderPasswords();
}
function renderPasswords(){
  const box=document.getElementById('pw-list');
  const q=(document.getElementById('pw-search').value||'').trim().toLowerCase();
  document.getElementById('pw-count').textContent = pwCache.length?('· '+pwCache.length+' 个'):'';
  const view=pwCache.map((p,i)=>({p,i})).filter(o=>!q||o.p.toLowerCase().includes(q));
  box.innerHTML = view.length ? view.map(o=>'<div class="row">'+
    '<span class="dim" style="width:1.6rem;text-align:right">'+(o.i+1)+'</span>'+
    '<div class="grow"><div class="name" style="font-family:ui-monospace,monospace">'+esc(o.p)+'</div></div>'+
    '<button class="btn sm danger" data-delpw="'+o.i+'">删除</button></div>').join('')
    : '<div class="empty">'+(pwCache.length?'没有匹配的密码':'还没有密码。解压加密压缩包时会按顺序尝试这里的密码')+'</div>';
  box.querySelectorAll('[data-delpw]').forEach(b=>b.onclick=()=>delPassword(pwCache[+b.dataset.delpw]));
}
async function addPassword(){
  const el=document.getElementById('pw-input'); const v=el.value;
  if(!v.trim()) return;
  const r=await px('uz','/api/passwords',{method:'POST',body:JSON.stringify({password:v})});
  if(r.ok){ toast('已添加密码'); el.value=''; loadPasswords(); }
  else { const e=await r.json().catch(()=>({})); toast(r.status===409?'该密码已存在':('添加失败：'+(e.error||r.status)),true); }
}
async function delPassword(p){
  const r=await px('uz','/api/passwords',{method:'DELETE',body:JSON.stringify({password:p})});
  toast(r.ok?'已删除':'删除失败',!r.ok); if(r.ok) loadPasswords();
}
document.getElementById('pw-add-btn').onclick=addPassword;
document.getElementById('pw-input').addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();addPassword();} });
document.getElementById('save-btn').onclick=async()=>{
  const btn=document.getElementById('save-btn'), msg=document.getElementById('save-msg');
  const upd={};
  SK.forEach(k=>{ const el=document.getElementById('f-'+k); if(!el||el.disabled) return;
    if(el.value.trim()!==(sInit[k]||'').trim()) upd[k]=el.value.trim(); });
  if(!Object.keys(upd).length){ msg.textContent='没有改动'; msg.className='msg'; return; }
  btn.disabled=true; msg.textContent='保存中…'; msg.className='msg';
  try{
    const r=await req('/api/config',{method:'POST',body:JSON.stringify(upd)});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){ msg.textContent='✗ '+(d.error||('HTTP '+r.status)); msg.className='msg err'; }
    else{ msg.innerHTML='✓ 已保存（'+d.saved.join(', ')+'），重启后生效：<code>'+d.restart_hint+'</code>';
      msg.className='msg ok'; d.saved.forEach(k=>sInit[k]=upd[k]); }
  }catch(e){ msg.textContent='✗ '+e; msg.className='msg err'; }
  finally{ btn.disabled=false; }
};

// ═══════════ 列表工具栏事件（搜索/排序/筛选 → 前端即时过滤，不重复请求） ═══════════
document.getElementById('home-dl-search').oninput=()=>{ if(lastO) renderHome(lastO); };
document.getElementById('recent-search').oninput=renderRecent;
document.getElementById('recent-stage').onchange=renderRecent;
document.getElementById('ch-filter').oninput=renderChannels;
document.getElementById('ch-kind').onchange=renderChannels;
document.getElementById('ch-sort').onchange=renderChannels;
document.getElementById('ch-sort-dir').onclick=()=>{
  chSortDesc=!chSortDesc;
  document.getElementById('ch-sort-dir').textContent = chSortDesc?'↓ 降序':'↑ 升序';
  renderChannels();
};
document.getElementById('task-search').oninput=renderTaskList;
document.getElementById('task-sort').onchange=renderTaskList;
document.getElementById('inbox-search').oninput=renderInbox;
document.getElementById('inbox-kind').onchange=renderInbox;
document.getElementById('pw-search').oninput=renderPasswords;

// ═══════════ 启动 ═══════════
pollOverview();
setInterval(pollOverview, 3000);
</script>
</body>
</html>
"""
