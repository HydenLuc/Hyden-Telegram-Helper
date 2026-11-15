# Unzipper 密码管理 UI 设计

> **状态**：✅ 已实现。本文档定义密码列表的存储格式迁移、运行时管理 UI 和后端 API。

## 背景

当前 unzipper 解压密码：

- 存储：`.env` 的 `PASSWORDS=p1,p2,p3`（逗号分隔）
- 运行时：`config.PASSWORDS` 启动时一次性加载到 `state.passwords` (list)
- API：`GET / POST / DELETE /api/passwords` 三个端点已存在
- 前端：**完全没有管理 UI**，用户只能 curl 或改 .env

两个问题：

1. **逗号分隔的存储格式无法支持含逗号的密码**——这是一个隐式约束，前端应当校验，但目前后端也无校验
2. **缺前端管理 UI** — 普通用户用不了运行时密码管理能力

## 关键设计决策

### 决策 1：密码独立存储到 `passwords.json`，从 .env 拆出

**理由**：

- 密码语义上是**运行时状态**而非配置（与 `watched_chats.json` 同级）
- `.env` 写入需要处理 quote / escape，env_writer 当前不支持；改起来侵入性大
- 独立 JSON 文件可以原生支持任意密码字符（含 `,` `\n` `\r` `"` `\\`）
- 与 `unzipper_history.json` / `watched_chats.json` 共享同一持久化模式，统一性好
- 唯一代价：启动加载逻辑要从 .env 改为读 JSON

### 决策 2：`.env PASSWORDS=` 旧格式自动迁移一次

**迁移规则**：

```
启动时：
  if passwords.json 存在:
      用 passwords.json 加载（新格式优先）
  elif .env PASSWORDS 非空:
      解析 .env 的逗号分隔值（兼容旧用户）
      立刻原子写入 passwords.json
      （不主动从 .env 删除 PASSWORDS=，避免破坏用户备份；下次启动直接走 passwords.json 路径，.env 的值被忽略）
  else:
      passwords = []
```

**`.env` 的 `PASSWORDS=` 行不主动删除**——避免给用户"没经过同意被改 .env"的惊吓；用户可以自己删（或留作备份），下次启动会忽略它。

### 决策 3：UI 拖拽重排 500 ms debounce

连续拖动多次只触发一次 `POST /api/passwords` 全量更新。最后一次释放鼠标后 500 ms 才持久化。

### 决策 4：UI 显示"顺序 = 解压尝试顺序"提示

`state.passwords` 是有序 list，按顺序 retry。section 标题旁加小字提示，避免用户对拖拽语义产生误解（"为什么顺序还会被记住"）。

## 后端改动

### `config.py`

```python
# 旧
PASSWORDS = [p.strip() for p in os.getenv("PASSWORDS", "").split(",") if p.strip()]

# 新
PASSWORDS_FILE = Path("passwords.json")
PASSWORDS = []   # 保留空列表（向后兼容：extractor.py:129 可能 fallback 到此）
                 # 真正的密码数据在 state.passwords，由 unzipper.storage.load_passwords() 启动时加载
```

`config.py` 不再读 `PASSWORDS=` 环境变量；改为静态常量 `PASSWORDS_FILE`。`PASSWORDS = []` 保留是为了向后兼容 `unzipper/extractor.py:129` 的 `passwords = config.PASSWORDS` fallback——这个 fallback 仅在测试代码 / 手工调用 `extract()` 不传 `passwords` 参数时才走，正常流程 `unzipper/manager.py` 总是显式传 `_state.passwords`，所以空 list 不影响生产逻辑。

### `unzipper/storage.py`

新增模块级单例 + 三个函数：

