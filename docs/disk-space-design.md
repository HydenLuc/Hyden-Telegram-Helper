# 磁盘空间显示与通知设计

> **状态**：✅ 已实现

## 目标

在 dashboard 卡片和 downloader 页面显示 `DOWNLOAD_DIR` 所在分区的磁盘剩余空间；磁盘紧张时通过 Telegram + 页面横幅双通道告警，避免下载到把磁盘塞满。

## 架构总览

```
独立 60s 周期任务 (downloader/disk_monitor.py)
    │
    ├─ shutil.disk_usage(config.DOWNLOAD_DIR)
    ├─ 写入 state.disk_usage（dict）
    └─ 阈值判定 → notify_disk_warning + 维护 disk_alert_sent flags
                   └─ 通过 common/disk_notify.py 发 Telegram

/api/status 与 WebSocket payload
    └─ 只读取 state.disk_usage 字段（不副作用、不计算）

前端
    ├─ 始终显示磁盘条（dashboard 卡片 + downloader 设置区）
    └─ 阈值横幅由前端独立判断（基于 disk_usage.pct_free）
        └─ dismiss 状态写入 localStorage（per-threshold per-browser）
```

**关键原则**：阈值检查只在周期任务里跑一次，HTTP 请求处理器不触发副作用。

## 数据结构

### 后端 state（`downloader/state.py` 新增）

```python
disk_usage: dict = {
    "free":     0,           # bytes
    "total":    0,           # bytes
    "pct_free": 0.0,         # 0.0 - 100.0
    "checked_at": None,      # ISO timestamp，None 表示尚未检测过
    "error":    None,        # str | None，DOWNLOAD_DIR 不可访问时记录
}
```

由 `disk_monitor` 任务每 60 秒覆盖；初始全零，前端遇到 `checked_at == None` 显示「检测中」。

### 持久化 flag（`downloader_settings.json` 已有 SettingsStore）

新增字段：

```json
{
  "disk_alert_sent": {
    "20": false,
    "10": false,
    "5":  false,
    "0":  false
  }
}
```

- 仅控制 Telegram 是否要再发同阈值通知
- 与前端横幅 dismiss 状态**完全分离**

### 前端 localStorage（per-browser）

```
disk_banner_ack_20  → "1" 表示已 dismiss
disk_banner_ack_10
disk_banner_ack_5
disk_banner_ack_0
```

`pct_free > 20` 时前端把这 4 个 key 一起清空（与后端 reset 同步）。

## 后端实现

### 新模块 `downloader/disk_monitor.py`

```python
async def disk_check_loop():
    while True:
        await _check_once()
        await asyncio.sleep(60)

async def _check_once():
    try:
        usage = shutil.disk_usage(config.DOWNLOAD_DIR)
        free, total = usage.free, usage.total
        pct = (free / total * 100) if total else 0.0
        state.disk_usage = {
            "free": free, "total": total,
            "pct_free": round(pct, 2),
            "checked_at": datetime.now().isoformat(),
            "error": None,
        }
        await _maybe_notify(pct)
    except Exception as e:
        state.disk_usage = {
            "free": 0, "total": 0, "pct_free": 0.0,
            "checked_at": datetime.now().isoformat(),
            "error": f"{type(e).__name__}: {e}",
        }
```

`_maybe_notify(pct)` 逻辑：

```python
THRESHOLDS = [20, 10, 5, 0]   # 高 → 低，显式声明

def _maybe_notify(pct):
    settings = storage.load_settings()
    flags = settings.setdefault("disk_alert_sent", {"20":F,"10":F,"5":F,"0":F})

    # reset：恢复到 20% 以上 → 4 个标志全清
    if pct > 20 and any(flags.values()):
        for k in flags: flags[k] = False
        storage.save_settings(settings)
        return

    # 命中：每个未发过的阈值都发一次（多阈值同时触发会发多条）
    for t in THRESHOLDS:
        if pct <= t and not flags[str(t)]:
            await notify_disk_warning(pct, free, total, threshold=t)
            flags[str(t)] = True
    storage.save_settings(settings)
```

### Telegram 通知 `common/disk_notify.py`（新文件）

复用 `common/crash_notify.py` 的 Bot API / Telethon fallback 模式，但导出新函数：

```python
async def notify_disk_warning(pct_free: float, free: int, total: int, threshold: int):
    """Telegram 告警。失败静默（写日志），不阻塞主流程。"""
    msg = (
        f"⚠️ 磁盘空间不足 {pct_free:.1f}%\n"
        f"剩余 {_fmt_bytes(free)} / {_fmt_bytes(total)}\n"
        f"路径：{config.DOWNLOAD_DIR}\n"
        f"阈值：{threshold}%"
    )
    # ... 发送（参考 crash_notify.notify_crash 的实现）

def _fmt_bytes(b: int) -> str:
    if b >= 1024**3: return f"{b/1024**3:.1f}GB"
    if b >= 1024**2: return f"{b/1024**2:.1f}MB"
    return f"{b}B"
```

