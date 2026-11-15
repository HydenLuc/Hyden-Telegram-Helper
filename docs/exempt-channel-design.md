# 例外频道设计（全局暂停下对单独频道开启监听）

> **状态**：✅ 已实现

## 1. 目标

`state.monitoring_paused = True` 时，允许用户对特定频道设置「例外」，例外频道的消息照常处理，不受全局暂停影响。

典型场景：默认暂停启动（F5）后，用户希望某些重点频道立刻接管，其他频道等用户点恢复后再统一开启。

## 2. 现状（调研结论）

完全无相关实现：

| 位置 | 现状 |
|------|------|
| `downloader/state.py:41` | `monitoring_paused: bool = False` —— 仅一个全局开关 |
| `downloader/tg/handlers.py:142-143` | `if state.monitoring_paused: return` —— 一刀切 |
| `state.watched` 字段 | 仅 `name / watched_since / task_count / task_count_reset_at`（4 个） |
| `watched_chats.json` | 与代码字段一致，无 exempt 类字段 |
| 前端监听列表行 | 仅 🔄（重置统计）和 ✕（取消监听）两个按钮 |

## 3. 数据结构

### 3.1 watched 记录新增字段

```python
state.watched[cid_str] = {
    "name":                str,
    "watched_since":       str,        # ISO
    "task_count":          int,
    "task_count_reset_at": str | None,
    "exempt":              bool,       # ★ 新增，默认 False
}
```

### 3.2 兼容性

旧 `watched_chats.json` 文件不含 `exempt` 字段。两层防御：

- **读时容错（必做）**：所有读 exempt 的代码用 `rec.get("exempt", False)`，缺字段视为 False
- **写时补齐（必做，4 处）**：所有创建/迁移 watched 记录的位置显式写 `exempt: False`，让 JSON 文件自描述

## 4. 拦截逻辑改动

### 4.1 `downloader/tg/handlers.py:142-143`

当前：

```python
if state.monitoring_paused:
    return
```

改后：

```python
cid_str = str(event.chat_id)
is_exempt = state.watched.get(cid_str, {}).get("exempt", False)
if state.monitoring_paused and not is_exempt:
    return
```

### 4.2 与下方 gate 的关系（保留不变）

```
142-145  新：paused gate（exempt 例外）
146      旧：bot_start_time gate（保留）
147-148  旧：watched gate（保留）
```

`bot_start_time` 在 paused 之后，**例外频道也只处理启动后的消息**——这是有意为之：避免重连时 Telethon 通过 `getDifference` 推送的旧积压被例外频道拉过来重复处理。

### 4.3 `state.watched` 中**不存在**的频道（非 watched）

`state.watched.get(cid_str, {})` 返回空字典，`exempt = False`。这种情况照旧被全局暂停拦截（在 142 拦下，根本走不到 147 的 watched gate）。语义不变。

## 5. 后端 API

### 5.1 新增端点

```
POST /api/watch/{cid}/exempt
Headers: X-API-Key: <api_key>
Content-Type: application/json
Body:   {"exempt": true | false}
```

### 5.2 路由注册位置

`downloader/web/server.py` 中现有路由顺序（行 27-31）：

```python
app.router.add_post("/api/watch",                       _api_watch_add)
app.router.add_post("/api/watch/reset-stats",           _api_watch_reset_stats)
app.router.add_post("/api/watch/{cid}/reset-stats",     _api_watch_cid_reset_stats)
app.router.add_delete("/api/watch/{chat_id}",           _api_watch_remove)
```

**新增插入点**（在 `{cid}/reset-stats` 之后、`{chat_id}` DELETE 之前）：

```python
app.router.add_post("/api/watch/{cid}/exempt",          _api_watch_cid_exempt)
```

aiohttp 静态段（`reset-stats` / `exempt`）和参数段（`{cid}`）的路由匹配是按精确度优先，与现有 `{cid}/reset-stats` 同模式，**无路由冲突**。

### 5.3 Handler 实现要点

