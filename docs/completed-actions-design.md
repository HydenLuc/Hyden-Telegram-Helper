# 已完成列表操作扩展设计

> **状态**：✅ 已实现（4A: commit；4B: commit）

包含两个独立子功能：
- **4A**：清空已完成列表中的 done 任务（保留 error / timeout）
- **4B**：移动整组文件夹（走 mover）

---

## 4A. 清空已完成中的 done 任务

### 现状

`downloader/web/api.py:_api_completed_clear` (POST `/api/completed/clear`) 一刀切清空 `state.completed_downloads`，包括失败任务。用户痛点：成功的清掉以释放历史，失败的要保留以便排查/重试，**目前办不到**。

### 新增端点

```
DELETE /api/history/done
```

逻辑：

```python
async def _api_history_clear_done(_request):
    before = len(state.completed_downloads)
    state.completed_downloads = [
        r for r in state.completed_downloads if r.get("status") != "done"
    ]
    after = len(state.completed_downloads)
    storage.save_completed(state.completed_downloads)
    await _broadcast()
    return web.json_response({
        "ok": True,
        "removed": before - after,
        "remaining": after,
    })
```

注册到 `downloader/web/server.py`：

```python
app.router.add_delete("/api/history/done", _api_history_clear_done)
```

### UI

`downloader/web/templates.py` 已完成区原「清空已完成」按钮**保留**，旁边新加一个：

```html
<button id="clear-done-btn" class="btn btn-sm">清空 done 任务</button>
```

点击：

```js
document.getElementById('clear-done-btn').onclick = async () => {
  if (!confirm('清空所有已成功的下载记录？失败/超时记录会保留')) return;
  const r = await apiFetch('/api/history/done', {method:'DELETE'});
  const j = await r.json();
  if (j.ok) {
    refetchHistory();   // 复用现有分页加载
    showToast(`已清除 ${j.removed} 条 done 记录，保留 ${j.remaining} 条`);
  }
};
```

### 验收

- 既有「清空已完成」仍清空全部
- 新按钮只清 `status=done` 的记录
- error / timeout 记录在新按钮点击后**仍可见**
- `completed.json` 与内存同步
- WebSocket 推送 `completed_total` 字段同步更新

---

## 4B. 移动整组文件夹（走 mover）

### 触发条件

只允许对**整组完成**的下载文件夹做整体搬运：

- 操作粒度：`grouped_state` 的一个 `gs_key` 对应的文件夹
- 可移动条件：`grouped_state[gs_key].status == "done"`
- 不可移动场景：
  - 该 group 还有 `downloading` / `waiting` 的 file
  - 该 group 有任意 `error` 的 file（前端按钮显示，但点击后端 422 拒绝）
  - 文件夹已不存在（之前手动移动 / mover 整体处理过）

### 整体设计：走 mover，不直接 shutil.move

mover 已有完整的两步原子搬运、跨文件系统、staging、blacklist、并发 semaphore。**不重复造轮子**。

```
downloader /api/history/move-group
    ↓
1. 验证 gs_key + status == done
2. 推导文件夹路径 folder = Path(任一 file.save_path).parent
3. 校验 folder 在 DOWNLOAD_DIR + 校验 target_dir
4. POST mover /api/move {source: folder, target: target_dir, task_id: "movegrp_{gs_key}"}
5. 返回 {ok, mover_task_id}（不等 mover 完成）
6. 启动一个 fire-and-forget watcher 协程：轮询 mover 直到 done/failed
       └ done → 删除 completed_downloads 中对应 gs_key 的所有 task 记录 + WS 广播
       └ failed → 不删 completed，前端 WS 收到 mover task failed 即可
```

mover 收到 `task_id = "movegrp_{gs_key}"`，通过 semaphore 与其他文件级搬运任务自然串行（如该 group 里某些 archive 文件还在被 mover 处理，新任务会排队等其完成，避免并发 race）。

### 路径推导与校验

