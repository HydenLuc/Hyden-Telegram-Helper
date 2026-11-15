# SPDX-License-Identifier: AGPL-3.0-or-later
WEB_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Userbot Monitor</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d0d0d;color:#e0e0e0;padding:20px 24px 60px}
h1{color:#4fc3f7;margin-bottom:24px;font-size:1.3rem;font-weight:600}
h2{color:#81d4fa;font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
   margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e1e1e}
section{margin-bottom:32px}
input{background:#161616;border:1px solid #2a2a2a;border-radius:6px;padding:8px 12px;
      color:#e0e0e0;font-size:.9rem;outline:none;transition:border .2s}
input:focus{border-color:#4fc3f7}
.btn{background:#1565c0;color:#fff;border:none;border-radius:6px;padding:8px 16px;
     font-size:.85rem;cursor:pointer;transition:background .2s;white-space:nowrap}
.btn:hover{background:#1976d2}
.btn-sm{padding:4px 10px;font-size:.75rem}
.btn-danger{background:#b71c1c}.btn-danger:hover{background:#c62828}
.row{display:flex;gap:8px;align-items:center;margin-bottom:12px}
/* Download cards */
.card{background:#161616;border:1px solid #1e1e1e;border-radius:8px;padding:14px 16px;margin-bottom:10px}
.card-lbl{font-size:.75rem;color:#555;margin-bottom:3px}
.card-fn{font-weight:600;margin-bottom:10px;word-break:break-all}
.bar-bg{background:#222;border-radius:3px;height:5px;margin-bottom:6px}
.bar-fill{height:100%;border-radius:3px;background:#4fc3f7;transition:width .4s}
.bar-fill.done{background:#66bb6a}.bar-fill.error,.bar-fill.timeout{background:#ef5350}
.card-meta{font-size:.75rem;color:#666;display:flex;justify-content:space-between}
/* Table */
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;color:#555;font-weight:500;padding:6px 10px;border-bottom:1px solid #1e1e1e;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #161616;vertical-align:middle}
tr:last-child td{border-bottom:none}
/* Watched tags */
.watch-tag{display:inline-flex;align-items:center;gap:6px;background:#1a2a3a;
           border-radius:5px;padding:5px 10px;margin:3px;font-size:.82rem}
.watch-tag .id{color:#444;font-size:.72rem}
.watch-tag .rm{background:none;border:none;color:#555;cursor:pointer;font-size:.9rem;
               padding:0 2px;line-height:1}.watch-tag .rm:hover{color:#ef5350}
/* Search results */
.sr-item{display:flex;align-items:center;justify-content:space-between;
         padding:8px 12px;background:#161616;border-radius:6px;margin-bottom:6px}
.sr-name{font-size:.88rem;flex:1}
.sr-id{font-size:.72rem;color:#555;margin:0 12px}
/* Status bar */
#sb{position:fixed;bottom:0;left:0;right:0;background:#0a0a0a;padding:5px 20px;
    font-size:.72rem;color:#444;border-top:1px solid #1a1a1a;display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.on{background:#66bb6a}.dot.off{background:#ef5350}
.empty{color:#444;font-style:italic;font-size:.82rem;padding:6px 0}
.status-badge{font-size:.78rem;font-weight:500;padding:2px 10px;border-radius:12px;margin-left:10px;vertical-align:middle}
/* Chunk detail toggle */
.card-hdr{display:flex;align-items:flex-start;gap:8px;margin-bottom:4px}
.card-hdr-info{flex:1;min-width:0}
.detail-btn{background:#1a3a4a;color:#4fc3f7;border:none;border-radius:4px;padding:3px 9px;
            font-size:.7rem;cursor:pointer;white-space:nowrap;flex-shrink:0;margin-top:2px}
.detail-btn:hover{background:#1e4a5e}
.chunks{margin-top:8px;padding-top:8px;border-top:1px solid #222}
.chunk-row{margin-bottom:5px}
.chunk-meta{display:flex;justify-content:space-between;font-size:.68rem;color:#555;margin-bottom:2px}
.chunk-bar{background:#1a1a1a;border-radius:2px;height:3px}
.chunk-fill{height:100%;border-radius:2px;background:#4fc3f7;transition:width .3s}
.s-waiting{color:#666}.s-downloading{color:#4fc3f7}.s-done{color:#66bb6a}
.s-error,.s-timeout{color:#ef5350}.s-paused{color:#ffd54f}.s-cancelling{color:#ff7043}
/* Task control buttons */
.ctrl-btns{display:flex;gap:4px;flex-shrink:0;align-items:flex-start;margin-top:2px}
.ctrl-btn{background:#1e2a35;color:#9e9e9e;border:none;border-radius:4px;padding:3px 8px;
          font-size:.68rem;cursor:pointer;white-space:nowrap;line-height:1.4}
.ctrl-btn:hover{background:#253545;color:#e0e0e0}
.ctrl-btn.resume-btn{color:#81c784}.ctrl-btn.resume-btn:hover{background:#1a2e1a;color:#66bb6a}
.ctrl-btn.cancel-btn{color:#ef9a9a}.ctrl-btn.cancel-btn:hover{background:#3a1a1a;color:#ef5350}
/* Completed group view */
.completed-ctrl{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.grp-block{background:#161616;border:1px solid #1e1e1e;border-radius:8px;margin-bottom:10px;overflow:hidden}
.grp-summary{display:flex;align-items:center;gap:8px;padding:10px 14px;cursor:pointer;
             list-style:none;user-select:none;flex-wrap:wrap}
.grp-summary::-webkit-details-marker{display:none}
.grp-arrow{color:#555;font-size:.72rem;transition:transform .2s;flex-shrink:0}
details[open]>.grp-summary .grp-arrow{transform:rotate(90deg)}
.grp-name{font-size:.85rem;font-weight:600;flex:1;min-width:80px;word-break:break-all}
.grp-count{color:#555;font-size:.75rem;white-space:nowrap}
.tag{border-radius:4px;padding:2px 7px;font-size:.7rem;font-weight:600;white-space:nowrap}
.tag-ok{background:#1b5e20;color:#81c784}
.tag-arch{background:#1a237e;color:#90caf9}
.grp-open-btn{margin-left:auto}
/* Auth modal */
#auth-mask{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);
           z-index:200;align-items:center;justify-content:center}
#auth-mask.show{display:flex}
.auth-box{background:#1a1a1a;border:1px solid #333;border-radius:12px;
          padding:32px;width:380px;max-width:90vw}
.auth-box h3{color:#4fc3f7;margin-bottom:8px;font-size:1.05rem}
.auth-box p{color:#aaa;font-size:.85rem;margin-bottom:20px;line-height:1.5}
.auth-box input{width:100%;margin-bottom:12px;font-size:1rem;letter-spacing:.15em}
.auth-box .btn{width:100%;padding:10px}
#auth-err{color:#ef5350;font-size:.8rem;margin-top:8px;min-height:18px}
#auth-where{background:#26303a;border-radius:6px;padding:8px 10px;margin:4px 0 10px;font-size:.82rem;line-height:1.5;color:#cfd8dc}
#auth-where b{color:#4fc3f7}
#auth-resend{background:none;border:none;color:#4fc3f7;font-size:.8rem;cursor:pointer;margin-top:8px;padding:0;text-decoration:underline}
#auth-resend:disabled{color:#666;cursor:default;text-decoration:none}
#auth-qr-btn{width:100%;margin-top:12px;background:#2e7d32}
#auth-qr{display:none;text-align:center;margin:4px 0 12px;font-size:.82rem;line-height:1.6;color:#cfd8dc}
#auth-qr img{width:200px;height:200px;background:#fff;border-radius:6px;display:block;margin:0 auto 8px}
.scroll-top-btn{position:fixed;bottom:24px;right:24px;z-index:999;
  width:44px;height:44px;border-radius:50%;
  background:#1f1f1f;color:#888;border:1px solid #333;
  font-size:1.4rem;cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:color .2s,border-color .2s,background .2s;padding:0;line-height:1}
.scroll-top-btn:hover{color:#4fc3f7;border-color:#4fc3f7;background:#262626}
/* MD5 dedup toast */
#toasts-container{position:fixed;bottom:80px;right:24px;z-index:1100;
  display:flex;flex-direction:column-reverse;gap:10px;max-width:380px}
.toast-card{background:#1f1f1f;border:1px solid #444;border-radius:8px;
  padding:12px 14px;color:#e0e0e0;box-shadow:0 4px 16px rgba(0,0,0,.5);
  font-size:.85rem;line-height:1.5;animation:toast-in .25s ease-out}
.toast-card .toast-title{color:#ffd54f;font-weight:600;margin-bottom:6px}
.toast-card .toast-meta{color:#888;font-size:.78rem;word-break:break-all}
.toast-card .toast-path{color:#5db;font-family:monospace;font-size:.75rem;cursor:pointer;margin-top:2px}
.toast-card .toast-path:hover{text-decoration:underline}
.toast-card .toast-actions{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;align-items:center}
.toast-card .toast-countdown{color:#888;font-size:.75rem;margin-left:auto;font-variant-numeric:tabular-nums}
@keyframes toast-in{from{transform:translateX(20px);opacity:0}to{transform:translateX(0);opacity:1}}
</style>
</head>
<body>

<!-- MD5 dedup toast 容器 -->
<div id="toasts-container"></div>

<!-- 移动文件夹对话框 -->
<div id="movegrp-mask" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:2000;justify-content:center;align-items:center">
  <div style="background:#1f1f1f;padding:20px 24px;border-radius:8px;max-width:560px;width:90%">
    <h3 style="margin:0 0 8px 0;color:#e0e0e0">移动文件夹</h3>
    <p id="movegrp-folder" style="font-family:monospace;font-size:.78rem;color:#5db;margin:0 0 12px 0;word-break:break-all"></p>
    <div style="font-size:.78rem;color:#888;margin-bottom:6px">目标父目录（绝对路径）：</div>
    <div style="display:flex;gap:6px;align-items:center">
      <input id="movegrp-input" list="movegrp-history-dl" type="text"
             style="flex:1;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:6px 8px;font-family:monospace;font-size:.85rem"
             placeholder="/path/to/target">
      <datalist id="movegrp-history-dl"></datalist>
    </div>
    <div id="movegrp-error" style="color:#ef5350;font-size:.78rem;min-height:20px;margin-top:6px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
      <button class="btn btn-sm" id="movegrp-cancel">取消</button>
      <button class="btn btn-sm" id="movegrp-confirm" style="background:#2e7d32">确认移动</button>
    </div>
  </div>
</div>

<!-- 磁盘空间横幅（固定顶部） -->
<div id="disk-banner" style="display:none;position:fixed;top:0;left:0;right:0;
     padding:12px 20px;text-align:center;font-weight:500;z-index:1000">
  <span id="disk-banner-msg"></span>
  <button id="disk-banner-close" style="margin-left:16px;background:rgba(0,0,0,.3);
          color:#fff;border:1px solid rgba(255,255,255,.4);border-radius:4px;
          padding:3px 12px;cursor:pointer;font-size:.85rem">确认</button>
</div>

<!-- Auth modal -->
<div id="auth-mask">
  <div class="auth-box">
    <h3 id="auth-title">Telegram 验证</h3>
    <p id="auth-desc">请打开 Telegram，查看收到的验证码后填入下方。</p>
    <div id="auth-qr"><img id="auth-qr-img" alt="登录二维码">手机 Telegram → <b>设置 → 设备（Devices）→ 扫描二维码（Scan QR）</b><br>扫这个码。二维码会自动刷新，过期不用管。</div>
    <div id="auth-where" style="display:none"></div>
    <input id="auth-input" type="text" placeholder="输入验证码…" autocomplete="off" inputmode="numeric">
    <button class="btn" id="auth-btn">提交</button>
    <div id="auth-err"></div>
    <button id="auth-resend" style="display:none">没收到？重新发送</button>
    <button class="btn" id="auth-qr-btn" style="display:none">收不到验证码？改用手机扫码登录</button>
  </div>
</div>

<h1>Userbot Monitor <span id="bot-status" class="status-badge"></span>
  <button id="hard-stop-btn" class="btn btn-sm"
          style="display:none;float:right;margin-top:.5rem;color:#ef5350;border-color:#ef5350;font-weight:normal"
          title="停掉下载器容器（只有 Docker 部署有这个按钮）。停了会一直停着，页面也会立刻失联；要恢复去 dashboard 设置页「服务启停」点启动。">
    ⏹ 停止 downloader
  </button>
</h1>
<div id="hard-stop-notice"
     style="display:none;background:#3a1010;border:1px solid #ef5350;color:#ff8f8f;padding:.8rem 1rem;margin:.5rem 0;border-radius:4px">
</div>

<!-- Search -->
<section>
  <h2>搜索聊天</h2>
  <div class="row">
    <input id="sq" placeholder="输入聊天名称关键词…" style="flex:1">
    <button class="btn" id="sbtn">搜索</button>
  </div>
  <div id="sr"></div>
</section>

<!-- 手动下载 -->
<section>
  <h2 id="manual-toggle" style="cursor:pointer;user-select:none">手动下载 <span id="manual-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span></h2>
  <div id="manual-panel">
    <!-- 场景 D：单条 -->
    <div class="manual-block" style="border-bottom:1px solid #1e1e1e;padding-bottom:10px;margin-bottom:10px">
      <div style="font-size:.85rem;color:#bbb;margin-bottom:6px">📎 下载指定消息（单条）</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <input id="md-cid" placeholder="频道 ID" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem;width:160px">
        <input id="md-mid" placeholder="消息 ID" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem;width:120px">
        <button class="btn btn-sm" id="md-go">下载</button>
        <span id="md-result" style="color:#888;font-size:.75rem"></span>
      </div>
    </div>

    <!-- 场景 A：全频道历史 -->
    <div class="manual-block" style="border-bottom:1px solid #1e1e1e;padding-bottom:10px;margin-bottom:10px">
      <div style="font-size:.85rem;color:#bbb;margin-bottom:6px">📚 下载频道全部历史</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <input id="ha-chat" placeholder="频道 ID 或 @username" style="flex:1;min-width:200px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem">
        <button class="btn btn-sm" id="ha-go">开始扫描</button>
        <span id="ha-result" style="color:#888;font-size:.75rem"></span>
      </div>
    </div>

    <!-- 场景 B：指定范围 -->
    <div class="manual-block">
      <div style="font-size:.85rem;color:#bbb;margin-bottom:6px">🎯 下载指定范围</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
        <input id="hb-chat" placeholder="频道 ID 或 @username" style="flex:1;min-width:200px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem">
        <label style="font-size:.78rem;color:#aaa"><input type="radio" name="hb-mode" value="id" checked> 按 ID</label>
        <label style="font-size:.78rem;color:#aaa"><input type="radio" name="hb-mode" value="date"> 按日期</label>
      </div>
      <div id="hb-id-block" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
        <input id="hb-min-id" type="number" placeholder="起始消息 ID（可选）" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem;width:200px">
        <input id="hb-max-id" type="number" placeholder="结束消息 ID（可选）" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem;width:200px">
      </div>
      <div id="hb-date-block" style="display:none;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
        <input id="hb-min-date" type="datetime-local" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem">
        <input id="hb-max-date" type="datetime-local" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem">
      </div>
      <div style="display:flex;gap:6px;align-items:center">
        <button class="btn btn-sm" id="hb-go">开始扫描</button>
        <span id="hb-result" style="color:#888;font-size:.75rem"></span>
      </div>
    </div>

    <!-- A/B jobs 进度展示（C 在「遗漏补下」section） -->
    <div id="hist-ab-jobs" style="margin-top:12px"></div>
  </div>
</section>

<!-- 遗漏补下 -->
<section>
  <h2 id="missing-toggle" style="cursor:pointer;user-select:none">遗漏补下 <span id="missing-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span></h2>
  <div id="missing-panel">
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
      <input id="hc-chat" placeholder="频道 ID 或 @username" style="flex:1;min-width:200px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem">
      <select id="hc-watched-list" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:3px 6px;font-size:.78rem;max-width:240px">
        <option value="">— 从已监听频道选择 —</option>
      </select>
      <button class="btn btn-sm" id="hc-go">开始扫描</button>
      <span id="hc-result" style="color:#888;font-size:.75rem"></span>
    </div>
    <div id="hist-c-jobs"></div>
  </div>
</section>

<!-- Settings -->
<section>
  <h2 id="st-toggle" style="cursor:pointer;user-select:none">设置 <span id="st-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span></h2>
  <div id="st-panel" style="display:none">
    <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end;margin-bottom:8px">
      <label style="display:flex;flex-direction:column;gap:4px;font-size:.82rem;color:#aaa">
        全局最大连接数
        <input id="s-mtc" type="number" min="1" max="64" style="width:68px">
      </label>
      <button class="btn btn-sm" id="s-save">应用</button>
    </div>
    <div id="s-warn" style="color:#ffd54f;font-size:.78rem;min-height:18px"></div>
    <div style="color:#444;font-size:.72rem;margin-top:2px">分块数自动按文件大小决定：&lt;50MB 1连接，50-500MB 2，500MB-2GB 4，&gt;2GB 6；修改立即生效并写入 .env</div>

    <!-- P1-6 Path management -->
    <div style="margin-top:18px;border-top:1px solid #2a2a2a;padding-top:14px">
      <div style="font-size:.85rem;color:#bbb;margin-bottom:10px">输出路径管理</div>

      <div style="margin-bottom:14px">
        <div style="font-size:.78rem;color:#888;margin-bottom:4px">下载路径 (DOWNLOAD_DIR)</div>
        <div id="dd-current" style="font-family:monospace;font-size:.78rem;color:#5db" data-default=""></div>
        <div style="display:flex;gap:6px;margin-top:6px;align-items:center;flex-wrap:wrap">
          <input id="dd-input" type="text" style="flex:1;min-width:280px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem" placeholder="/绝对路径">
          <select id="dd-history" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:3px 6px;font-size:.78rem;max-width:240px"></select>
          <button class="btn btn-sm" id="dd-save">应用</button>
          <button class="btn btn-sm" id="dd-open" title="在文件管理器中打开下载目录">📂 打开</button>
        </div>
      </div>

      <div style="margin-bottom:8px">
        <div style="font-size:.78rem;color:#888;margin-bottom:4px">集合点路径 (WATCH_PATH，下载完压缩包后 mover 投递的目标父目录)</div>
        <div id="wp-current" style="font-family:monospace;font-size:.78rem;color:#5db" data-default=""></div>
        <div style="display:flex;gap:6px;margin-top:6px;align-items:center;flex-wrap:wrap">
          <input id="wp-input" type="text" style="flex:1;min-width:280px;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:4px 6px;font-family:monospace;font-size:.78rem" placeholder="/绝对路径">
          <select id="wp-history" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:3px 6px;font-size:.78rem;max-width:240px"></select>
          <label style="display:flex;align-items:center;gap:4px;font-size:.76rem;color:#aaa">
            <input id="wp-sync" type="checkbox" checked> 同步到 Unzipper
          </label>
          <button class="btn btn-sm" id="wp-save">应用</button>
          <button class="btn btn-sm" id="wp-open" title="在文件管理器中打开集合点目录">📂 打开</button>
        </div>
      </div>

      <div id="path-warn" style="color:#ffd54f;font-size:.78rem;min-height:18px;margin-top:6px"></div>
      <div style="color:#444;font-size:.72rem">改路径只影响新任务；下拉框第一项始终是系统默认路径，其余按最近使用倒序。</div>

      <!-- 磁盘空间显示 -->
      <div id="dd-disk" style="font-size:.78rem;color:#888;margin-top:10px">下载目录磁盘剩余 检测中…</div>
    </div>
  </div>
</section>

<!-- Downloads -->
<section>
  <h2 id="dl-toggle" style="cursor:pointer;user-select:none">下载中 <span id="dl-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span><span id="ac" style="color:#444;font-weight:normal;font-size:.8rem"></span><span id="spd" style="color:#4fc3f7;font-weight:normal;font-size:.8rem;margin-left:10px"></span><button id="dup-toggle-btn" class="btn btn-sm" style="float:right;font-weight:normal;font-size:.75rem" title="待确认重复下载">重复文件 (<span id="dup-count">0</span>)</button></h2>
  <div id="dl-panel">
    <div id="al"><p class="empty">暂无下载任务</p></div>
  </div>
</section>

<!-- F6: 重复下载确认队列 -->
<section id="dup-section" style="display:none">
  <h2 style="cursor:default">待确认重复下载 <span id="dup-section-count" style="color:#888;font-size:.78rem;font-weight:normal;margin-left:8px"></span></h2>
  <div id="dup-panel">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
      <label style="font-size:.78rem;color:#888">排序：
        <select id="dup-sort" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:2px 6px;font-size:.78rem">
          <option value="time">入队时间（新→旧）</option>
          <option value="size">文件大小（大→小）</option>
        </select>
      </label>
      <button class="btn btn-sm" id="dup-clear" style="margin-left:auto;color:#ef9a9a">清空列表</button>
    </div>
    <div id="dup-table-wrap"></div>
  </div>
</section>

<!-- Queue (waiting tasks, paginated) -->
<section>
  <h2 id="queue-toggle" style="cursor:pointer;user-select:none">排队中 <span id="queue-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span><span id="queue-count" style="color:#888;font-size:.78rem;font-weight:normal;margin-left:8px"></span></h2>
  <div id="queue-panel">
    <div id="queue-list"><p class="empty">暂无排队任务</p></div>
    <div id="queue-pager" style="display:none;align-items:center;gap:8px;justify-content:center;margin-top:10px;font-size:.8rem">
      <button class="btn btn-sm" id="queue-prev">上一页</button>
      <span id="queue-page-info" style="color:#888;font-family:monospace">第 1 / 1 页</span>
      <button class="btn btn-sm" id="queue-next">下一页</button>
    </div>
  </div>
</section>

<!-- Completed -->
<section>
  <h2 id="completed-toggle" style="cursor:pointer;user-select:none">已完成 <span id="completed-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span> <span id="completed-count" style="color:#888;font-size:.78rem;font-weight:normal;margin-left:8px"></span></h2>
  <div id="completed-panel">
    <div class="completed-ctrl" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
      <label style="font-size:.78rem;color:#888">排序：
        <select id="history-sort-by" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:2px 6px;font-size:.78rem">
          <option value="finished_at">完成时间</option>
          <option value="filename">文件名</option>
          <option value="filesize">文件大小</option>
          <option value="status">状态</option>
          <option value="queued_at">入队时间</option>
          <option value="extract_status">解压状态</option>
        </select>
      </label>
      <button id="history-sort-order" class="btn btn-sm" title="切换升序/降序">↓</button>
      <button class="btn btn-sm" id="mode-btn">按组分类</button>
      <button class="btn btn-sm" id="refresh-btn" title="刷新列表">🔄</button>
      <button class="btn btn-sm" id="retry-all-btn" style="margin-left:auto;color:#ffd54f" title="一键重试当前 completed_downloads 中所有 error/timeout 任务">↻ 重试全部失败 (<span id="retry-all-count">0</span>)</button>
      <button class="btn btn-sm" id="clear-done-btn" style="color:#a5d6a7" title="只清除成功记录，保留 error/timeout">清空 done 任务</button>
      <button class="btn btn-sm" id="clear-btn" style="color:#ef9a9a">清空已完成</button>
    </div>
    <div id="completed-wrap"></div>
    <div class="completed-pagination" style="display:flex;justify-content:center;align-items:center;gap:10px;margin-top:10px;font-size:.85rem;flex-wrap:wrap">
      <button class="btn btn-sm" id="page-prev">← 上一页</button>
      <span id="page-info" style="color:#888;min-width:120px;text-align:center">第 1 页 / 共 1 页</span>
      <button class="btn btn-sm" id="page-next">下一页 →</button>
      <label style="margin-left:20px;color:#888;font-size:.78rem">每页：
        <select id="page-size" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:2px 6px;font-size:.78rem">
          <option value="20">20</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
      </label>
    </div>
  </div>
</section>

<!-- Watched -->
<section>
  <h2 id="wl-toggle" style="cursor:pointer;user-select:none">监听列表 <span id="wl-arrow" style="color:#555;font-size:.7rem;display:inline-block;transition:transform .2s">▶</span> <button id="pause-btn" class="btn btn-sm" style="float:right;font-weight:normal" title="暂停后停止接收新媒体；已下载和排队任务不受影响">⏸ 暂停监听</button></h2>
  <div id="wl-panel">
    <div class="wl-ctrl" style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
      <label style="font-size:.78rem;color:#888">排序：
        <select id="wl-sort-by" style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:2px 6px;font-size:.78rem">
          <option value="default">添加顺序</option>
          <option value="name">名称</option>
          <option value="watched_since">监听时间</option>
          <option value="task_count">任务数</option>
        </select>
      </label>
      <button id="wl-sort-order" class="btn btn-sm" title="切换升序/降序">↓</button>
      <button id="wl-reset-all" class="btn btn-sm" style="color:#ff9800" title="所有频道 task_count 归零">重置所有统计</button>
      <div style="display:flex;align-items:center;gap:4px;margin-left:auto">
        <input id="wl-search" type="text" placeholder="🔍 搜索频道名 / ID..." style="background:#1a1a1a;color:#e0e0e0;border:1px solid #444;padding:2px 6px;font-size:.78rem;width:200px">
        <button id="wl-search-clear" class="btn btn-sm" title="清空搜索" style="padding:2px 8px">✕</button>
      </div>
    </div>
    <div id="wl-search-info" style="display:none;color:#888;font-size:.75rem;margin-bottom:6px"></div>
    <div id="wl"><p class="empty">监听列表为空</p></div>
  </div>
</section>

<div id="sb"><span class="dot off" id="dot"></span><span id="st">连接中…</span></div>

<script>
const fmb = b => b < 1 ? (b*1024).toFixed(0)+' KB' : b.toFixed(1)+' MB';
const fspeed = bps => { const m = bps/1048576; return m >= 0.1 ? m.toFixed(1)+' MB/s' : (bps/1024).toFixed(0)+' KB/s'; };
const ftime = ts => ts ? new Date(ts*1000).toLocaleTimeString() : '-';
// P1-8: 完成时间含日期 YYYY-MM-DD HH:MM:SS
const fdate = ts => {
  if (!ts) return '-';
  const d = new Date(ts*1000);
  const pad = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate())
       + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
};
const fdur = (s,e) => (!s || !e) ? '-' : (e-s)<60 ? Math.round(e-s)+'s' : ((e-s)/60).toFixed(1)+'m';
const fwait = (q,s) => { if(!q || !s) return ''; const w = Math.round(s-q); return w > 5 ? ' (等待 '+w+'s)' : ''; };
const SC = {waiting:'#666',downloading:'#4fc3f7',done:'#66bb6a',error:'#ef5350',timeout:'#ef5350',flood_wait:'#ffd54f',paused:'#ffd54f',cancelling:'#ff7043'};
const SL = {waiting:'等待中',downloading:'下载中',done:'完成',error:'出错',timeout:'超时',flood_wait:'限速等待',paused:'已暂停',cancelling:'终止中'};

let viewMode = 'list';
let lastCompleted = [];
// P1-7: 监听列表全局状态（必须在 setupToggle 调用前声明，避免 TDZ 错误）
let wlSortBy    = localStorage.getItem('watched_sort_by')    || 'default';
let wlSortOrder = localStorage.getItem('watched_sort_order') || 'asc';
let lastWatched = {};
let wlSearchQuery = '';   // P1-search: 搜索词，不持久化
// P1-8: 已完成区域分页/排序状态（同样必须在事件绑定之前声明）
let historyCurrentPage = 0;
let historyPageSize    = parseInt(localStorage.getItem('history_page_size') || '50');
let historySortBy      = localStorage.getItem('history_sort_by')    || 'finished_at';
let historySortOrder   = localStorage.getItem('history_sort_order') || 'desc';
let historyTotal       = 0;
let historyMaxCap      = 5000;
let lastHistoryFetch   = 0;

// ── Auth ──────────────────────────────────────────────────────────────────────
let _authShownStep = 'idle';
function updateAuth(step, info) {
  const mask = document.getElementById('auth-mask');
  if (step === 'idle') { mask.classList.remove('show'); _authShownStep = 'idle'; return; }
  info = info || {};
  mask.classList.add('show');
  const whereEl  = document.getElementById('auth-where');
  const resendEl = document.getElementById('auth-resend');
  // 服务端的错误提示（验证码不对 / 过期 / 限流）；为空时不覆盖本地「连不上」之类的提示
  if (info.error) document.getElementById('auth-err').textContent = info.error;
  if (step === 'waiting_code') {
    document.getElementById('auth-title').textContent = 'Telegram 验证码';
    document.getElementById('auth-desc').textContent  = '验证码不一定发到 Telegram App，请按下面写的位置去找。';
    document.getElementById('auth-input').inputMode   = 'numeric';
    document.getElementById('auth-input').type        = 'text';
    if (info.where) {
      whereEl.innerHTML = '验证码发到了：<b>' + esc(info.where) + '</b>'
        + (info.length ? '<br>共 ' + info.length + ' 位' : '');
      whereEl.style.display = 'block';
    } else { whereEl.style.display = 'none'; }
    resendEl.style.display = 'inline-block';
    resendEl.textContent = info.next ? ('没收到？改用' + info.next + '重新发送') : '没收到？重新发送';
    const qrBox = document.getElementById('auth-qr');
    if (info.qr) {
      document.getElementById('auth-qr-img').src = info.qr;
      qrBox.style.display = 'block';
      document.getElementById('auth-qr-btn').style.display = 'none';
    } else {
      qrBox.style.display = 'none';
      document.getElementById('auth-qr-btn').style.display = 'block';
    }
  } else {
    whereEl.style.display = 'none';
    resendEl.style.display = 'none';
    document.getElementById('auth-qr').style.display = 'none';
    document.getElementById('auth-qr-btn').style.display = 'none';
    document.getElementById('auth-title').textContent = '两步验证';
    document.getElementById('auth-desc').textContent  = '您的账号开启了两步验证，请输入密码。';
    document.getElementById('auth-input').inputMode   = 'text';
    document.getElementById('auth-input').type        = 'password';
  }
  if (_authShownStep !== step) document.getElementById('auth-input').focus();
  _authShownStep = step;
}
document.getElementById('auth-btn').onclick = submitAuth;
document.getElementById('auth-qr-btn').onclick = async () => {
  const btn = document.getElementById('auth-qr-btn');
  const err = document.getElementById('auth-err');
  btn.disabled = true; err.textContent = '正在生成二维码…';
  try {
    const r = await apiFetch('/api/auth/qr', {method:'POST'});
    const d = await r.json().catch(() => ({}));
    if (!d.ok) err.textContent = d.error || '生成二维码失败';
    else err.textContent = '';
    // 二维码本身由服务端推送过来（updateAuth 里显示）
  } catch (e) {
    err.textContent = '连不上下载器服务（网络断了？），请检查后再试';
  } finally {
    setTimeout(() => { btn.disabled = false; }, 3000);
  }
};
document.getElementById('auth-resend').onclick = async () => {
  const btn = document.getElementById('auth-resend');
  const err = document.getElementById('auth-err');
  btn.disabled = true; err.textContent = '正在重新发送…';
  try {
    const r = await apiFetch('/api/auth/resend', {method:'POST'});
    const d = await r.json().catch(() => ({}));
    err.textContent = d.ok ? '已重新发送，请按上面写的位置查看最新一条' : ((d.auth_info && d.auth_info.error) || d.error || '重新发送失败');
    if (d.auth_info) updateAuth('waiting_code', Object.assign({}, d.auth_info, {error: ''}));
  } catch (e) {
    err.textContent = '连不上下载器服务（网络断了？），请检查后再试';
  } finally {
    setTimeout(() => { btn.disabled = false; }, 30000);   // 防连点：30 秒内只能点一次
  }
};
document.getElementById('auth-input').addEventListener('keydown', e => { if(e.key==='Enter') submitAuth(); });
async function submitAuth() {
  const val = document.getElementById('auth-input').value.trim();
  if (!val) return;
  const err = document.getElementById('auth-err');
  err.textContent = '正在验证…';
  let r;
  try {
    r = await apiFetch('/api/auth', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:val})});
  } catch (e) {
    // 2026-11-13：以前这里没 catch，网络断了点提交毫无反应，用户以为验证码不对
    err.textContent = '连不上下载器服务（网络断了？），验证码没有提交出去，请检查后再试';
    return;
  }
  if (r.ok) {
    document.getElementById('auth-input').value = '';
    // 结果（成功就关弹窗 / 失败显示原因）由服务端推送回来
  } else {
    const d = await r.json().catch(() => ({}));
    err.textContent = d.error || ('提交失败（HTTP ' + r.status + '），请重试');
  }
}

// ── Search ────────────────────────────────────────────────────────────────────
async function doSearch() {
  const q = document.getElementById('sq').value.trim();
  if (!q) return;
  const btn = document.getElementById('sbtn');
  btn.textContent = '搜索中…'; btn.disabled = true;
  const sr = document.getElementById('sr');
  sr.innerHTML = '';
  try {
    const r = await apiFetch('/api/search?q='+encodeURIComponent(q));
    const data = await r.json();
    if (r.status === 403) { sr.innerHTML = '<p class="empty">请先完成登录</p>'; return; }
    if (!data.length) { sr.innerHTML = '<p class="empty">未找到匹配的聊天</p>'; return; }
    sr.innerHTML = data.map(d =>
      '<div class="sr-item">'
      +'<span class="sr-name">'+esc(d.name)+'</span>'
      +'<span class="sr-id">'+d.id+'</span>'
      +'<button class="btn btn-sm add-watch-btn" data-id="'+d.id+'" data-name="'+esc(d.name)+'">添加监听</button>'
      +'</div>'
    ).join('');
  } catch(e) { sr.innerHTML = '<p class="empty">搜索失败</p>'; }
  finally { btn.textContent = '搜索'; btn.disabled = false; }
}
async function addWatch(id, name, btn) {
  btn.disabled = true; btn.textContent = '添加中…';
  const r = await apiFetch('/api/watch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,name})});
  if (r.ok) {
    const j = await r.json();
    if (j.already_watched) {
      // P1-5a Q2: 该频道已在监听中
      btn.textContent = '⚠ 已在监听';
      btn.style.background = '#4a3010';
      btn.style.color = '#ff9800';
    } else {
      btn.textContent = '✓ 已添加';
      btn.style.background = '#2e7d32';
    }
  } else { btn.textContent = '添加监听'; btn.disabled = false; }
}
async function removeWatch(id, btn) {
  btn.disabled = true;
  const r = await apiFetch('/api/watch/'+encodeURIComponent(id), {method:'DELETE'});
  if (!r.ok) btn.disabled = false;
}
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
const API_KEY = '__API_KEY__';
async function apiFetch(url, opts={}) {
  const headers = Object.assign({'X-API-Key': API_KEY}, opts.headers || {});
  return fetch(url, {...opts, headers});
}

// ── Status indicator ──────────────────────────────────────────────────────────
function updateStatus(active, completed, paused) {
  const el = document.getElementById('bot-status');
  if (paused) {
    el.textContent = '⏸ 监听暂停中';
    el.style.cssText = 'background:#4a3010;color:#ff9800';
    return;
  }
  if (completed.some(r => r.status === 'error' || r.status === 'timeout')) {
    el.textContent = '任务异常'; el.style.cssText = 'background:#3b1010;color:#ef5350';
  } else if (active.some(t => t.status === 'downloading' || t.status === 'waiting')) {
    el.textContent = '下载中';   el.style.cssText = 'background:#0d2b1a;color:#66bb6a';
  } else {
    el.textContent = '待机中';   el.style.cssText = 'background:#2a2a10;color:#ffd54f';
  }
}

// ── Completed helpers ─────────────────────────────────────────────────────────
// P1-8 Phase 2: 解压状态徽章
const EX_LABEL = {
  not_archive:     '非压缩包',
  ready:           '待搬运',
  moving:          '搬运中',
  move_failed:     '搬运失败',
  pending_extract: '排队解压',
  extracting:      '解压中',
  extracted:       '已解压',
  extract_failed:  '解压失败',
};
const EX_COLOR = {
  not_archive:     '#555',
  ready:           '#90a4ae',
  moving:          '#4fc3f7',
  move_failed:     '#ef5350',
  pending_extract: '#ffd54f',
  extracting:      '#66bb6a',
  extracted:       '#81c784',
  extract_failed:  '#ef5350',
};

function extractBadge(r) {
  const s = r.extract_status || 'not_archive';
  const label = EX_LABEL[s] || s;
  const color = EX_COLOR[s] || '#888';
  return '<span style="font-size:.7rem;padding:1px 6px;border-radius:8px;background:#1a1a1a;border:1px solid '+color+';color:'+color+';white-space:nowrap">'+label+'</span>';
}

function completedRow(r) {
  const canRetry = (r.status === 'error' || r.status === 'timeout') && r.chat_id && r.message_id;
  let ops = '';
  if (r.path) ops += '<button class="btn btn-sm open-file-btn" data-path="'+esc(r.path)+'">打开文件</button>'
                    +'<button class="btn btn-sm open-dir-btn" data-path="'+esc(r.dir)+'">文件夹</button>';
  if (canRetry) ops += '<button class="btn btn-sm retry-btn" data-task-id="'+esc(r.task_id)+'">重试</button>';
  ops += '<button class="btn btn-sm del-rec-btn" data-task-id="'+esc(r.task_id)+'" style="color:#ef9a9a">删除记录</button>';
  const opsCell = ops
    ? '<div style="display:flex;gap:4px;flex-wrap:nowrap;align-items:center">'+ops+'</div>'
    : '-';
  // 文件名下方加完整保存路径（点击打开所在目录）
  const pathDir = r.dir || (r.path ? r.path.replace(/[/\\\\][^/\\\\]+$/, '') : '');
  const pathRow = pathDir
    ? '<div style="font-size:.7rem;color:#5a6a78;font-family:monospace;word-break:break-all;margin-top:2px;cursor:pointer" '
      + 'class="open-dir-btn" data-path="'+esc(pathDir)+'" title="点击打开此目录">📁 '+esc(pathDir)+'</div>'
    : '';
  // 多选 checkbox（前端管理选中状态）
  const cb = '<input type="checkbox" class="row-select-cb" data-task-id="'+esc(r.task_id)+'" '
    + 'data-status="'+esc(r.status)+'" '+(selectedTaskIds.has(r.task_id)?'checked':'')+'>';
  return '<tr>'
    +'<td style="text-align:center;width:32px">'+cb+'</td>'
    +'<td style="word-break:break-all">'+esc(r.filename)+pathRow+'</td>'
    +'<td style="color:#888;font-size:.75rem">'+esc(r.label)+'</td>'
    +'<td>'+fmb(r.size_mb)+'</td>'
    +'<td style="color:'+SC[r.status]+'">'+SL[r.status]
    +(r.error_msg?'<br><span style="font-size:.7rem;color:#666">'+esc(r.error_msg)+'</span>':'')
    +'</td><td>'+extractBadge(r)+'</td>'
    +'<td>'+fdur(r.started_at,r.finished_at)+fwait(r.queued_at,r.started_at)+'</td>'
    +'<td style="color:#555;font-variant-numeric:tabular-nums">'+fdate(r.finished_at)+'</td>'
    +'<td>'+opsCell+'</td></tr>';
}

// 已完成列表多选状态（前端管理；分页 / 刷新时清空）
const selectedTaskIds = new Set();

function _renderBulkBar(rows) {
  // 顶部批量操作条（出现在表格之前；选中数 0 时隐藏）
  if (!selectedTaskIds.size) return '';
  let retryable = 0;
  for (const r of rows) {
    if (selectedTaskIds.has(r.task_id) && (r.status === 'error' || r.status === 'timeout')) retryable++;
  }
  return '<div style="background:#1a1f2a;border:1px solid #2a3a4a;padding:8px 12px;margin-bottom:8px;'
    + 'border-radius:6px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
    + '<span style="color:#4fc3f7">已选 ' + selectedTaskIds.size + ' 条</span>'
    + (retryable > 0 ? '<span style="color:#ffd54f">（其中 ' + retryable + ' 条可重试）</span>' : '')
    + '<button class="btn btn-sm" id="bulk-retry-btn" style="margin-left:auto;color:#ffd54f"'
    + (retryable === 0 ? ' disabled' : '') + '>↻ 重试选中</button>'
    + '<button class="btn btn-sm" id="bulk-delete-btn" style="color:#ef9a9a">🗑 删除选中</button>'
    + '<button class="btn btn-sm" id="bulk-clear-btn">取消选中</button>'
    + '</div>';
}

function renderCompletedList(rows) {
  if (!rows.length) {
    selectedTaskIds.clear();
    return '<p class="empty">暂无记录</p>';
  }
  // 清理：选中里不在当前页的项剔除（分页切换 / 刷新自然收敛）
  const pageIds = new Set(rows.map(r => r.task_id));
  for (const tid of Array.from(selectedTaskIds)) {
    if (!pageIds.has(tid)) selectedTaskIds.delete(tid);
  }
  const allChecked = rows.every(r => selectedTaskIds.has(r.task_id));
  const headCb = '<input type="checkbox" id="select-all-cb" '+(allChecked?'checked':'')+'>';
  return '<table><thead><tr>'
    + '<th style="width:32px;text-align:center">'+headCb+'</th>'
    + '<th>文件名</th><th>来源</th><th>大小</th><th>状态</th><th>解压</th><th>耗时</th><th>完成时间</th><th>操作</th>'
    + '</tr></thead><tbody>'
    + rows.map(completedRow).join('')
    + '</tbody></table>';
}

function gsKeyOf(row) {
  if (!row) return '';
  const cid = row.chat_id;
  if (cid === undefined || cid === null) return '';
  const gid = row.grouped_id;
  return gid ? (cid + '_' + gid) : (cid + '_' + row.message_id);
}

function renderCompletedGroup(rows) {
  if (!rows.length) return '<p class="empty">暂无记录</p>';
  const archExts = /\\.(zip|rar|7z|tar|gz|bz2|xz)$/i;
  const groups = new Map();
  for (const r of rows) {
    const key = r.dir || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  let html = '';
  for (const [dir, grpRows] of groups) {
    // 组内沿用后端给的顺序（不再二次排序）
    const allDone = grpRows.every(r => r.status === 'done');
    const hasArch = grpRows.some(r => archExts.test(r.filename));
    const folderName = dir ? dir.replace(/\\\\/g,'/').split('/').pop() : '未知路径';
    const gsKey = gsKeyOf(grpRows[0]);
    html += '<details class="grp-block" open>'
      +'<summary class="grp-summary">'
      +'<span class="grp-arrow">▶</span>'
      +'<span class="grp-name" title="'+esc(dir)+'">'+esc(folderName)+'</span>'
      +'<span class="grp-count">'+grpRows.length+' 个文件</span>'
      +(allDone ? '<span class="tag tag-ok">✅ 全部完成</span>' : '')
      +(hasArch ? '<span class="tag tag-arch">📦 含压缩包</span>' : '')
      +(dir ? '<button class="btn btn-sm open-dir-btn grp-open-btn" data-path="'+esc(dir)+'">打开文件夹</button>' : '')
      +(allDone && dir && gsKey
        ? '<button class="btn btn-sm move-grp-btn" data-gs-key="'+esc(gsKey)+'" data-folder="'+esc(dir)+'" style="color:#81c784">移动文件夹</button>'
        : '')
      +'</summary>'
      +'<table><thead><tr>'
      +'<th style="width:32px"></th>'
      +'<th>文件名</th><th>来源</th><th>大小</th><th>状态</th><th>解压</th><th>耗时</th><th>完成时间</th><th>操作</th>'
      +'</tr></thead><tbody>'
      +grpRows.map(completedRow).join('')
      +'</tbody></table>'
      +'</details>';
  }
  return html;
}

function renderCompleted(rows) {
  lastCompleted = rows;
  // 清理跨页选中（rows 是当前页快照）
  if (rows && rows.length) {
    const pageIds = new Set(rows.map(r => r.task_id));
    for (const tid of Array.from(selectedTaskIds)) {
      if (!pageIds.has(tid)) selectedTaskIds.delete(tid);
    }
  } else {
    selectedTaskIds.clear();
  }
  const bulkBar = _renderBulkBar(rows || []);
  const body = viewMode === 'list' ? renderCompletedList(rows) : renderCompletedGroup(rows);
  document.getElementById('completed-wrap').innerHTML = bulkBar + body;
}

// ── P1-8: 已完成区域分页/排序逻辑 ───────────────────────────────────────────
async function fetchHistory() {
  const offset = historyCurrentPage * historyPageSize;
  const url = '/api/history?'
    + 'limit=' + historyPageSize
    + '&offset=' + offset
    + '&sort_by=' + encodeURIComponent(historySortBy)
    + '&sort_order=' + historySortOrder;
  try {
    const r = await apiFetch(url);
    if (!r.ok) return;
    const d = await r.json();
    if (!d.ok) return;
    historyTotal = d.total;
    renderCompleted(d.items);
    updatePaginationUI();
  } catch (e) { /* ignore network errors */ }
}

function updatePaginationUI() {
  const totalPages = Math.max(1, Math.ceil(historyTotal / historyPageSize));
  const curPage    = Math.min(historyCurrentPage, totalPages - 1);
  if (curPage !== historyCurrentPage) historyCurrentPage = curPage;

  document.getElementById('page-info').textContent =
    '第 ' + (historyCurrentPage + 1) + ' 页 / 共 ' + totalPages + ' 页';
  document.getElementById('page-prev').disabled = historyCurrentPage === 0;
  document.getElementById('page-next').disabled = historyCurrentPage >= totalPages - 1;
  document.getElementById('completed-count').textContent =
    '共 ' + historyTotal + ' 条 / 上限 ' + historyMaxCap + ' 条';
}

function updateHistorySortBtn() {
  document.getElementById('history-sort-order').textContent =
    historySortOrder === 'asc' ? '↑' : '↓';
}

function maybeRefetchHistoryFromWS() {
  // P1-8: WS 推送时若用户在第 1 页 + 默认排序，2 秒节流后台拉取最新数据
  if (historyCurrentPage !== 0) return;
  if (historySortBy !== 'finished_at') return;
  if (historySortOrder !== 'desc') return;
  const now = Date.now();
  if (now - lastHistoryFetch < 2000) return;
  lastHistoryFetch = now;
  fetchHistory();
}

// ── Settings ──────────────────────────────────────────────────────────────────
function updateSettingsUI(s) {
  const el = document.getElementById('s-mtc');
  if (el && document.activeElement !== el) el.value = s.max_total_connections;
}
document.getElementById('st-toggle').addEventListener('click', () => {
  const panel = document.getElementById('st-panel');
  const arrow = document.getElementById('st-arrow');
  const show  = panel.style.display === 'none';
  panel.style.display    = show ? 'block' : 'none';
  arrow.style.transform  = show ? 'rotate(90deg)' : '';
});

// P1-5a Q3: 下载区/已完成区折叠（localStorage 持久化）
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
setupToggle('dl-toggle',        'dl-arrow',        'dl-panel',        'dl_section_collapsed');
setupToggle('queue-toggle',     'queue-arrow',     'queue-panel',     'queue_section_collapsed');
setupToggle('completed-toggle', 'completed-arrow', 'completed-panel', 'completed_section_collapsed');
setupToggle('wl-toggle',        'wl-arrow',        'wl-panel',        'watched_section_collapsed');
setupToggle('manual-toggle',    'manual-arrow',    'manual-panel',    'manual_section_collapsed');
setupToggle('missing-toggle',   'missing-arrow',   'missing-panel',   'missing_section_collapsed');

// P1-7 监听列表排序与统计控制
document.getElementById('wl-sort-by').value = wlSortBy;
updateWlSortBtn();
document.getElementById('wl-sort-by').addEventListener('change', e => {
  wlSortBy = e.target.value;
  localStorage.setItem('watched_sort_by', wlSortBy);
  renderWatched(lastWatched);
});
document.getElementById('wl-sort-order').addEventListener('click', () => {
  wlSortOrder = wlSortOrder === 'asc' ? 'desc' : 'asc';
  localStorage.setItem('watched_sort_order', wlSortOrder);
  updateWlSortBtn();
  renderWatched(lastWatched);
});
// P1-search: 监听列表搜索（纯前端 filter）
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

document.getElementById('wl-reset-all').addEventListener('click', async () => {
  if (!confirm('重置所有频道的任务计数？此操作不可撤销。')) return;
  const r = await apiFetch('/api/watch/reset-stats', {method: 'POST'});
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    alert('重置失败：' + (j.error || r.status));
  }
});
document.getElementById('s-save').addEventListener('click', async () => {
  const mtc  = parseInt(document.getElementById('s-mtc').value) || 1;
  const btn  = document.getElementById('s-save');
  const warn = document.getElementById('s-warn');
  btn.disabled = true; btn.textContent = '保存中…'; warn.textContent = '';
  try {
    const r = await apiFetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({max_total_connections: mtc})
    });
    const j = await r.json();
    if (j.ok) {
      btn.style.background = '#2e7d32'; btn.textContent = '已保存 ✓';
      setTimeout(() => { btn.style.background=''; btn.textContent='应用'; btn.disabled=false; }, 2000);
    } else {
      warn.textContent = j.error || '保存失败';
      btn.disabled = false; btn.textContent = '应用';
    }
  } catch(e) {
    warn.textContent = '请求失败'; btn.disabled = false; btn.textContent = '应用';
  }
});

// ── P1-6 Path management ─────────────────────────────────────────────────────
let pathSettingsCache = null;

function buildHistoryOptions(selectId, currentValue, defaultValue, history) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const opts = [];
  opts.push('<option value="">-- 选择历史路径 --</option>');
  opts.push('<option value="' + escapeHtml(defaultValue) + '">系统默认: ' + escapeHtml(defaultValue) + '</option>');
  (history || []).forEach(p => {
    if (p && p !== defaultValue) {
      opts.push('<option value="' + escapeHtml(p) + '">' + escapeHtml(p) + '</option>');
    }
  });
  sel.innerHTML = opts.join('');
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadPathSettings() {
  try {
    const r = await apiFetch('/api/settings');
    const s = await r.json();
    if (!s.ok) return;
    pathSettingsCache = s;
    document.getElementById('dd-current').textContent = s.download_dir;
    document.getElementById('dd-current').dataset.default = s.default_download_dir;
    const ddInput = document.getElementById('dd-input');
    if (document.activeElement !== ddInput) ddInput.value = s.download_dir;
    buildHistoryOptions('dd-history', s.download_dir, s.default_download_dir, s.download_dir_history);

    document.getElementById('wp-current').textContent = s.watch_path;
    document.getElementById('wp-current').dataset.default = s.default_watch_path;
    const wpInput = document.getElementById('wp-input');
    if (document.activeElement !== wpInput) wpInput.value = s.watch_path;
    buildHistoryOptions('wp-history', s.watch_path, s.default_watch_path, s.watch_path_history);
  } catch(e) { /* ignore */ }
}

document.getElementById('dd-history').addEventListener('change', e => {
  if (e.target.value) document.getElementById('dd-input').value = e.target.value;
});
document.getElementById('wp-history').addEventListener('change', e => {
  if (e.target.value) document.getElementById('wp-input').value = e.target.value;
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
      warn.textContent = '已生效（仅影响新任务）';
      setTimeout(() => { btn.style.background=''; btn.textContent=oldText; btn.disabled=false; warn.textContent=''; }, 2500);
      await loadPathSettings();
    } else {
      warn.textContent = j.error || '保存失败';
      btn.disabled = false; btn.textContent = oldText;
    }
  } catch(e) {
    warn.textContent = '请求失败'; btn.disabled = false; btn.textContent = oldText;
  }
}

document.getElementById('dd-save').addEventListener('click', () => {
  savePath('download_dir', 'dd-input', 'dd-save');
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

document.getElementById('dd-open').addEventListener('click', () => {
  openLocalPath(document.getElementById('dd-current').textContent.trim());
});
document.getElementById('wp-save').addEventListener('click', () => {
  const sync = document.getElementById('wp-sync').checked;
  savePath('watch_path', 'wp-input', 'wp-save', {sync_unzipper: sync});
});
document.getElementById('wp-open').addEventListener('click', () => {
  openLocalPath(document.getElementById('wp-current').textContent.trim());
});

loadPathSettings();

// ── Active download cards ─────────────────────────────────────────────────────
let lastActive = [];
const expandedTasks = new Set();

function renderCard(t) {
  const cls = t.status==='done'?'done':(t.status==='error'||t.status==='timeout')?'error':'';
  const hasChunks = Array.isArray(t.chunks) && t.chunks.length > 0;
  const expanded  = expandedTasks.has(t.task_id);
  let statusLabel;
  if (t.status === 'flood_wait' && t.flood_until) {
    const secs = Math.max(0, Math.ceil(t.flood_until - Date.now()/1000));
    statusLabel = '<span style="color:'+SC.flood_wait+'">限速等待 '+secs+'s</span>';
  } else {
    statusLabel = '<span class="s-'+t.status+'">'+(SL[t.status]||t.status)+' '+t.pct+'%</span>';
  }
  let chunksHtml = '';
  if (hasChunks && expanded) {
    chunksHtml = '<div class="chunks">'
      + t.chunks.map((c,i) =>
          '<div class="chunk-row">'
          +'<div class="chunk-meta"><span>块 '+(i+1)+'</span>'
          +'<span>'+c.pct+'%'+(c.speed>0?'&nbsp;&nbsp;'+fspeed(c.speed):'')+'</span></div>'
          +'<div class="chunk-bar"><div class="chunk-fill" style="width:'+c.pct+'%"></div></div>'
          +'</div>'
        ).join('')
      +'</div>';
  }
  // Control buttons: pause/resume only for chunked; cancel for all active statuses
  const canPause  = t.chunks !== null && t.status === 'downloading';
  const canResume = t.chunks !== null && t.status === 'paused';
  const canCancel = ['downloading','waiting','paused','flood_wait'].includes(t.status);
  let ctrlHtml = '';
  if (canPause || canResume || canCancel) {
    let btns = '';
    if (canPause)  btns += '<button class="ctrl-btn pause-btn"  data-task-id="'+esc(t.task_id)+'">暂停</button>';
    if (canResume) btns += '<button class="ctrl-btn resume-btn" data-task-id="'+esc(t.task_id)+'">继续</button>';
    if (canCancel) btns += '<button class="ctrl-btn cancel-btn" data-task-id="'+esc(t.task_id)+'">终止</button>';
    ctrlHtml = '<div class="ctrl-btns">'+btns+'</div>';
  }
  return '<div class="card" data-task-id="'+esc(t.task_id)+'">'
    +'<div class="card-hdr">'
    +'<div class="card-hdr-info">'
    +'<div class="card-lbl">'+esc(t.label)+'</div>'
    +'<div class="card-fn">'+esc(t.filename)+'</div>'
    +'</div>'
    +(hasChunks?'<button class="detail-btn" data-task-id="'+esc(t.task_id)+'">'+(expanded?'收起':'详情')+'</button>':'')
    +ctrlHtml
    +'</div>'
    +'<div class="bar-bg"><div class="bar-fill '+cls+'" style="width:'+t.pct+'%"></div></div>'
    +'<div class="card-meta">'+statusLabel
    +'<span>'+fmb(t.current_mb)+' / '+fmb(t.size_mb)+(t.speed>0?'&nbsp;&nbsp;↓ '+fspeed(t.speed):'')+'</span></div>'
    +chunksHtml
    +'</div>';
}

// 下载中：非 waiting 状态（包括 downloading / paused / flood_wait / cancelling）
// 排队中：waiting 状态，前端分页 20/页
const QUEUE_PAGE_SIZE = 20;
let queueCurrentPage = 1;

function renderActiveList(active) {
  lastActive = active;
  const dling = active.filter(t => t.status !== 'waiting');
  const al = document.getElementById('al');
  al.innerHTML = dling.length
    ? dling.map(renderCard).join('')
    : '<p class="empty">暂无下载任务</p>';
  renderQueueList(active);
}

function renderQueueList(active) {
  const queued = active.filter(t => t.status === 'waiting');
  const total = queued.length;
  const totalPages = Math.max(1, Math.ceil(total / QUEUE_PAGE_SIZE));
  if (queueCurrentPage > totalPages) queueCurrentPage = totalPages;
  if (queueCurrentPage < 1) queueCurrentPage = 1;

  document.getElementById('queue-count').textContent = total ? ' (共 ' + total + ' 个)' : '';

  const start = (queueCurrentPage - 1) * QUEUE_PAGE_SIZE;
  const slice = queued.slice(start, start + QUEUE_PAGE_SIZE);
  const list = document.getElementById('queue-list');
  list.innerHTML = slice.length
    ? slice.map(renderCard).join('')
    : '<p class="empty">暂无排队任务</p>';

  const pager = document.getElementById('queue-pager');
  pager.style.display = total > QUEUE_PAGE_SIZE ? 'flex' : 'none';
  document.getElementById('queue-page-info').textContent =
    '第 ' + queueCurrentPage + ' / ' + totalPages + ' 页';
  document.getElementById('queue-prev').disabled = queueCurrentPage <= 1;
  document.getElementById('queue-next').disabled = queueCurrentPage >= totalPages;
}

document.getElementById('queue-prev').addEventListener('click', () => {
  if (queueCurrentPage > 1) { queueCurrentPage--; renderQueueList(lastActive); }
});
document.getElementById('queue-next').addEventListener('click', () => {
  queueCurrentPage++; renderQueueList(lastActive);
});

// ── P1-5a Q4 软暂停按钮 ────────────────────────────────────────────────────
let lastPaused = false;
function updatePauseBtn(paused) {
  lastPaused = !!paused;
  const btn = document.getElementById('pause-btn');
  if (lastPaused) {
    btn.textContent = '▶ 恢复监听';
    btn.style.cssText = 'float:right;font-weight:normal;background:#4a3010;color:#ff9800;border-color:#ff9800';
  } else {
    btn.textContent = '⏸ 暂停监听';
    btn.style.cssText = 'float:right;font-weight:normal';
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

// ── 硬停按钮：POST /api/downloader/stop → control 服务停掉下载器容器（只有 Docker 版）──
// 与软暂停完全不同：软暂停只是把 handle_media 挂空档，进程照跑；这里是把进程关了。
// 原生部署不显示这个按钮（render 里按 d.is_docker 决定），原生用 ./stop.sh。
document.getElementById('hard-stop-btn').addEventListener('click', async () => {
  // ⚠️ JS 字符串换行必须写 \\n（Python 三引号里的裸 \\n 会被转成真换行，JS 语法错）
  if (!confirm('确定硬停 downloader 进程？\\n\\n' +
               '• 全部下载中的任务会被 SIGTERM 中断（已下的分块 .partN 保留）\\n' +
               '• 会一直停着，不会自己恢复\\n' +
               '• 停完这个页面也会失联\\n' +
               '• 要恢复请去 dashboard → 设置 → 服务启停，点「启动」')) return;
  const btn = document.getElementById('hard-stop-btn');
  btn.disabled = true; btn.textContent = '停止中…';
  try {
    const r = await apiFetch('/api/downloader/stop', {method:'POST'});
    const j = await r.json().catch(() => ({message:'解析失败'}));
    const notice = document.getElementById('hard-stop-notice');
    if (r.ok && j.ok) {
      notice.textContent = '⏹ 已发起停止：' + (j.message || '进程即将退出，页面即将失联。');
    } else {
      notice.textContent = '❌ 停止失败：' + (j.message || r.statusText);
      btn.disabled = false; btn.textContent = '⏹ 停止 downloader';
    }
    notice.style.display = 'block';
  } catch (err) {
    // 网络挂了通常正是「进程已经死了」，把话说清楚而不是显示 error
    const notice = document.getElementById('hard-stop-notice');
    notice.textContent = '⏹ 连接已断开——进程可能已停止。刷新页面确认。';
    notice.style.display = 'block';
  }
});

// ── Render ────────────────────────────────────────────────────────────────────
function render(d) {
  // 「⏹ 停止」只有 Docker 部署才有（经 control 服务停容器）；原生部署用 ./stop.sh
  document.getElementById('hard-stop-btn').style.display = d.is_docker ? '' : 'none';
  updateAuth(d.auth || 'idle', d.auth_info);
  updateStatus(d.active || [], d.completed || [], d.paused);
  if (d.settings) updateSettingsUI(d.settings);
  updatePauseBtn(d.paused);

  // Active
  const active   = d.active || [];
  const dlCount  = active.filter(t => t.status !== 'waiting').length;
  const conns    = d.active_conns  || 0;
  const maxC     = (d.settings && d.settings.max_total_connections) || 20;
  let acText = '';
  if (dlCount > 0) acText += ' ' + dlCount + '个文件，' + conns + '/' + maxC + '连接';
  document.getElementById('ac').textContent  = acText;
  document.getElementById('spd').textContent = (d.total_speed > 0) ? '↓ '+fspeed(d.total_speed) : '';
  renderActiveList(active);

  // P1-8: 已完成区域由 /api/history 驱动（不再用 d.completed），WS 仅触发 page=1 节流刷新
  if (typeof d.completed_total === 'number') {
    historyTotal = d.completed_total;
    updatePaginationUI();
  }
  maybeRefetchHistoryFromWS();

  // 失败数：从 d.completed（最近 100 条快照）数 error/timeout
  const failedCount = (d.completed || []).filter(r => r.status === 'error' || r.status === 'timeout').length;
  const retryAllCountEl = document.getElementById('retry-all-count');
  const retryAllBtn = document.getElementById('retry-all-btn');
  if (retryAllCountEl) retryAllCountEl.textContent = String(failedCount);
  if (retryAllBtn) retryAllBtn.disabled = (failedCount === 0);

  // Watched (P1-7: 新结构 + 排序)
  renderWatched(d.watched || {});

  // 磁盘空间显示 + 横幅
  updateDiskDisplay(d.disk_usage);
  updateDiskBanner(d.disk_usage);

  // F6: 重复下载队列
  updateDupQueue(d.duplicate_queue || [], d.duplicate_count || 0);

  // MD5 dedup toast
  updateToasts(d.pending_toasts || []);

  // 历史下载 jobs + 已监听频道下拉
  updateHistoryJobs(d.history_jobs || []);
  updateHcWatchedDropdown(d.watched || {});
}

// ── MD5 dedup toast ──────────────────────────────────────────────────────
function updateToasts(toasts) {
  const container = document.getElementById('toasts-container');
  if (!container) return;
  // 按 created_at 倒序，截最新 3 条
  const sorted = (toasts || []).slice()
    .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
    .slice(0, 3);
  container.innerHTML = sorted.map(renderToastCard).join('');
}

function renderToastCard(t) {
  const isFuid = t.trigger_source !== 'finish';
  const sizeText = t.size_mb > 0 ? (t.size_mb + ' MB') : '';
  const headerText = isFuid ? '⚠️ 检测到重复文件' : '⚠️ 已下载文件与历史重复';

  const body = '<div class="toast-meta">'
    + esc(t.filename || '(未知)') + (sizeText ? '  ·  ' + sizeText : '')
    + (t.source_label ? '  ·  ' + esc(t.source_label) : '')
    + '</div>'
    + '<div class="toast-meta" style="margin-top:4px">与以下文件内容相同：</div>'
    + '<div class="toast-meta">' + esc(t.matched_filename || '(未知)') + '</div>'
    + '<div class="toast-path" data-toast-id="' + esc(t.toast_id) + '" data-action="open-matched" title="点击打开所在文件夹">'
    + esc(t.matched_path || '') + '</div>'
    + '<div class="toast-meta" style="margin-top:4px">下载于 ' + esc(t.matched_finished_at || '-') + '</div>';

  let buttons;
  if (isFuid) {
    buttons = '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="queue">加入队列</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="skip" style="color:#ef9a9a">跳过下载</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="download" style="color:#81c784">直接下载</button>';
  } else {
    buttons = '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="open-matched">查看重复</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="skip" style="color:#ef9a9a">跳过</button>'
      + '<button class="btn btn-sm" data-toast-id="' + esc(t.toast_id) + '" data-action="keep">保留</button>';
  }

  return '<div class="toast-card" data-toast-id="' + esc(t.toast_id) + '">'
    + '<div class="toast-title">' + headerText + '</div>'
    + body
    + '<div class="toast-actions">' + buttons
    + '<span class="toast-countdown" data-expires="' + (t.expires_at_epoch || 0) + '">10s</span>'
    + '</div></div>';
}

function updateToastCountdowns() {
  const now = Date.now() / 1000;
  document.querySelectorAll('.toast-countdown').forEach(el => {
    const exp = parseFloat(el.dataset.expires || '0');
    const left = Math.max(0, Math.ceil(exp - now));
    el.textContent = left + 's';
    if (left <= 3) el.style.color = '#ef5350';
    else el.style.color = '#888';
  });
}
setInterval(updateToastCountdowns, 1000);

document.getElementById('toasts-container').addEventListener('click', async e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const tid = btn.dataset.toastId;
  const action = btn.dataset.action;
  const map = {
    'queue':        ['POST', '/api/toast/' + encodeURIComponent(tid) + '/queue'],
    'skip':         ['POST', '/api/toast/' + encodeURIComponent(tid) + '/skip'],
    'download':     ['POST', '/api/toast/' + encodeURIComponent(tid) + '/download'],
    'keep':         ['POST', '/api/toast/' + encodeURIComponent(tid) + '/keep'],
    'open-matched': ['POST', '/api/toast/' + encodeURIComponent(tid) + '/open-matched'],
  };
  const route = map[action];
  if (!route) return;
  if (btn.tagName === 'BUTTON') btn.disabled = true;
  try {
    const r = await apiFetch(route[1], {method: route[0]});
    if (!r.ok) {
      let j = {};
      try { j = await r.json(); } catch (e) {}
      if (action === 'open-matched') {
        alert('打开失败：原文件可能已被搬运 / 移动\\n' + (j.error || ''));
      } else if (r.status !== 404) {
        alert('操作失败：' + (j.error || r.status));
      }
      // 失败也移除卡片（除非是 open-matched，需保留让用户再尝试）
      if (action !== 'open-matched') {
        const card = document.querySelector('.toast-card[data-toast-id="' + tid + '"]');
        if (card) card.remove();
      }
    } else {
      // 成功 → 乐观移除（WS 推送会再校正）
      if (action !== 'open-matched') {
        const card = document.querySelector('.toast-card[data-toast-id="' + tid + '"]');
        if (card) card.remove();
      }
    }
  } catch (err) {
    // 网络异常忽略
  }
});

// ── F6 重复下载队列 ──────────────────────────────────────────────────────
let lastDupQueue = [];
let dupSectionVisible = false;
let dupSortMode = 'time';

function fmtIsoOrEpoch(v) {
  if (v === null || v === undefined || v === '') return '-';
  if (typeof v === 'number') {
    try {
      const d = new Date(v * 1000);
      return d.toLocaleString('zh-CN', {hour12: false});
    } catch(e) { return '-'; }
  }
  if (typeof v === 'string') {
    try {
      const d = new Date(v);
      if (!isNaN(d)) return d.toLocaleString('zh-CN', {hour12: false});
    } catch(e) {}
    return v;
  }
  return '-';
}

function sortDup(queue, mode) {
  const arr = queue.slice();
  if (mode === 'size') {
    arr.sort((a,b) => (b.size_mb || 0) - (a.size_mb || 0));
  } else {
    arr.sort((a,b) => (b.queued_at || '').localeCompare(a.queued_at || ''));
  }
  return arr;
}

function renderDupTable() {
  const wrap = document.getElementById('dup-table-wrap');
  const sorted = sortDup(lastDupQueue, dupSortMode);
  if (!sorted.length) {
    wrap.innerHTML = '<p class="empty">暂无待确认</p>';
    return;
  }
  let html = '<table><thead><tr>'
    + '<th>文件名</th><th>大小</th><th>来源</th><th>上次完成</th><th>状态</th><th>操作</th>'
    + '</tr></thead><tbody>';
  for (const d of sorted) {
    const dt = d.duplicate_type || '';
    const isContent = dt === 'fuid' || dt === 'md5';
    const matchedRow = isContent && d.matched_filename
      ? '<tr class="dup-matched-row"><td colspan="6" style="color:#888;font-size:.78rem;padding-left:24px;border-bottom:1px solid #161616">'
        + '内容与 <span style="color:#e0e0e0">' + esc(d.matched_filename) + '</span>'
        + (d.matched_path
            ? ' （<span class="dup-matched-path" data-path="' + esc(d.matched_path) + '" style="color:#5db;cursor:pointer;font-family:monospace">'
              + esc(d.matched_path) + '</span>）'
            : '')
        + (d.matched_finished_at ? '，下载于 ' + esc(d.matched_finished_at) : '')
        + '  ·  类型 ' + esc(dt)
        + '</td></tr>'
      : '';
    html += '<tr data-task-id="' + esc(d.task_id) + '">'
      + '<td>' + esc(d.filename || '(未知)') + '</td>'
      + '<td>' + (d.size_mb > 0 ? d.size_mb + ' MB' : '-') + '</td>'
      + '<td>' + esc(d.source_label || '') + '</td>'
      + '<td>' + esc(fmtIsoOrEpoch(d.last_downloaded_at)) + '</td>'
      + '<td>' + esc(d.previous_status || '') + '</td>'
      + '<td>'
      + '<button class="btn btn-sm dup-redownload" data-task-id="' + esc(d.task_id) + '" style="color:#81c784">重新下载</button> '
      + '<button class="btn btn-sm dup-ignore" data-task-id="' + esc(d.task_id) + '" style="color:#ef9a9a">忽略</button>'
      + '</td></tr>'
      + matchedRow;
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

function updateDupQueue(queue, count) {
  lastDupQueue = queue || [];
  document.getElementById('dup-count').textContent = String(count);
  document.getElementById('dup-section-count').textContent = count ? '(共 ' + count + ' 个)' : '';
  const btn = document.getElementById('dup-toggle-btn');
  if (count > 0) btn.style.background = '#4a3010', btn.style.color = '#ffd54f', btn.style.borderColor = '#ffd54f';
  else btn.style.background = '', btn.style.color = '#666', btn.style.borderColor = '';
  if (dupSectionVisible) renderDupTable();
}

document.getElementById('dup-toggle-btn').addEventListener('click', e => {
  e.stopPropagation();   // 防止冒泡到 dl-toggle 引发折叠
  dupSectionVisible = !dupSectionVisible;
  const sec = document.getElementById('dup-section');
  sec.style.display = dupSectionVisible ? '' : 'none';
  if (dupSectionVisible) renderDupTable();
});

document.getElementById('dup-sort').addEventListener('change', e => {
  dupSortMode = e.target.value;
  renderDupTable();
});

document.getElementById('dup-clear').addEventListener('click', async () => {
  if (!lastDupQueue.length) return;
  if (!confirm('清空所有 ' + lastDupQueue.length + ' 条待确认重复？')) return;
  const r = await apiFetch('/api/duplicate-queue', {method: 'DELETE'});
  if (!r.ok) alert('清空失败');
});

document.getElementById('dup-table-wrap').addEventListener('click', async e => {
  const rb = e.target.closest('.dup-redownload');
  if (rb) {
    const tid = rb.dataset.taskId;
    const entry = lastDupQueue.find(d => d.task_id === tid);
    const fname = entry ? (entry.filename || tid) : tid;
    if (!confirm('确认重新下载 ' + fname + ' ？')) return;
    rb.disabled = true;
    const r = await apiFetch('/api/duplicate-queue/' + encodeURIComponent(tid) + '/download', {method: 'POST'});
    const j = await r.json();
    if (!j.ok) {
      alert(j.error || '触发重新下载失败');
      rb.disabled = false;
    }
    return;
  }
  const ib = e.target.closest('.dup-ignore');
  if (ib) {
    ib.disabled = true;
    const r = await apiFetch('/api/duplicate-queue/' + encodeURIComponent(ib.dataset.taskId), {method: 'DELETE'});
    if (!r.ok) {
      alert('忽略失败');
      ib.disabled = false;
    }
    return;
  }
  // matched_path 点击 → /api/open（mover 已搬走则失败提示）
  const mp = e.target.closest('.dup-matched-path');
  if (mp) {
    const path = mp.dataset.path;
    if (!path) return;
    try {
      const r = await apiFetch('/api/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path}),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        alert('打开失败：原文件可能已被搬运 / 移动\\n' + (j.error || ''));
      }
    } catch (err) {
      alert('打开失败：' + err);
    }
  }
});

// ── 磁盘空间显示 + 横幅 ──────────────────────────────────────────────────────
function fmtBytesAuto(b) {
  if (!b && b !== 0) return '-';
  if (b >= 1024**3) return (b/1024**3).toFixed(1) + 'GB';
  if (b >= 1024**2) return (b/1024**2).toFixed(1) + 'MB';
  return Math.round(b) + 'B';
}

function updateDiskDisplay(disk) {
  const el = document.getElementById('dd-disk');
  if (!el) return;
  if (!disk || disk.checked_at === null) {
    el.textContent = '下载目录磁盘剩余 检测中…';
    el.style.color = '#888';
    return;
  }
  if (disk.error) {
    el.textContent = '磁盘检测失败：' + disk.error;
    el.style.color = '#ef5350';
    return;
  }
  const free = fmtBytesAuto(disk.free);
  const total = fmtBytesAuto(disk.total);
  const pct = disk.pct_free;
  el.textContent = '下载目录磁盘剩余 ' + free + ' / ' + total + '（' + pct.toFixed(1) + '%）';
  if (pct < 10)      el.style.color = '#ef5350';
  else if (pct < 20) el.style.color = '#ff9800';
  else               el.style.color = '#888';
}

function updateDiskBanner(disk) {
  const banner = document.getElementById('disk-banner');
  if (!banner) return;
  if (!disk || disk.checked_at === null || disk.error) {
    banner.style.display = 'none';
    return;
  }
  const pct = disk.pct_free;
  if (pct > 20) {
    [20, 10, 5, 0].forEach(t => localStorage.removeItem('disk_banner_ack_' + t));
    banner.style.display = 'none';
    return;
  }
  // 找命中的最严重阈值（数值最小者优先）
  const triggered = [0, 5, 10, 20].find(t => pct <= t);
  if (triggered === undefined) {
    banner.style.display = 'none';
    return;
  }
  if (localStorage.getItem('disk_banner_ack_' + triggered)) {
    banner.style.display = 'none';
    return;
  }
  const colors = {20: '#5a4a10', 10: '#5a3a10', 5: '#5a1010', 0: '#5a1010'};
  banner.style.background = colors[triggered];
  banner.style.color = '#fff';
  document.getElementById('disk-banner-msg').textContent =
    '⚠️ 磁盘空间不足 ' + pct.toFixed(1) + '%，剩余 ' + fmtBytesAuto(disk.free);
  banner.dataset.threshold = String(triggered);
  banner.style.display = 'block';
}

document.getElementById('disk-banner-close').onclick = function() {
  const t = document.getElementById('disk-banner').dataset.threshold;
  if (t !== undefined) localStorage.setItem('disk_banner_ack_' + t, '1');
  document.getElementById('disk-banner').style.display = 'none';
};

// ── P1-7 监听列表渲染与排序 ─────────────────────────────────────────────────
// 注意：wlSortBy / wlSortOrder / lastWatched 已在文件顶部声明（避免 TDZ）

function fwatchedTime(iso) {
  if (!iso) return '-';
  // ISO datetime → YYYY-MM-DD HH:MM
  return iso.slice(0, 16).replace('T', ' ');
}

function _watchedNameOf(rec) {
  return (typeof rec === 'object' && rec) ? (rec.name || '') : (rec || '');
}
function _watchedSinceOf(rec) {
  return (typeof rec === 'object' && rec) ? (rec.watched_since || '') : '';
}
function _watchedCountOf(rec) {
  return (typeof rec === 'object' && rec) ? (rec.task_count || 0) : 0;
}
function _watchedExemptOf(rec) {
  return (typeof rec === 'object' && rec) ? !!rec.exempt : false;
}

function sortWatchedEntries(entries) {
  const factor = wlSortOrder === 'asc' ? 1 : -1;
  if (wlSortBy === 'name') {
    return entries.slice().sort((a, b) =>
      _watchedNameOf(a[1]).localeCompare(_watchedNameOf(b[1])) * factor);
  }
  if (wlSortBy === 'watched_since') {
    return entries.slice().sort((a, b) =>
      _watchedSinceOf(a[1]).localeCompare(_watchedSinceOf(b[1])) * factor);
  }
  if (wlSortBy === 'task_count') {
    return entries.slice().sort((a, b) =>
      (_watchedCountOf(a[1]) - _watchedCountOf(b[1])) * factor);
  }
  // default：原始顺序，descend 时反转
  return wlSortOrder === 'asc' ? entries : entries.slice().reverse();
}

function _matchesSearch(cid, rec, query) {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const name = _watchedNameOf(rec) || '';
  return name.toLowerCase().includes(q) || cid.includes(q);
}

function renderWatched(watched) {
  lastWatched = watched;
  const wl = document.getElementById('wl');
  const allEntries = Object.entries(watched);

  // 完全空（未监听任何频道）
  if (!allEntries.length) {
    wl.innerHTML = '<p class="empty">监听列表为空</p>';
    document.getElementById('wl-search-info').style.display = 'none';
    return;
  }

  // 应用搜索过滤
  let entries = wlSearchQuery
    ? allEntries.filter(([cid, rec]) => _matchesSearch(cid, rec, wlSearchQuery))
    : allEntries;

  // 搜索信息条
  const info = document.getElementById('wl-search-info');
  if (wlSearchQuery) {
    info.style.display = '';
    info.textContent = '匹配 ' + entries.length + ' / 共 ' + allEntries.length;
  } else {
    info.style.display = 'none';
  }

  // 搜索 0 命中
  if (wlSearchQuery && !entries.length) {
    wl.innerHTML = '<p class="empty">没有找到匹配「' + esc(wlSearchQuery) + '」的频道</p>';
    return;
  }

  entries = sortWatchedEntries(entries);
  wl.innerHTML = entries.map(([id, rec]) => {
    const name   = _watchedNameOf(rec);
    const since  = _watchedSinceOf(rec);
    const count  = _watchedCountOf(rec);
    const exempt = _watchedExemptOf(rec);
    const exemptIcon  = exempt ? '🔔' : '🔕';
    const exemptColor = exempt ? '#ff9800' : '#666';
    const exemptTitle = exempt
      ? '全局暂停时此频道仍会监听，点击取消例外'
      : '全局暂停时此频道也会暂停，点击设为例外';
    // 暂停 + 例外 → 显示「监听中」徽章；其他状态不显示
    const pausedBadge = (lastPaused && exempt)
      ? '<span style="color:#66bb6a;font-size:.7rem;margin-right:6px" title="全局暂停时仍在监听">● 监听中</span>'
      : '';
    return '<div class="watch-row" data-id="'+esc(id)+'" '
         + 'style="display:flex;justify-content:space-between;align-items:center;'
         + 'gap:8px;padding:6px 8px;border-bottom:1px solid #1e1e1e;flex-wrap:wrap">'
      + '<div style="flex:1;min-width:0">'
      +   '<span style="font-weight:500">'+esc(name)+'</span>'
      +   '<span style="color:#666;font-size:.72rem;margin-left:6px">'+id+'</span>'
      + '</div>'
      + '<div style="display:flex;gap:10px;align-items:center;color:#888;font-size:.78rem;font-variant-numeric:tabular-nums">'
      +   pausedBadge
      +   '<span title="开始监听时间">📅 '+fwatchedTime(since)+'</span>'
      +   '<span title="累计触发的任务数">📊 '+count+' 个任务</span>'
      +   '<button class="btn btn-sm wl-exempt-btn" data-id="'+esc(id)+'" data-exempt="'+(exempt?'1':'0')+'" '
      +     'title="'+exemptTitle+'" style="padding:2px 6px;color:'+exemptColor+'">'+exemptIcon+'</button>'
      +   '<button class="btn btn-sm wl-reset-btn" data-id="'+esc(id)+'" '
      +     'title="清零该频道统计" style="padding:2px 6px">🔄</button>'
      +   '<button class="rm rm-watch-btn" data-id="'+esc(id)+'" '
      +     'title="取消监听">✕</button>'
      + '</div>'
      + '</div>';
  }).join('');
}

function updateWlSortBtn() {
  const btn = document.getElementById('wl-sort-order');
  btn.textContent = wlSortOrder === 'asc' ? '↑' : '↓';
}

// ── Event delegation（避免 inline onclick 的引号转义问题）────────────────────
document.getElementById('sbtn').addEventListener('click', doSearch);
document.getElementById('sq').addEventListener('keydown', e => { if(e.key==='Enter') doSearch(); });
document.getElementById('sr').addEventListener('click', e => {
  const btn = e.target.closest('.add-watch-btn');
  if (btn) addWatch(btn.dataset.id, btn.dataset.name, btn);
});
document.getElementById('wl').addEventListener('click', async e => {
  const removeBtn = e.target.closest('.rm-watch-btn');
  if (removeBtn) { removeWatch(removeBtn.dataset.id, removeBtn); return; }
  // P1-7 单行清零
  const resetBtn = e.target.closest('.wl-reset-btn');
  if (resetBtn) {
    const cid = resetBtn.dataset.id;
    resetBtn.disabled = true;
    const r = await apiFetch('/api/watch/' + encodeURIComponent(cid) + '/reset-stats', {method: 'POST'});
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      alert('清零失败：' + (j.error || r.status));
    }
    resetBtn.disabled = false;
    return;
  }
  // 例外频道切换
  const exemptBtn = e.target.closest('.wl-exempt-btn');
  if (exemptBtn) {
    const cid = exemptBtn.dataset.id;
    const newVal = exemptBtn.dataset.exempt !== '1';
    exemptBtn.disabled = true;
    const r = await apiFetch('/api/watch/' + encodeURIComponent(cid) + '/exempt', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({exempt: newVal}),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      alert('设置失败：' + (j.error || r.status));
      exemptBtn.disabled = false;
    }
    // 不主动 disabled=false：WS 推回新 watched 后整行重渲染
  }
});
document.getElementById('completed-wrap').addEventListener('click', async e => {
  const ob = e.target.closest('.open-file-btn, .open-dir-btn');
  if (ob) {
    ob.disabled = true;
    const r = await apiFetch('/api/open', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path: ob.dataset.path})});
    if (!r.ok) { const j = await r.json(); alert(j.error || '打开失败'); }
    ob.disabled = false;
    return;
  }
  const rb = e.target.closest('.retry-btn');
  if (rb) {
    rb.disabled = true; rb.textContent = '重试中…';
    const r = await apiFetch('/api/retry', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task_id: rb.dataset.taskId})});
    if (!r.ok) {
      const j = await r.json();
      alert(j.error || '重试失败');
      rb.disabled = false; rb.textContent = '重试';
    }
    return;
  }
  const db = e.target.closest('.del-rec-btn');
  if (db) {
    if (!confirm('确认删除这条记录？（不会删除磁盘文件）')) return;
    db.disabled = true;
    const r = await apiFetch('/api/completed/'+encodeURIComponent(db.dataset.taskId), {method:'DELETE'});
    if (!r.ok) { const j = await r.json(); alert(j.error || '删除失败'); db.disabled = false; }
    return;
  }
  const mg = e.target.closest('.move-grp-btn');
  if (mg) {
    openMoveGroupDialog(mg.dataset.gsKey, mg.dataset.folder);
    return;
  }
  // 多选 checkbox（行）
  const rcb = e.target.closest('.row-select-cb');
  if (rcb) {
    const tid = rcb.dataset.taskId;
    if (rcb.checked) selectedTaskIds.add(tid); else selectedTaskIds.delete(tid);
    if (lastCompleted) renderCompleted(lastCompleted);
    return;
  }
  // 全选 checkbox
  const acb = e.target.closest('#select-all-cb');
  if (acb) {
    if (acb.checked) for (const r of (lastCompleted || [])) selectedTaskIds.add(r.task_id);
    else selectedTaskIds.clear();
    if (lastCompleted) renderCompleted(lastCompleted);
    return;
  }
  // 批量操作按钮
  const bclear = e.target.closest('#bulk-clear-btn');
  if (bclear) {
    selectedTaskIds.clear();
    if (lastCompleted) renderCompleted(lastCompleted);
    return;
  }
  const bret = e.target.closest('#bulk-retry-btn');
  if (bret) {
    const targets = (lastCompleted || []).filter(r =>
      selectedTaskIds.has(r.task_id) && (r.status === 'error' || r.status === 'timeout')
    );
    if (!targets.length) { alert('选中项中没有可重试任务'); return; }
    if (!confirm('确认重试 ' + targets.length + ' 个任务？')) return;
    bret.disabled = true;
    let ok = 0, fail = 0;
    for (let i = 0; i < targets.length; i++) {
      bret.textContent = '重试中… ' + (i+1) + '/' + targets.length;
      try {
        const r = await apiFetch('/api/retry', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task_id: targets[i].task_id})});
        if (r.ok) ok++; else fail++;
      } catch(e) { fail++; }
    }
    selectedTaskIds.clear();
    alert('已重试：' + ok + ' 成功，' + fail + ' 失败');
    return;
  }
  const bdel = e.target.closest('#bulk-delete-btn');
  if (bdel) {
    const targets = Array.from(selectedTaskIds);
    if (!targets.length) return;
    if (!confirm('确认删除 ' + targets.length + ' 条记录？（不会删除磁盘文件）')) return;
    bdel.disabled = true;
    let ok = 0, fail = 0;
    for (let i = 0; i < targets.length; i++) {
      bdel.textContent = '删除中… ' + (i+1) + '/' + targets.length;
      try {
        const r = await apiFetch('/api/completed/' + encodeURIComponent(targets[i]), {method:'DELETE'});
        if (r.ok) ok++; else fail++;
      } catch(e) { fail++; }
    }
    selectedTaskIds.clear();
    alert('已删除：' + ok + ' 成功，' + fail + ' 失败');
  }
});

// ── F4B 移动文件夹对话框 ──────────────────────────────────────────────────
let _moveGsKey = '';
let _moveFolder = '';
async function openMoveGroupDialog(gs_key, folder) {
  _moveGsKey = gs_key;
  _moveFolder = folder;
  document.getElementById('movegrp-folder').textContent = '源文件夹：' + folder;
  document.getElementById('movegrp-input').value = '';
  document.getElementById('movegrp-error').textContent = '';
  // 加载历史路径
  try {
    const r = await apiFetch('/api/settings');
    if (r.ok) {
      const s = await r.json();
      const dl = document.getElementById('movegrp-history-dl');
      dl.innerHTML = (s.move_target_history || []).map(p => '<option value="'+esc(p)+'">').join('');
    }
  } catch(e) { /* ignore */ }
  document.getElementById('movegrp-mask').style.display = 'flex';
  setTimeout(() => document.getElementById('movegrp-input').focus(), 50);
}
function closeMoveGroupDialog() {
  document.getElementById('movegrp-mask').style.display = 'none';
  _moveGsKey = '';
  _moveFolder = '';
}
document.getElementById('movegrp-cancel').addEventListener('click', closeMoveGroupDialog);
document.getElementById('movegrp-mask').addEventListener('click', e => {
  if (e.target.id === 'movegrp-mask') closeMoveGroupDialog();
});
document.getElementById('movegrp-confirm').addEventListener('click', async () => {
  const target = document.getElementById('movegrp-input').value.trim();
  const errEl = document.getElementById('movegrp-error');
  if (!target) {
    errEl.textContent = '请输入目标父目录';
    return;
  }
  if (!_moveGsKey) {
    errEl.textContent = '内部错误：缺少 gs_key';
    return;
  }
  const btn = document.getElementById('movegrp-confirm');
  btn.disabled = true;
  errEl.textContent = '提交中…';
  errEl.style.color = '#888';
  try {
    const r = await apiFetch('/api/history/move-group', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({gs_key: _moveGsKey, target_dir: target}),
    });
    const j = await r.json();
    if (j.ok) {
      const msg = j.already_moved
        ? '已搬运过（清理 ' + (j.removed_completed || 0) + ' 条记录）'
        : '已提交搬运到：' + j.target_dir + '\\nmover 完成后会自动从历史移除该组';
      closeMoveGroupDialog();
      alert(msg);
      // 刷新设置（更新历史下拉）
      if (typeof loadPathSettings === 'function') loadPathSettings();
    } else {
      errEl.textContent = j.error || '提交失败';
      errEl.style.color = '#ef5350';
    }
  } catch (e) {
    errEl.textContent = '请求失败：' + e;
    errEl.style.color = '#ef5350';
  } finally {
    btn.disabled = false;
  }
});
document.getElementById('clear-btn').addEventListener('click', async () => {
  if (!confirm('确认清空所有已完成记录？（不会删除磁盘文件）')) return;
  const btn = document.getElementById('clear-btn');
  btn.disabled = true;
  const r = await apiFetch('/api/completed/clear', {method:'POST'});
  if (!r.ok) { alert('清空失败'); }
  btn.disabled = false;
});
document.getElementById('retry-all-btn').addEventListener('click', async () => {
  const cnt = parseInt(document.getElementById('retry-all-count').textContent || '0');
  if (cnt === 0) return;
  if (!confirm('确认重试全部 ' + cnt + ' 个失败任务？\\n（任务会立即排队下载，受连接预算 MAX_TOTAL_CONNECTIONS 自然限流）')) return;
  const btn = document.getElementById('retry-all-btn');
  btn.disabled = true;
  const original = btn.innerHTML;
  btn.innerHTML = '提交中…';
  try {
    const r = await apiFetch('/api/retry-all-failed', {method: 'POST'});
    const j = await r.json();
    if (j.ok) {
      let msg = '已排队 ' + j.queued + ' / ' + j.total + ' 个';
      if (j.skipped && j.skipped.length) {
        msg += '\\n跳过 ' + j.skipped.length + ' 个（前 5 个）：\\n';
        msg += j.skipped.slice(0, 5).map(s => '  ' + s.task_id + ': ' + s.error).join('\\n');
      }
      alert(msg);
    } else {
      alert(j.error || '失败');
    }
  } catch(e) {
    alert('请求失败：' + e);
  } finally {
    btn.innerHTML = original;
    // 不主动 disabled=false：等 WS 推回新的 failedCount
  }
});
document.getElementById('clear-done-btn').addEventListener('click', async () => {
  if (!confirm('只清除已成功的下载记录？\\n失败 / 超时记录会保留。\\n（不会删除磁盘文件）')) return;
  const btn = document.getElementById('clear-done-btn');
  btn.disabled = true;
  const r = await apiFetch('/api/history/done', {method:'DELETE'});
  if (r.ok) {
    const j = await r.json();
    alert('已清除 ' + j.removed + ' 条 done 记录，保留 ' + j.remaining + ' 条');
  } else {
    alert('清除失败');
  }
  btn.disabled = false;
});
document.getElementById('al').addEventListener('click', async e => {
  const detBtn = e.target.closest('.detail-btn');
  if (detBtn) {
    const tid = detBtn.dataset.taskId;
    if (expandedTasks.has(tid)) expandedTasks.delete(tid);
    else expandedTasks.add(tid);
    renderActiveList(lastActive);
    return;
  }
  const pauseBtn = e.target.closest('.pause-btn');
  if (pauseBtn) {
    pauseBtn.disabled = true;
    await apiFetch('/api/task/'+encodeURIComponent(pauseBtn.dataset.taskId)+'/pause', {method:'POST'});
    pauseBtn.disabled = false;
    return;
  }
  const resumeBtn = e.target.closest('.resume-btn');
  if (resumeBtn) {
    resumeBtn.disabled = true;
    await apiFetch('/api/task/'+encodeURIComponent(resumeBtn.dataset.taskId)+'/resume', {method:'POST'});
    resumeBtn.disabled = false;
    return;
  }
  const cancelBtn = e.target.closest('.cancel-btn');
  if (cancelBtn) {
    if (!confirm('确认终止该下载任务？已下载的临时文件将被丢弃。')) return;
    cancelBtn.disabled = true;
    await apiFetch('/api/task/'+encodeURIComponent(cancelBtn.dataset.taskId)+'/cancel', {method:'POST'});
    cancelBtn.disabled = false;
  }
});
document.getElementById('mode-btn').addEventListener('click', () => {
  viewMode = viewMode === 'list' ? 'group' : 'list';
  document.getElementById('mode-btn').textContent = viewMode === 'list' ? '按组分类' : '列表模式';
  renderCompleted(lastCompleted);
});

// ── P1-8: 已完成区域分页/排序绑定 ───────────────────────────────────────────
document.getElementById('history-sort-by').value = historySortBy;
updateHistorySortBtn();
document.getElementById('page-size').value = historyPageSize;

document.getElementById('history-sort-by').addEventListener('change', e => {
  historySortBy = e.target.value;
  localStorage.setItem('history_sort_by', historySortBy);
  historyCurrentPage = 0;
  fetchHistory();
});
document.getElementById('history-sort-order').addEventListener('click', () => {
  historySortOrder = historySortOrder === 'asc' ? 'desc' : 'asc';
  localStorage.setItem('history_sort_order', historySortOrder);
  updateHistorySortBtn();
  historyCurrentPage = 0;
  fetchHistory();
});
document.getElementById('page-size').addEventListener('change', e => {
  historyPageSize = parseInt(e.target.value);
  localStorage.setItem('history_page_size', historyPageSize);
  historyCurrentPage = 0;
  fetchHistory();
});
document.getElementById('page-prev').addEventListener('click', () => {
  if (historyCurrentPage > 0) {
    historyCurrentPage--;
    fetchHistory();
  }
});
document.getElementById('page-next').addEventListener('click', () => {
  const totalPages = Math.ceil(historyTotal / historyPageSize);
  if (historyCurrentPage < totalPages - 1) {
    historyCurrentPage++;
    fetchHistory();
  }
});
document.getElementById('refresh-btn').addEventListener('click', fetchHistory);

// 初次加载
fetchHistory();

// ── WebSocket + 轮询降级 ──────────────────────────────────────────────────────
const dot = document.getElementById('dot'), st = document.getElementById('st');
let polling = false;

function startPolling() {
  if (polling) return;
  polling = true;
  dot.className = 'dot on'; st.textContent = '已连接（轮询）';
  (async function loop() {
    while (polling) {
      try {
        const r = await apiFetch('/api/state');
        render(await r.json());
      } catch(e) { dot.className='dot off'; st.textContent='请求失败，重试中…'; }
      await new Promise(r => setTimeout(r, 2000));
    }
  })();
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = proto + '://' + location.host + '/ws' + (API_KEY ? ('?key=' + encodeURIComponent(API_KEY)) : '');
  const ws = new WebSocket(wsUrl);
  const timer = setTimeout(() => { ws.close(); startPolling(); }, 5000);
  ws.onopen = () => {
    clearTimeout(timer);
    polling = false;
    dot.className='dot on'; st.textContent='已连接（WebSocket）';
  };
  ws.onmessage = e => render(JSON.parse(e.data));
  ws.onclose = () => {
    clearTimeout(timer);
    if (!polling) {
      dot.className='dot off'; st.textContent='已断开，3秒后重连…';
      setTimeout(connect, 3000);
    }
  };
  ws.onerror = () => ws.close();
}
connect();

// ── 历史消息下载 (history-pull) ─────────────────────────────────────────────

let lastHistoryJobs = [];
const expandedJobs = new Set();   // C 场景展开的 job_id
const cachedScanResults = {};      // job_id → 全量 scan_results（按需 GET）

function updateHistoryJobs(jobs) {
  lastHistoryJobs = jobs || [];
  const ab = document.getElementById('hist-ab-jobs');
  const c  = document.getElementById('hist-c-jobs');
  if (!ab || !c) return;
  const abJobs = lastHistoryJobs.filter(j => j.scene === 'A' || j.scene === 'B');
  const cJobs  = lastHistoryJobs.filter(j => j.scene === 'C');
  ab.innerHTML = abJobs.length ? abJobs.map(renderHistJobCard).join('') : '';
  c.innerHTML  = cJobs.length  ? cJobs.map(renderHistJobCard).join('')  : '';
  // 展开的 C job 渲染 scan_results 表
  for (const j of cJobs) {
    if (expandedJobs.has(j.job_id)) {
      _renderScanResultsTable(j);
    }
  }
}

function renderHistJobCard(j) {
  const colors = {
    running: '#4fc3f7', paused: '#ffd54f', done: '#66bb6a',
    error: '#ef5350', ready_for_selection: '#03a9f4',
  };
  const color = colors[j.status] || '#888';
  const isC = j.scene === 'C';
  const showResults = isC && (j.status === 'ready_for_selection' || j.status === 'paused' || j.status === 'done')
                       && (j.scan_results_count > 0);
  const errorRow = j.error_msg
    ? '<div style="color:#ef5350;font-size:.75rem;margin-top:4px">' + esc(j.error_msg) + '</div>'
    : '';

  let buttons = '';
  if (j.status === 'running') {
    buttons += '<button class="btn btn-sm hp-stop" data-job-id="' + esc(j.job_id) + '">停止</button>';
  }
  if (['paused','done','error','ready_for_selection'].includes(j.status)) {
    buttons += '<button class="btn btn-sm hp-rescan" data-job-id="' + esc(j.job_id) + '">重新扫描</button>';
  }
  if (j.status === 'paused') {
    buttons += '<button class="btn btn-sm hp-resume" data-job-id="' + esc(j.job_id) + '" data-scene="' + esc(j.scene) + '" data-chat="' + j.chat_id + '">继续扫描</button>';
  }
  buttons += '<button class="btn btn-sm hp-delete" data-job-id="' + esc(j.job_id) + '" style="color:#ef9a9a">删除</button>';

  let resultsRow = '';
  if (showResults) {
    const expanded = expandedJobs.has(j.job_id);
    resultsRow = '<button class="btn btn-sm hp-toggle-results" data-job-id="' + esc(j.job_id) + '">'
      + (expanded ? '收起' : '展开') + ' 扫描结果 (' + j.scan_results_count + ')</button>'
      + '<div id="hp-results-' + esc(j.job_id) + '" style="margin-top:8px"></div>';
  }

  return '<div class="hist-job-card" data-job-id="' + esc(j.job_id) + '" '
    + 'style="background:#161616;border:1px solid #2a2a2a;border-radius:6px;padding:10px;margin-bottom:10px">'
    + '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
    +   '<div>'
    +     '<span style="color:' + color + ';font-weight:500">[' + esc(j.scene) + '/' + esc(j.status) + ']</span> '
    +     '<span style="color:#e0e0e0">' + esc(j.chat_name || '') + '</span> '
    +     '<span style="color:#666;font-size:.72rem">' + j.chat_id + '</span>'
    +   '</div>'
    +   '<div style="display:flex;gap:4px">' + buttons + '</div>'
    + '</div>'
    + '<div style="color:#888;font-size:.78rem;margin-top:6px;font-variant-numeric:tabular-nums">'
    +   '已扫描 <b>' + j.total_scanned + '</b> · '
    +   '排队 <b>' + j.total_queued + '</b> · '
    +   '跳过 <b>' + j.total_skipped + '</b>'
    +   '（其中重复 ' + (j.total_duplicates || 0) + '）· '
    +   '断点 last_seen=' + (j.last_seen_id || 0)
    + '</div>'
    + errorRow
    + (resultsRow ? '<div style="margin-top:8px">' + resultsRow + '</div>' : '')
    + '</div>';
}

async function _fetchScanResults(job_id) {
  try {
    const r = await apiFetch('/api/history-pull/jobs?include=scan_results&job_id=' + encodeURIComponent(job_id));
    if (!r.ok) return;
    const j = await r.json();
    if (j.ok && j.job) {
      cachedScanResults[job_id] = j.job.scan_results || [];
      _renderScanResultsTable({job_id, scan_results_count: cachedScanResults[job_id].length});
    }
  } catch (e) { /* ignore */ }
}

function _renderScanResultsTable(jobSummary) {
  const wrap = document.getElementById('hp-results-' + jobSummary.job_id);
  if (!wrap) return;
  const results = cachedScanResults[jobSummary.job_id];
  if (!results) {
    wrap.innerHTML = '<p class="empty">加载中…</p>';
    _fetchScanResults(jobSummary.job_id);
    return;
  }
  const total = results.length;
  if (!total) {
    wrap.innerHTML = '<p class="empty">无结果</p>';
    return;
  }
  let html = '<div style="margin-bottom:6px">'
    + '<button class="btn btn-sm hp-select-all" data-job-id="' + esc(jobSummary.job_id) + '">全选</button> '
    + '<button class="btn btn-sm hp-select-none" data-job-id="' + esc(jobSummary.job_id) + '">全不选</button> '
    + '<button class="btn btn-sm hp-select-non-dup" data-job-id="' + esc(jobSummary.job_id) + '">仅选未重复</button> '
    + '<button class="btn btn-sm hp-download-selected" data-job-id="' + esc(jobSummary.job_id) + '" style="color:#81c784">下载选中</button>'
    + '</div>'
    + '<div style="max-height:400px;overflow-y:auto">'
    + '<table style="width:100%;font-size:.78rem">'
    + '<thead><tr><th></th><th>文件名</th><th>大小</th><th>时间</th><th>类型</th></tr></thead><tbody>';
  results.forEach((r, i) => {
    const dupTag = r.duplicate
      ? '<span style="background:#3a2a10;color:#ffb74d;padding:1px 5px;border-radius:3px;font-size:.7rem" title="' + esc(r.matched_filename || '') + '">已下载</span>'
      : '';
    html += '<tr style="' + (r.duplicate ? 'background:#1f1810' : '') + '">'
      + '<td><input type="checkbox" class="hp-result-cb" data-job-id="' + esc(jobSummary.job_id) + '" data-mid="' + r.message_id + '" ' + (r.selected ? 'checked' : '') + '></td>'
      + '<td>' + esc(r.filename || '') + '</td>'
      + '<td>' + (r.size_mb > 0 ? r.size_mb + ' MB' : '-') + '</td>'
      + '<td>' + esc((r.date || '').slice(0, 16).replace('T', ' ')) + '</td>'
      + '<td>' + dupTag + '</td>'
      + '</tr>';
  });
  html += '</tbody></table></div>';
  wrap.innerHTML = html;
}

function updateHcWatchedDropdown(watched) {
  const sel = document.getElementById('hc-watched-list');
  if (!sel) return;
  const cur = sel.value;
  const entries = Object.entries(watched);
  sel.innerHTML = '<option value="">— 从已监听频道选择 —</option>'
    + entries.map(([cid, rec]) => {
        const name = (typeof rec === 'object' && rec) ? (rec.name || '') : (rec || '');
        return '<option value="' + esc(cid) + '">' + esc(name) + ' [' + cid + ']</option>';
      }).join('');
  if (cur) sel.value = cur;
}

// ── 按钮事件：D 单条 ────────────────────────────────────────────
document.getElementById('md-go').addEventListener('click', async () => {
  const cid = document.getElementById('md-cid').value.trim();
  const mid = document.getElementById('md-mid').value.trim();
  const result = document.getElementById('md-result');
  if (!cid || !mid) { result.textContent = '请填 chat_id 和 message_id'; result.style.color='#ef5350'; return; }
  result.textContent = '提交中…'; result.style.color='#888';
  const r = await apiFetch('/api/download', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({chat_id: parseInt(cid), message_id: parseInt(mid)})
  });
  const j = await r.json();
  if (j.ok) {
    if (j.duplicate_pending) {
      result.textContent = '已检测重复，请看右下角 toast'; result.style.color='#ffd54f';
    } else {
      result.textContent = '已排队：' + (j.filename || '');
      result.style.color = '#66bb6a';
    }
  } else {
    result.textContent = j.error || '失败';
    result.style.color = '#ef5350';
  }
});

// ── 按钮事件：A 全频道 ────────────────────────────────────────
document.getElementById('ha-go').addEventListener('click', async () => {
  const chat = document.getElementById('ha-chat').value.trim();
  const result = document.getElementById('ha-result');
  if (!chat) { result.textContent='请填频道'; result.style.color='#ef5350'; return; }
  result.textContent = '创建中…'; result.style.color='#888';
  await _hpStart('A', chat, {}, result);
});

// ── 按钮事件：B 范围 ────────────────────────────────────────
document.querySelectorAll('input[name="hb-mode"]').forEach(r => {
  r.addEventListener('change', () => {
    const mode = document.querySelector('input[name="hb-mode"]:checked').value;
    document.getElementById('hb-id-block').style.display = (mode === 'id') ? 'flex' : 'none';
    document.getElementById('hb-date-block').style.display = (mode === 'date') ? 'flex' : 'none';
  });
});
document.getElementById('hb-go').addEventListener('click', async () => {
  const chat = document.getElementById('hb-chat').value.trim();
  const mode = document.querySelector('input[name="hb-mode"]:checked').value;
  const result = document.getElementById('hb-result');
  if (!chat) { result.textContent='请填频道'; result.style.color='#ef5350'; return; }
  const extra = {filter_type: mode};
  if (mode === 'id') {
    const min = document.getElementById('hb-min-id').value.trim();
    const max = document.getElementById('hb-max-id').value.trim();
    if (!min && !max) { result.textContent='请填至少一个 ID'; result.style.color='#ef5350'; return; }
    if (min) extra.min_id = parseInt(min);
    if (max) extra.max_id = parseInt(max);
  } else {
    const min = document.getElementById('hb-min-date').value;
    const max = document.getElementById('hb-max-date').value;
    if (!min && !max) { result.textContent='请填至少一个日期'; result.style.color='#ef5350'; return; }
    if (min) extra.min_date = new Date(min).toISOString();
    if (max) extra.max_date = new Date(max).toISOString();
  }
  result.textContent='创建中…'; result.style.color='#888';
  await _hpStart('B', chat, extra, result);
});

// ── 按钮事件：C 遗漏补下 ────────────────────────────────────
document.getElementById('hc-watched-list').addEventListener('change', e => {
  if (e.target.value) document.getElementById('hc-chat').value = e.target.value;
});
document.getElementById('hc-go').addEventListener('click', async () => {
  const chat = document.getElementById('hc-chat').value.trim();
  const result = document.getElementById('hc-result');
  if (!chat) { result.textContent='请填频道'; result.style.color='#ef5350'; return; }
  result.textContent='创建中…'; result.style.color='#888';
  await _hpStart('C', chat, {}, result);
});

async function _hpStart(scene, chat, extra, resultEl) {
  const body = Object.assign({scene, chat}, extra);
  let r = await apiFetch('/api/history-pull/start', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
  });
  let j = await r.json();
  if (r.status === 409 && j.existing_job_id) {
    if (confirm('已存在同频道同 scene 的 job。确定→新建一个；取消→续上原 job。')) {
      r = await apiFetch('/api/history-pull/start', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(Object.assign({}, body, {force: true})),
      });
    } else {
      r = await apiFetch('/api/history-pull/start', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(Object.assign({}, body, {resume: true})),
      });
    }
    j = await r.json();
  }
  if (j.ok) {
    resultEl.textContent = '✅ job 已创建：' + (j.job_id || '').slice(0, 8);
    resultEl.style.color = '#66bb6a';
  } else {
    resultEl.textContent = j.error || '失败';
    resultEl.style.color = '#ef5350';
  }
}

// ── job 卡片按钮事件代理 ──────────────────────────────────────
function _hpJobsClickHandler(e) {
  const stop = e.target.closest('.hp-stop');
  if (stop) return _hpAction(stop.dataset.jobId, 'stop');
  const rescan = e.target.closest('.hp-rescan');
  if (rescan) {
    if (!confirm('重新扫描会清除断点和扫描结果，确定？')) return;
    return _hpAction(rescan.dataset.jobId, 'rescan');
  }
  const resume = e.target.closest('.hp-resume');
  if (resume) {
    return _hpResume(resume.dataset.jobId, resume.dataset.scene, resume.dataset.chat);
  }
  const del = e.target.closest('.hp-delete');
  if (del) {
    if (!confirm('删除该 job 记录？已经在下载的任务不受影响。')) return;
    return _hpDelete(del.dataset.jobId);
  }
  const tog = e.target.closest('.hp-toggle-results');
  if (tog) {
    const jid = tog.dataset.jobId;
    if (expandedJobs.has(jid)) expandedJobs.delete(jid);
    else { expandedJobs.add(jid); delete cachedScanResults[jid]; }
    updateHistoryJobs(lastHistoryJobs);
    return;
  }
  const sa = e.target.closest('.hp-select-all');
  if (sa) {
    document.querySelectorAll('.hp-result-cb[data-job-id="' + sa.dataset.jobId + '"]').forEach(cb => cb.checked = true);
    return;
  }
  const sn = e.target.closest('.hp-select-none');
  if (sn) {
    document.querySelectorAll('.hp-result-cb[data-job-id="' + sn.dataset.jobId + '"]').forEach(cb => cb.checked = false);
    return;
  }
  const sd = e.target.closest('.hp-select-non-dup');
  if (sd) {
    const jid = sd.dataset.jobId;
    const results = cachedScanResults[jid] || [];
    document.querySelectorAll('.hp-result-cb[data-job-id="' + jid + '"]').forEach(cb => {
      const mid = parseInt(cb.dataset.mid);
      const r = results.find(x => x.message_id === mid);
      cb.checked = r && !r.duplicate;
    });
    return;
  }
  const dl = e.target.closest('.hp-download-selected');
  if (dl) return _hpDownloadSelected(dl.dataset.jobId);
}
document.getElementById('hist-ab-jobs').addEventListener('click', _hpJobsClickHandler);
document.getElementById('hist-c-jobs').addEventListener('click', _hpJobsClickHandler);

async function _hpAction(jobId, action) {
  const r = await apiFetch('/api/history-pull/' + encodeURIComponent(jobId) + '/' + action, {method:'POST'});
  if (!r.ok) {
    const j = await r.json().catch(()=>({}));
    alert((action === 'stop' ? '停止失败：' : '操作失败：') + (j.error || r.status));
  }
}
async function _hpResume(jobId, scene, chat) {
  const r = await apiFetch('/api/history-pull/start', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({scene, chat, resume: true})
  });
  if (!r.ok) {
    const j = await r.json().catch(()=>({}));
    alert('恢复失败：' + (j.error || r.status));
  }
}
async function _hpDelete(jobId) {
  const r = await apiFetch('/api/history-pull/' + encodeURIComponent(jobId), {method:'DELETE'});
  if (!r.ok) {
    const j = await r.json().catch(()=>({}));
    alert('删除失败：' + (j.error || r.status));
  } else {
    delete cachedScanResults[jobId];
    expandedJobs.delete(jobId);
  }
}
async function _hpDownloadSelected(jobId) {
  const checked = Array.from(document.querySelectorAll('.hp-result-cb[data-job-id="' + jobId + '"]:checked'));
  if (!checked.length) { alert('请先勾选要下载的文件'); return; }
  if (!confirm('启动 ' + checked.length + ' 个文件的下载？')) return;
  const message_ids = checked.map(cb => parseInt(cb.dataset.mid));
  const r = await apiFetch('/api/history-pull/' + encodeURIComponent(jobId) + '/download-selected', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({message_ids})
  });
  const j = await r.json();
  if (j.ok) {
    alert('已排队 ' + j.queued + ' 个下载');
    delete cachedScanResults[jobId];   // 强制下次拉取（selected 字段更新）
  } else {
    alert(j.error || '失败');
  }
}
</script>
<button class="scroll-top-btn" title="回到顶部" onclick="window.scrollTo({top:0,behavior:'smooth'})">↑</button>
</body>
</html>"""