```python
async def _api_watch_cid_exempt(request):
    """POST /api/watch/{cid}/exempt — 切换该频道的「全局暂停例外」状态。"""
    cid = request.match_info["cid"]
    if cid not in state.watched:
        return web.json_response({"ok": False, "error": "not in watch list"}, status=404)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(data.get("exempt"), bool):
        return web.json_response({"ok": False, "error": "exempt must be boolean"}, status=400)

    rec = state.watched[cid]
    if isinstance(rec, dict):
        rec["exempt"] = data["exempt"]
    storage.save_watched(state.watched)
    await _broadcast()
    return web.json_response({"ok": True, "cid": cid, "exempt": data["exempt"]})
```

注：旧迁移前的 string-format 条目此时早已被 `load_watched()` 转为 dict（详见 `storage.py:33-58`），运行时不会遇到 string；防御 `if isinstance(rec, dict)` 仍保留，对齐 P1-7 模式。

## 6. 前端 UI

### 6.1 监听列表每行的按钮序列

`downloader/web/templates.py:1396-1399` 现有：

```js
+ '<button class="btn btn-sm wl-reset-btn" data-id="..." title="清零该频道统计" style="padding:2px 6px">🔄</button>'
+ '<button class="rm rm-watch-btn" data-id="..." title="取消监听">✕</button>'
```

改后（在两者之间插入 exempt 按钮）：

```js
+ '<button class="btn btn-sm wl-exempt-btn" data-id="..." data-exempt="' + (exempt ? '1' : '0') + '" '
+   'title="' + (exempt ? '全局暂停时此频道仍会监听，点击取消例外' : '全局暂停时此频道也会暂停，点击设为例外') + '" '
+   'style="padding:2px 6px;color:' + (exempt ? '#ff9800' : '#666') + '">'
+   (exempt ? '🔔' : '🔕') + '</button>'
+ '<button class="btn btn-sm wl-reset-btn" data-id="..." title="清零该频道统计" style="padding:2px 6px">🔄</button>'
+ '<button class="rm rm-watch-btn" data-id="..." title="取消监听">✕</button>'
```

`exempt` 由 `_watchedExemptOf(rec)` 提取（旧条目 falsy / 缺字段返回 false）。

### 6.2 暂停期间「监听中」徽章

仅当 `state.monitoring_paused === true && exempt === true` 时，在该行加一个绿色小点徽章：

```js
const pausedBadge = (lastPaused && exempt)
  ? '<span style="color:#66bb6a;font-size:.7rem;margin-right:6px" title="全局暂停时仍在监听">● 监听中</span>'
  : '';
```

放在该行右半区起始位置（图标 / 时间 / 计数之前）。`lastPaused` 是 `templates.py:820` 已有的全局变量。

非暂停时不显示这个徽章（所有频道都在监听，区分无意义）。

### 6.3 click 事件

在 `wl` 容器现有 click delegation 中追加分支：

```js
const eb = e.target.closest('.wl-exempt-btn');
if (eb) {
  const cid = eb.dataset.id;
  const newVal = eb.dataset.exempt !== '1';
  eb.disabled = true;
  const r = await apiFetch('/api/watch/' + encodeURIComponent(cid) + '/exempt', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({exempt: newVal}),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    alert(j.error || '设置失败');
  }
  // 不主动设回 disabled=false：WS 推回新 watched 后整行重渲染
  return;
}
```

### 6.4 状态推送

`watched` 已在 WS payload 全量推送（`websocket.py:13`），不需新增字段。前端从 `d.watched[cid].exempt` 直接读。

## 7. 持久化

### 7.1 4 个写入点必须显式赋 exempt=False

| 位置 | 函数 | 当前字段集 | 改动 |
|------|------|-----------|------|
| `downloader/storage.py:46-52` | `load_watched()` 旧 string 格式迁移 | name + 3 字段 | 加 `"exempt": False` |
| `downloader/storage.py` (新增逻辑) | `load_watched()` dict 格式补齐缺字段 | — | 加 `rec.setdefault("exempt", False)` 循环 |
| `downloader/tg/handlers.py:87-92` | `cmd_watch` 命令新增频道 | name + 3 字段 | 加 `"exempt": False` |
| `downloader/web/api.py:57-62` | `/api/watch` POST 新增频道 | name + 3 字段 | 加 `"exempt": False` |

`load_watched` 中既要负责 string→dict 的旧迁移，也要负责 dict→dict-含exempt 的字段升级。建议结构：