```python
def _resolve_group_folder(gs_key: str) -> Path | None:
    group = state.grouped_state.get(gs_key)
    if not group: return None
    if group["status"] != "done": return None
    files = group.get("files", {})
    for task_id, f in files.items():
        sp = f.get("save_path")
        if sp:
            folder = Path(sp).parent
            return folder if folder.exists() else None
    return None
```

### target_dir 校验（在 downloader 端预检，给清晰错误）

```python
from common.path_utils import is_under

def _validate_move_target(folder: Path, target_dir: Path) -> str | None:
    """返回 None 表示通过，否则返回错误字符串。"""
    if not target_dir.is_absolute():
        return "target_dir must be absolute"
    if target_dir == folder:
        return "target_dir must differ from source folder"
    if is_under(folder, target_dir) or is_under(target_dir, folder):
        return "target_dir must not contain or be inside source folder"
    # mover 自己也会再校验黑名单（DRY；但提前给报错更清晰）
    return None
```

mover 自身仍会做 `_is_blacklisted` / `_source_in_allowed_roots` 二次校验。

### 新端点 `POST /api/history/move-group`

```python
async def _api_history_move_group(request):
    data = await request.json()
    gs_key = (data.get("gs_key") or "").strip()
    target_dir = (data.get("target_dir") or "").strip()
    if not gs_key or not target_dir:
        return web.json_response({"ok": False, "error": "gs_key and target_dir required"}, 400)

    folder = _resolve_group_folder(gs_key)
    if not folder:
        return web.json_response(
            {"ok": False, "error": "group not found, not done, or folder missing"}, 404
        )

    err = _validate_move_target(folder, Path(target_dir))
    if err:
        return web.json_response({"ok": False, "error": err}, 400)

    mover_task_id = f"movegrp_{gs_key}"
    payload = {
        "source": str(folder),
        "target": target_dir,
        "task_id": mover_task_id,
    }
    # POST 给 mover；超时短，因 mover 立即返回
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5),
        headers={'X-API-Key': config.API_KEY},
    ) as session:
        async with session.post(
            f"http://localhost:{config.MOVER_PORT}/api/move", json=payload,
        ) as resp:
            mover_resp = await resp.json()
    if not mover_resp.get("ok"):
        return web.json_response(
            {"ok": False, "error": f"mover rejected: {mover_resp.get('error')}"}, 502
        )

    # 加入路径历史
    settings = storage.load_settings()
    storage.add_path_to_history(settings, "move_target", target_dir)
    storage.save_settings(settings)

    # 启动 watcher 协程（不阻塞响应）
    asyncio.create_task(_watch_movegrp(mover_task_id, gs_key))

    return web.json_response({
        "ok": True,
        "mover_task_id": mover_task_id,
        "source_folder": str(folder),
        "target_dir": target_dir,
    })
```

### Watcher 协程

```python
async def _watch_movegrp(mover_task_id: str, gs_key: str):
    """轮询 mover 直到任务终态，成功则清理 completed_downloads。"""
    url = f"http://localhost:{config.MOVER_PORT}/api/tasks/{mover_task_id}"
    deadline = time.time() + 3600  # 最长 1 小时；超时放弃监听
    while time.time() < deadline:
        await asyncio.sleep(2)
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
                headers={'X-API-Key': config.API_KEY},
            ) as session:
                async with session.get(url) as resp:
                    data = await resp.json()
        except Exception:
            continue
        task = data.get("task")
        if not task: continue
        st = task.get("status")
        if st == "done":
            _remove_completed_by_gs_key(gs_key)
            await _broadcast()
            return
        if st == "failed":
            # 失败保留 completed_downloads，让用户看到 mover 那边的错误
            await _broadcast()
            return

def _remove_completed_by_gs_key(gs_key: str):
    from downloader.download.manager import _gs_key_for
    before = len(state.completed_downloads)
    state.completed_downloads = [
        r for r in state.completed_downloads if _gs_key_for(r) != gs_key
    ]
    if len(state.completed_downloads) != before:
        storage.save_completed(state.completed_downloads)
```

注：mover 当前 `/api/tasks/{task_id}` 端点存在性需确认。如未实现，需要补一个 GET 单任务的端点（mover/web/api.py 已有 `_api_tasks_list` 列表，单任务查询应该已有；若无则补 `GET /api/tasks/{task_id}`）。