```python
def load_passwords() -> list[str]:
    """加载 passwords.json；不存在 → 尝试从 .env 迁移；都没有返回 []."""
    if config.PASSWORDS_FILE.exists():
        try:
            data = json.loads(config.PASSWORDS_FILE.read_text(encoding="utf-8"))
            return [p for p in data if isinstance(p, str)]
        except Exception as e:
            _log.error(f"[unzipper] 加载 passwords.json 失败: {e}")
            return []

    # 兼容性迁移：从 .env PASSWORDS= 读一次
    legacy = os.getenv("PASSWORDS", "").strip()
    if legacy:
        migrated = [p.strip() for p in legacy.split(",") if p.strip()]
        if migrated:
            save_passwords(migrated)
            _log.info(f"[unzipper] 已从 .env PASSWORDS= 迁移 {len(migrated)} 个密码到 passwords.json")
            return migrated
    return []


def save_passwords(passwords: list[str]) -> None:
    """原子写 passwords.json。"""
    atomic_write_json(config.PASSWORDS_FILE, passwords)


# 旧 save_passwords_to_env / save_setting_to_env('PASSWORDS', ...) 删除
```

### `unzipper/state.py`

```python
# 旧
passwords: list[str] = list(config.PASSWORDS)

# 新（启动时加载）
from unzipper.storage import load_passwords
passwords: list[str] = load_passwords()
```

### `unzipper/web/api.py`

- `_api_passwords_add`：保留现有校验（非空、不重复），改调 `save_passwords(state.passwords)`
- `_api_passwords_remove`：同上
- **新增** `POST /api/passwords/reorder`：接受 `{"passwords": [...]}` 全量替换（用于拖拽重排和按字典序排序）；先校验列表内容是 `state.passwords` 的排列（同集合，仅顺序不同），不允许此端点新增/删除

```python
async def _api_passwords_reorder(request):
    body = await request.json()
    new_order = body.get("passwords", [])
    if not isinstance(new_order, list):
        return web.json_response({"ok": False, "error": "passwords must be a list"}, status=400)
    # 仅允许重排：必须是当前集合的排列
    if sorted(new_order) != sorted(state.passwords):
        return web.json_response(
            {"ok": False, "error": "reorder must contain exactly the same passwords"},
            status=400,
        )
    state.passwords = list(new_order)
    save_passwords(state.passwords)
    return web.json_response({"ok": True, "passwords": state.passwords})
```

注册路由 `POST /api/passwords/reorder`。

### `.gitignore`

添加 `passwords.json`。

### 后端校验补强（独立于 UI）

虽然密码现在不写 .env，**后端仍应**在 `_api_passwords_add` 中拒绝包含 `\n` 或 `\r` 的密码——否则用户用 curl 直接 POST 含换行的密码，前端不可见还会破坏 UI 显示。

```python
if "\n" in pw or "\r" in pw:
    return web.json_response(
        {"ok": False, "error": "password cannot contain newline characters"},
        status=400,
    )
```

## 前端 UI

### 位置

`unzipper/web/templates.py` 现有结构：
```
<section id="set-section">  // 设置（路径管理）
<section>正在运行的任务
<section>待确认任务
<section>历史记录
```

新增"密码管理" section 插入到**设置之后、正在运行的任务之前**：

```html
<section>
  <h2 id="pwd-toggle" style="cursor:pointer;user-select:none">
    密码管理 <span id="pwd-arrow" ...>▶</span>
    <span id="pwd-count" style="color:#888;font-size:.8rem;margin-left:8px">0</span>
    <span style="color:#666;font-size:.7rem;margin-left:8px;font-weight:normal">顺序 = 解压尝试顺序</span>
  </h2>
  <div id="pwd-panel" style="display:none">
    <div id="pwd-list">
      <!-- 密码条目（drag-and-drop） -->
    </div>
    <div style="display:flex;gap:6px;margin-top:10px">
      <input id="pwd-input" type="password" placeholder="输入新密码..." style="flex:1;...">
      <button class="btn btn-sm" id="pwd-add">添加</button>
      <button class="btn btn-sm" id="pwd-sort" title="按字典序排序">↕ A-Z</button>
    </div>
    <div id="pwd-warn" style="color:#ef9a9a;font-size:.78rem;min-height:16px;margin-top:6px"></div>
  </div>
</section>
```