```python
def load_watched() -> dict:
    if not WATCHED_FILE.exists():
        return {}
    raw = json.loads(WATCHED_FILE.read_text(encoding="utf-8"))
    needs_save = False
    migrated = {}
    now_iso = datetime.now().isoformat()
    for cid, val in raw.items():
        if isinstance(val, str):
            migrated[cid] = {
                "name": val,
                "watched_since": now_iso,
                "task_count": 0,
                "task_count_reset_at": None,
                "exempt": False,
            }
            needs_save = True
        elif isinstance(val, dict):
            if "exempt" not in val:
                val["exempt"] = False
                needs_save = True
            migrated[cid] = val
    if needs_save:
        save_watched(migrated)
        _log.warning(f"[downloader] watched_chats.json 已迁移（{len(migrated)} 个条目，含 exempt 字段补齐）")
    return migrated
```

### 7.2 暂停状态本身不持久化

`state.monitoring_paused` 维持现状（不持久化，重启回 False，配合 F5 默认暂停）。

**但 exempt 字段持久化**——重启后 `exempt` 设置保留，配合 F5 启动默认暂停时，例外频道立即生效。这是"启动默认暂停 + 部分频道立即活跃"组合的关键能力。

## 8. 命令行（Telegram cmd）

**v1 不实现** Telegram 端的 `例外 <id>` 命令。理由：
- exempt 是相对静态配置（设一次长期生效），命令使用频次低
- Web UI 按钮已经能完成切换且更直观
- 命令实现需要解析 cid 参数、错误兜底等额外工作

如未来要加，可参考 `cmd_watch / cmd_unwatch`（`handlers.py:72-119`）模式。

## 9. 与其他模块的交互

### 9.1 mover / unzipper

不读 `state.watched`，**完全不受影响**。

### 9.2 dashboard

`dashboard/templates.py` 显示「监听频道: N」（`renderDownloader` 内 `Object.keys(d.watched).length`）。N 仍是总数，不区分 exempt。**v1 不在 dashboard 加 exempt 可视化**（spec §10）。

### 9.3 task_count 自增

`handlers.py:233` 的 `watched_rec["task_count"] += 1` 在 dedup 检查后、download 启动前执行。例外频道下载触发后照常计数，与暂停时 task_count 不增的现有逻辑一致——因为现在例外频道根本走到了下载路径。

## 10. 边界 case

| 场景 | 行为 |
|------|------|
| 全局暂停 + 频道不在 watched + 消息到达 | paused 阻止，不到 watched gate（行为不变） |
| 全局暂停 + 频道在 watched 但 exempt=False + 消息 | paused 阻止（行为不变） |
| 全局暂停 + 频道在 watched + exempt=True + 消息 | **新行为**：放行，进入正常下载流程 |
| 非暂停 + 任意 exempt 状态 + 消息 | 不受 exempt 字段影响（exempt 仅在 paused=True 时起作用） |
| 用户在暂停期间新增频道（cmd_watch / Web）| 默认 exempt=False，新频道**不会**立即接收消息；用户须显式点 🔕→🔔 切换 |
| 删除频道 | 整条 dict 删除，exempt 字段一并消失（行为对称） |
| 非暂停时切换 exempt | 切换有效，仅在下次 paused 时体现作用 |
| 重启 bot | exempt 持久化保留；monitoring_paused 重置（默认暂停 + exempt 字段配合，立即生效） |
| F4B 移动整组（与 exempt 无关） | 不受影响 |
| F6 重复下载、MD5 dedup | 不受影响（在 paused 之后才到 dedup gate） |
| 并发：用户两次快速点击 exempt 按钮 | 两个 POST 顺序到达，最后一个写入决定状态；WS 推送收敛；无数据损坏 |

## 11. 测试矩阵