### 路径历史

`downloader_settings.json` 现已支持 `path_history.download_dir / watch_path`，新增第三个 key：

```json
{
  "path_history": {
    "download_dir":  ["..."],
    "watch_path":    ["..."],
    "move_target":   ["..."]
  }
}
```

`SettingsStore` 已是通用 dict，无需改 schema 代码，只需调用 `storage.add_path_to_history(settings, "move_target", path)` 即可。

### `_build_settings_response()` 增加返回字段

```python
"move_target_history": settings["path_history"].get("move_target", []),
```

### 前端 UI

在已完成列表里，**按 group 聚合显示** 是必需的（spec 表达：每个 done group 显示一个「移动文件夹」按钮）。当前 history 是按 task 平铺。

实现方式：

1. 前端拉到 history 后按 `gs_key`（前端可基于 `task.grouped_id`/`task.task_id` 推导）分组
2. 每组渲染时：组内全部 done → 顶部加一个「移动文件夹」按钮；任意非 done → 不显示按钮
3. 按钮的具体位置：组的标题行右侧，与组的展开/收起按钮并列

按钮点击弹出输入框：

```html
<dialog id="movegrp-dialog">
  <h3>移动文件夹</h3>
  <p id="movegrp-folder" class="muted"></p>
  <input id="movegrp-input" list="movegrp-history" placeholder="目标父目录绝对路径" />
  <datalist id="movegrp-history"></datalist>
  <div>
    <button id="movegrp-confirm">确认移动</button>
    <button id="movegrp-cancel">取消</button>
  </div>
  <p id="movegrp-error" style="color:#ef5350"></p>
</dialog>
```

Datalist 选项来自 `/api/settings` 的 `move_target_history`。

确认逻辑：

```js
async function submitMoveGroup(gs_key, source_folder) {
  const target = document.getElementById('movegrp-input').value.trim();
  if (!target) return;
  const r = await apiFetch('/api/history/move-group', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({gs_key, target_dir: target}),
  });
  const j = await r.json();
  if (!j.ok) {
    document.getElementById('movegrp-error').textContent = j.error;
    return;
  }
  showToast(`已提交搬运：${j.source_folder} → ${j.target_dir}`);
  closeDialog();
  loadPathSettings();   // 刷新历史下拉
  // mover 完成后会自动从 history 移除该 group，无需此处手动刷新
}
```

### 已知限制（写入 spec）

- **`_group_dirs` 缓存**：移动文件夹后，5 分钟内同 grouped_id 的延迟到达消息会失败（因为缓存里 `dir` 字段指向已不存在的旧路径）。**用户操作前应确认该 group 的 Telegram 消息已全部送达**。重启 bot 即可清缓存。
- **mover 历史保留**：mover 的 `movegrp_{gs_key}` 任务记录留在 `mover_state.json`，与文件级搬运任务一起出现在 mover UI。
- **跨文件系统**：mover 已支持（`shutil.copytree` 模式），但耗时显著长于同 fs `os.rename`，watcher 协程的 1 小时超时是为此预留。
- **error group**：spec 明确不允许移动有 error 的 group。如果 group 部分 done 部分 error，前端按钮不显示；用户要先重试或删除 error 任务才能动这个 group。

### 验收

- 选一个完整 done 的 group，点「移动文件夹」→ 输入 target → 确认
- mover 接到任务，执行原子搬运
- mover 完成后，downloader history 里该 group 的所有 task 自动消失
- mover failed → history 保留，用户看到 mover 红色任务
- target == source / target 在 source 内 → 后端 400
- target = `/etc` → mover 黑名单返回 403（前端展示原始错误）
- 路径历史下拉记住最近 10 个 target

---

## 共用：错误码约定

- `400` 参数缺失或自校验失败
- `404` group 不存在 / 文件夹找不到
- `422` group 状态不允许操作（保留状态码，目前用 404）
- `502` mover 调用失败（不可达 / 拒绝）