### 折叠

复用 `setupToggle('pwd-toggle', 'pwd-arrow', 'pwd-panel', 'pwd_section_collapsed')`。默认**折叠**（密码 UI 不应在打开页面时立刻暴露）。

### 密码条目渲染

每条密码一行：

```
[⠿] •••••••••••       [👁] [✕]
```

- `⠿` 拖动手柄（cursor: grab；drag-and-drop 触发区域）
- `•••••••••••` 默认掩码（用 `*` × 密码长度，最多显示 20 个，超过截断显示）
- `👁` toggle：点击后该条切到明文显示；再点回掩码
- `✕` 删除按钮（无二次确认；操作可通过添加恢复，不需要保护）

```javascript
function renderPasswordItem(pw, idx) {
  const masked = '•'.repeat(Math.min(pw.length, 20));
  return '<div class="pwd-row" draggable="true" data-idx="' + idx + '">'
    + '<span class="pwd-handle">⠿</span>'
    + '<span class="pwd-text" data-pw="' + esc(pw) + '" data-show="0">' + esc(masked) + '</span>'
    + '<button class="btn btn-sm pwd-toggle-btn" data-idx="' + idx + '" title="显示/隐藏">👁</button>'
    + '<button class="btn btn-sm pwd-del-btn" data-idx="' + idx + '" style="color:#ef9a9a">✕</button>'
    + '</div>';
}
```

### 空状态

`#pwd-list` 为空时显示：

```html
<p class="empty">暂无解压密码，点击下方添加</p>
```

### 添加交互

```javascript
async function addPassword() {
  const inp = document.getElementById('pwd-input');
  const warn = document.getElementById('pwd-warn');
  const pw = inp.value;
  warn.textContent = '';

  // 前端校验
  if (!pw.trim()) { warn.textContent = '密码不能为空'; return; }
  if (pw.includes('\n') || pw.includes('\r')) {
    warn.textContent = '密码不能包含换行符';
    return;
  }
  if (currentPasswords.includes(pw)) {
    warn.textContent = '密码已存在';
    return;
  }

  // 调 POST /api/passwords
  const r = await apiFetch('/api/passwords', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: pw}),
  });
  const j = await r.json();
  if (j.ok) {
    currentPasswords = j.passwords;
    inp.value = '';
    renderPasswordList();
  } else {
    warn.textContent = j.error || '添加失败';
  }
}

document.getElementById('pwd-add').addEventListener('click', addPassword);
document.getElementById('pwd-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') addPassword();
});
```

### 删除交互

```javascript
document.getElementById('pwd-list').addEventListener('click', async (e) => {
  const delBtn = e.target.closest('.pwd-del-btn');
  if (delBtn) {
    const idx = parseInt(delBtn.dataset.idx);
    const pw = currentPasswords[idx];
    const r = await apiFetch('/api/passwords', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw}),
    });
    const j = await r.json();
    if (j.ok) {
      currentPasswords = j.passwords;
      renderPasswordList();
    }
    return;
  }

  const tgBtn = e.target.closest('.pwd-toggle-btn');
  if (tgBtn) {
    const row = tgBtn.closest('.pwd-row');
    const txt = row.querySelector('.pwd-text');
    const show = txt.dataset.show === '1';
    if (show) {
      const masked = '•'.repeat(Math.min(txt.dataset.pw.length, 20));
      txt.textContent = masked;
      txt.dataset.show = '0';
    } else {
      txt.textContent = txt.dataset.pw;
      txt.dataset.show = '1';
    }
  }
});
```

### 拖拽重排（HTML5 drag-and-drop + 500 ms debounce）