### 11.1 后端

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 启动新空 watched_chats.json，调 `cmd_watch xxx` | 新条目含 `exempt: false` |
| 2 | 手工编辑 JSON 删除 exempt 字段，重启 | `load_watched` 自动补齐并持久化 |
| 3 | 旧 string 格式 JSON 启动 | 一次性迁移到含 exempt 的 dict |
| 4 | `POST /api/watch/{cid}/exempt {exempt: true}` | 200，state.watched[cid].exempt=true，文件持久化 |
| 5 | 同上但 cid 不存在 | 404 not in watch list |
| 6 | body 缺 exempt 字段 / 类型非 bool | 400 |
| 7 | `monitoring_paused=true + exempt=false`，模拟消息 | handle_media 在 142 行 return |
| 8 | `monitoring_paused=true + exempt=true`，模拟消息 | 走完正常下载流程 |
| 9 | `monitoring_paused=false + exempt=任意`，模拟消息 | 行为与现状一致（exempt 字段不读不写） |

### 11.2 前端

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 列表渲染含 exempt=false 的频道 | 显示 🔕 灰色按钮 |
| 2 | 列表渲染含 exempt=true 的频道 | 显示 🔔 橙色按钮 |
| 3 | 点 🔕 切换 → POST → WS 推回 | 按钮变 🔔 橙色 |
| 4 | 全局暂停 + exempt=true | 该行显示绿色「● 监听中」徽章 |
| 5 | 全局暂停 + exempt=false | 不显示徽章 |
| 6 | 非暂停 + exempt=true | 不显示徽章（按钮颜色已表达意图） |
| 7 | 切换 exempt 期间快速重复点击 | 最终状态收敛到最后一次点击；无 JS 报错 |
| 8 | 取消监听后 watched 删除 | 该行连同 exempt 按钮一起消失 |

### 11.3 联动

| # | 场景 | 期望 |
|---|------|------|
| 1 | F5 默认暂停启动 + 1 个 exempt 频道有积压消息 | 启动后 exempt 频道立即开始下载 |
| 2 | recover_pending_tasks 跑（F5 决策：照跑） | 与 exempt 无关，所有 pending 任务照常恢复 |
| 3 | duplicate_queue / MD5 toast | exempt 频道触发的下载与普通下载流程完全一致，dedup 与 toast 正常工作 |
| 4 | dashboard 卡片 | "监听频道: N" 仍是总数，不变 |

## 12. 不在本次范围

- 例外频道的历史消息补下（在历史消息下载功能里做）
- 例外频道在 Dashboard 的可视化（如"X 个例外"提示）
- 暂停状态本身的持久化（仍维持启动重置，配合 F5 默认暂停）
- Telegram 命令端 `例外 <id>` 切换
- 例外频道间的优先级（v1 所有 exempt 频道平等，按消息到达顺序处理）
- 例外白名单的批量操作（一键全部 exempt / 一键清空 exempt）

---

## 13. 后续演进：「例外暂停」开关（2026-08-06 加）

本设计里 exempt 频道是**无条件**绕过全局暂停的。实际用下来有个缺口：想让例外频道也停
下来时，只能**逐个把 exempt 改回 false，事后还得记着改回来**（2026-08-06 手动改了 18 个）。

所以加了第二个开关，两个各管一半：

```python
# downloader/tg/handlers.py:handle_media
is_exempt = state.watched.get(cid_str, {}).get("exempt", False)
if state.exempt_paused if is_exempt else state.monitoring_paused:
    return
```

| 全局暂停 | 例外暂停 | 效果 |
|---|---|---|
| 关 | 关 | 全都收（默认） |
| **开** | 关 | 只有例外频道收 ← 本设计的原意 |
| **开** | **开** | 全都不收 ← 要把队列排空时用 |
| 关 | **开** | 例外不收、其余照收（少见但允许） |

- 新增 `state.exempt_paused`（同样**不持久化**，重启回默认）
- 新增 `POST /api/exempt-pause` / `/api/exempt-resume`；`/api/status` 与 WebSocket 广播带 `exempt_paused`
- ⚠️ **`bot.py` 启动时把两个都置 True** —— 只关全局的话例外频道会在重启后立刻开下，
  与「重启永不静默开始下载」的初衷矛盾（2026-08-06 队列就是这样一路涨到 1800+ 的）

前端两端一致：按钮文字自带状态（`全局暂停:开` / `例外暂停:关`），开时实心高亮。
⚠️ 网页端原来的「暂停例外」标签已改叫「**例外频道**」——跟新开关「例外暂停」只差语序，太容易看混。