不复用 `notify_crash` 是因为语义和图标不同（崩溃 vs 警告），但内部传输逻辑完全可以抽（实际开发时可考虑提取共用底层 `_send_via_bot_api / _send_via_telethon`）。

### 启动入口

`bot.py` 在 unzipper 启动后追加：

```python
from downloader.disk_monitor import disk_check_loop
asyncio.create_task(disk_check_loop())
```

不放进 `_broadcast_loop` 因为周期不同（broadcast 0.5s vs disk 60s）。

### `/api/status` 字段

`downloader/web/api.py:_api_status` 返回值新增：

```python
"disk_usage": state.disk_usage,
```

`downloader/web/websocket.py:_build_state` 同步加：

```python
"disk_usage": state.disk_usage,
```

**只读，不触发副作用**。

## 前端实现

### Dashboard downloader 卡片

`dashboard/templates.py`，downloader 卡片正文新增一行：

```
磁盘：12.4GB / 256GB （4.8%）
```

- `pct_free < 20` 时数字标红 `color: #ef5350`
- `pct_free < 10` 时整行加 `background: #2a1010`
- `error != null` 时显示「磁盘检测失败：{error}」

数据来源：dashboard 现有 `/api/overview` 已经聚合 downloader 字段，需确认是否传 `disk_usage`（如未传则在 dashboard 后端 proxy 时透传）。

### Downloader 页面设置区

`downloader/web/templates.py` 路径设置区下方新增一行：

```html
<div id="dd-disk" class="muted">下载目录磁盘剩余 12.4GB / 256GB</div>
```

显示规则同上（红/黄/橙边距）。

### 横幅

`downloader/web/templates.py` `<body>` 顶部加：

```html
<div id="disk-banner" style="display:none;position:fixed;top:0;left:0;right:0;
     padding:12px 20px;text-align:center;font-weight:500;z-index:1000">
  <span id="disk-banner-msg"></span>
  <button id="disk-banner-close" style="margin-left:16px">确认</button>
</div>
```

JS 逻辑（每次 WS 推送或轮询都跑一遍）：

```js
function updateDiskBanner(disk_usage) {
  if (!disk_usage || disk_usage.error || disk_usage.checked_at === null) return;
  const pct = disk_usage.pct_free;
  if (pct > 20) {
    // 恢复：清所有 dismiss
    [20,10,5,0].forEach(t => localStorage.removeItem('disk_banner_ack_'+t));
    document.getElementById('disk-banner').style.display = 'none';
    return;
  }
  // 找到当前命中的最严重阈值
  const triggered = [0,5,10,20].find(t => pct <= t);  // 0 最优先（最红）
  if (localStorage.getItem('disk_banner_ack_'+triggered)) {
    document.getElementById('disk-banner').style.display = 'none';
    return;
  }
  // 显示横幅
  const colors = {20:'#5a4a10', 10:'#5a3010', 5:'#5a1010', 0:'#5a1010'};
  const banner = document.getElementById('disk-banner');
  banner.style.background = colors[triggered];
  banner.style.color = '#fff';
  document.getElementById('disk-banner-msg').textContent =
    `⚠️ 磁盘空间不足 ${pct.toFixed(1)}%，剩余 ${fmtBytes(disk_usage.free)}`;
  banner.dataset.threshold = triggered;
  banner.style.display = 'block';
}

document.getElementById('disk-banner-close').onclick = () => {
  const t = document.getElementById('disk-banner').dataset.threshold;
  localStorage.setItem('disk_banner_ack_'+t, '1');
  document.getElementById('disk-banner').style.display = 'none';
};
```

`fmtBytes`：`>=1GB` 显示 GB（一位小数）；`<1GB` 显示 MB。

## 单位与格式约定

- `free / total` 始终在前端做单位换算，后端只送 bytes
- `pct_free` 后端已 `round(_, 2)`，前端 `.toFixed(1)` 显示
- `阈值` 字段（Telegram 通知）显示为整数百分比

## 边界 case

| 场景 | 处理 |
|------|------|
| `DOWNLOAD_DIR` 不存在或挂载断开 | `shutil.disk_usage` 抛 `FileNotFoundError` → `disk_usage.error` 记录，前端显示「检测失败」 |
| `total == 0`（理论上不可能） | `pct_free = 0.0`，但不触发通知（看 error 字段） |
| 用户手动删 `disk_alert_sent` 字段 | 下次启动 SettingsStore 加默认值，正常工作 |
| 同时跨过多个阈值（突然写入大文件） | `_maybe_notify` 一次循环里发多条 Telegram，每个阈值独立 |
| Telegram 发送失败 | 静默写日志，flag 仍然设为 True（避免日志洪水）；下次到下一阈值时再尝试 |

## 验收

- 启动 60s 后 dashboard 显示磁盘行
- 用 `truncate -s` 或大文件人为占满磁盘 → 跨过 20% 触发横幅 + Telegram
- 删除大文件恢复到 21% → 横幅自动消失，flag 清零
- 同浏览器点 dismiss → 横幅消失；切到另一浏览器 → 仍可见（per-browser 验证）
- Telegram 不会重复推送同阈值（除非 reset 后再触发）