```javascript
let pwdReorderTimer = null;

function setupDragDrop() {
  const list = document.getElementById('pwd-list');

  let dragSrcIdx = null;

  list.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.pwd-row');
    if (!row) return;
    dragSrcIdx = parseInt(row.dataset.idx);
    row.style.opacity = '0.4';
  });

  list.addEventListener('dragend', (e) => {
    const row = e.target.closest('.pwd-row');
    if (row) row.style.opacity = '';
  });

  list.addEventListener('dragover', (e) => {
    e.preventDefault();  // 必须 preventDefault 才允许 drop
  });

  list.addEventListener('drop', (e) => {
    e.preventDefault();
    const targetRow = e.target.closest('.pwd-row');
    if (!targetRow || dragSrcIdx === null) return;
    const dstIdx = parseInt(targetRow.dataset.idx);
    if (dstIdx === dragSrcIdx) return;

    // 移动数组项
    const moved = currentPasswords.splice(dragSrcIdx, 1)[0];
    currentPasswords.splice(dstIdx, 0, moved);
    renderPasswordList();    // 立即重渲染（视觉反馈）

    // 500ms debounce 持久化
    clearTimeout(pwdReorderTimer);
    pwdReorderTimer = setTimeout(persistReorder, 500);
  });
}

async function persistReorder() {
  const r = await apiFetch('/api/passwords/reorder', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({passwords: currentPasswords}),
  });
  const j = await r.json();
  if (!j.ok) {
    document.getElementById('pwd-warn').textContent = '重排失败：' + (j.error || '未知错误');
    // 重新拉一次后端真实顺序
    await loadPasswords();
  }
}
```

### 字典序排序按钮

```javascript
document.getElementById('pwd-sort').addEventListener('click', async () => {
  if (currentPasswords.length < 2) return;
  const sorted = [...currentPasswords].sort((a, b) => a.localeCompare(b));
  if (sorted.every((p, i) => p === currentPasswords[i])) return;  // 已排序
  currentPasswords = sorted;
  renderPasswordList();
  await persistReorder();   // 直接持久化，不走 debounce
});
```

### 启动加载

```javascript
let currentPasswords = [];

async function loadPasswords() {
  const r = await apiFetch('/api/passwords');
  const j = await r.json();
  if (j.ok) {
    currentPasswords = j.passwords;
    renderPasswordList();
  }
}

// 页面加载完调一次
loadPasswords();
```

WebSocket 不推送密码（密码不放进 `_build_state`）；只在用户操作后由 API 响应同步。如果两个 Tab 同时打开，B Tab 不会感知 A Tab 的修改，需要手动刷新——v1 不解决这个，记入"不在本次范围"。

## 不在本次范围

- 多 Tab 同步（用 WebSocket 推送密码列表变更）—— v1 不做（密码列表不应频繁广播）
- 密码强度提示 / 密码生成器 —— 与"已知密码列表"语义不符
- 密码导入/导出 —— 用户可手动操作 `passwords.json`
- 密码分组（按来源 / 标签）—— 单一 list 满足当前需求
- 密码使用统计（哪个密码命中最多）—— 与历史记录相关，可后续做

## 测试矩阵

1. 启动加载：
   - 无 passwords.json + 无 .env PASSWORDS → `state.passwords == []`
   - 无 passwords.json + .env PASSWORDS=p1,p2 → 自动迁移 + 写 passwords.json + log "已迁移"
   - 有 passwords.json → 用 JSON 内容（忽略 .env PASSWORDS）
2. 添加：空 / 仅空格 / 含 `\n` / 重复 → 各自正确报错
3. 添加正常 → 持久化到 passwords.json + 立即生效（下个解压任务可用）
4. 删除：通过 ✕ 按钮 → 从列表 + 文件移除
5. 重排：连续拖动 5 次 → 仅触发一次 `POST /api/passwords/reorder`
6. 字典序排序：立即生效（不走 debounce）
7. 含特殊字符的密码（`,` `\\` `"` `'`）正确写入 / 读取 passwords.json
8. 显示切换：👁 toggle 不影响存储
9. 重启：state.passwords 与 passwords.json 一致

## 工作量预估

~半天。后端改动小（`config.py` + `storage.py` + 3 个 handler），前端 UI 约 150 行 JS + 50 行 HTML/CSS；测试矩阵 9 项。
