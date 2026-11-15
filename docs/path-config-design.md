# 输出路径管理设计

> **状态**：✅ 已实现。本文档定义三模块的输出路径动态配置语义、UI 行为、`.env` 写回策略和模块间联动机制。

## 背景

当前路径硬编码在 `.env`（`DOWNLOAD_DIR` / `WATCH_PATH` / `OUTPUT_PATH`），无法在 UI 动态修改——用户必须停服务、改 `.env`、重启。需要支持热更新：在 UI 改路径，新任务立即用新路径，旧任务沿用原路径，无需重启。

---

## 默认路径（跨平台）

| 模块 | 路径变量 | Linux/macOS 默认 | Windows 默认 |
|---|---|---|---|
| downloader 输出 | `DOWNLOAD_DIR` | `~/HydenFileSystem/Downloads` | `C:\HydenFileSystem\Downloads` |
| 集合点（mover 落点 / unzipper 输入）| `WATCH_PATH` | `~/HydenFileSystem/Archives` | `C:\HydenFileSystem\Archives` |
| unzipper 输出 | `OUTPUT_PATH` | `~/HydenFileSystem/Extracted` | `C:\HydenFileSystem\Extracted` |

### `config.py` 默认值改动

```python
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", str(Path.home() / "HydenFileSystem" / "Downloads")))
WATCH_PATH   = Path(os.getenv("WATCH_PATH",   str(Path.home() / "HydenFileSystem" / "Archives")))
OUTPUT_PATH  = Path(os.getenv("OUTPUT_PATH",  str(Path.home() / "HydenFileSystem" / "Extracted")))
```

注意：`.env` 显式设定的路径优先；用户当前已配置的路径**不会被自动迁移**。

---

## 优先级与单一真相源

`.env` 是**单一真相源**：

| 阶段 | 行为 |
|---|---|
| **启动加载** | 读 `.env`；缺失则用 `config.py` 默认值 |
| **UI 改路径** | 同时**写回 `.env`**（参考已有 `save_env_settings` 模式）+ 更新内存 |
| **`settings.json`**（新增）| **仅**保存历史路径列表 + `use_last_path` 偏好；**不保存当前路径** |

理由：避免 `.env` 与 `settings.json` 双源不一致；`.env` 既是用户手改的入口，也是 UI 改路径的落地。

---

## 路径管理 UI（各模块设置区域）

每个模块的「设置」区域内嵌路径管理控件：

```
┌─ 输出路径 ──────────────────────────────────┐
│ 当前：/home/user/HydenFileSystem/Downloads  │ ← 只读显示
│ ┌──────────────────────────────────┐        │
│ │ [输入框：可编辑]                   │ [应用]│
│ └──────────────────────────────────┘        │
│ 历史路径 [v]                                  │
│   ▶ 系统默认路径                              │ ← 始终是第一项
│   ▶ /old/path/1                              │
│   ▶ /old/path/2                              │
│ 默认行为：                                    │
│   ◯ 始终使用系统默认路径                      │
│   ⬤ 记住上次使用的路径                       │
└─────────────────────────────────────────────┘
```

### 历史下拉

- 最多 10 条，超出删最旧
- 第一项**始终**是"系统默认路径"（`config.py` 默认值，不可删）
- 其余按最近使用时间倒序排列
- 点击任一项 = 应用该路径（同 [应用] 按钮的语义）

### Radio 选项语义

| 选项 | 启动加载行为 | UI 改路径影响 |
|---|---|---|
| **始终使用系统默认路径** | 启动时无条件用 `config.py` 默认值（**忽略 `.env` 里的 `*_PATH`**）| UI 改路径**只对本次会话有效**，重启回默认 |
| **记住上次使用的路径** | 启动时用 `.env` 里的路径（标准行为）| UI 改路径**永久生效**（写回 `.env`）|

`use_last_path` 偏好持久化在 `settings.json`。

---

## 热更新语义

修改路径**不重启服务**：

- 正在进行的任务**继续用旧路径**（path 已绑定到协程作用域）
- 已排队但未开始的任务**继续用旧路径**（已派发，路径已固定）
- **只有新触发的任务用新路径**

伪代码：
```python
# downloader 侧
async def handle_media(event):
    save_dir = config.DOWNLOAD_DIR / source_name / folder_name  # 读当前 config 值
    file_path = save_dir / media_filename(message)
    asyncio.create_task(download_one(task_id, message, file_path, ...))  # path 已固定
```

`config.DOWNLOAD_DIR` 是模块级变量，UI 改路径直接覆盖该变量；`handle_media` 下次调用读到新值。

---

## 模块间联动（downloader ↔ unzipper 直连）

**mover 不参与联动**——mover 不持有 `WATCH_PATH` 配置（详见下方"mover 的特殊处理"）。

| 修改的模块 | 字段 | 联动方向 |
|---|---|---|
| downloader | `DOWNLOAD_DIR` | **无联动**（私有路径）|
| downloader | `WATCH_PATH` | 弹窗：是否同步到 unzipper 的 `WATCH_PATH`？|
| unzipper | `WATCH_PATH` | 弹窗：是否同步回 downloader 的 `WATCH_PATH`？|
| unzipper | `OUTPUT_PATH` | **无联动**（终点路径）|

### 联动实现

用户点击 [是]：
- 当前模块调对方的 `POST /api/settings` 更新 WATCH_PATH（带 `X-API-Key`）
- 对方收到请求后：写回自己的 `.env` + 更新内存（同自己 UI 改路径行为一致）

用户点击 [否]：
- 当前模块独自改路径
- **v1 不显示实时不一致警告**（参见下文）

### v1 不做实时不一致警告

如果用户选 [否]，下次访问对方页面**不会**看到 banner 提示路径不一致。  
原因：实时检测涉及跨模块 HTTP 拉取（CORS 或 dashboard 聚合扩展），工程复杂度配不上产品价值（弹窗联动已经足够提示）。

**v2 留作未来**：通过 dashboard `/api/overview` 聚合各模块 settings + 各模块 UI 检测后显示警告条。

---

## mover 的特殊处理

mover **不持有 `WATCH_PATH` 配置**——它通过 HTTP `POST /api/move` 接收 `target` 参数，target 由调用方（downloader）提供。

### mover UI 的"集合点路径"显示

mover UI 的路径区域是**只读聚合显示**（详见 `mover-ui-design.md`）：

- 聚合 `mover_state.json` 里**当前活跃**任务（`pending` / `copying`）的 `target` 字段
- 显示分布（如：`/HydenFileSystem/Archives` 5 个，`/legacy/path` 2 个）
- 提示文案："集合点路径在 Downloader 或 Unzipper 页面修改"

### mover 不实现 `POST /api/settings`

`/api/settings` 仅 downloader / unzipper 两侧实现。mover 不暴露此端点（无可改的路径）。

---

## API 规范

### `GET /api/settings`（downloader / unzipper）

返回当前路径 + 历史 + 偏好：

```json
{
  "ok": true,
  "output_path":   "/home/user/HydenFileSystem/Downloads",
  "path_history": [
    "/home/user/HydenFileSystem/Downloads",
    "/old/path/1",
    "/old/path/2"
  ],
  "use_last_path": true
}
```

注意：

- `output_path` 字段名**对 downloader 和 unzipper 都用同名**（含义不同）：
  - downloader 返回 `DOWNLOAD_DIR`
  - unzipper 返回 `OUTPUT_PATH` + 同时返回 `watch_path` 字段（unzipper 监听路径，与 downloader 的 WATCH_PATH 对应）
  - 实际命名：unzipper 返回 `{"output_path": ..., "watch_path": ..., ...}`，downloader 返回 `{"output_path": DOWNLOAD_DIR, "watch_path": WATCH_PATH, ...}`

- 各自 `path_history` 仅包含**自己**那个字段的历史；如果 unzipper 同时管理两个字段（OUTPUT_PATH 和 WATCH_PATH），需要分别返回 `output_path_history` / `watch_path_history`

### 字段细化（避免命名混乱）

```json
// downloader GET /api/settings
{
  "ok": true,
  "download_dir":          "...",
  "download_dir_history":  [...],
  "watch_path":            "...",          // 调 mover 时的 target
  "watch_path_history":    [...],
  "use_last_path":         true
}

// unzipper GET /api/settings
{
  "ok": true,
  "watch_path":            "...",          // watchdog 监听
  "watch_path_history":    [...],
  "output_path":           "...",          // 解压输出
  "output_path_history":   [...],
  "use_last_path":         true
}
```

### `POST /api/settings`

请求体（任一字段可选）：

```json
{
  "download_dir": "/new/path",         // downloader 仅
  "watch_path":   "/new/path",         // downloader / unzipper 都接受
  "output_path":  "/new/path",         // unzipper 仅
  "use_last_path": true                // 偏好更新
}
```

行为：

1. 验证路径绝对路径 + 可创建（`mkdir(parents=True, exist_ok=True)`，失败返回 400）
2. 更新内存（`config.XXX_PATH = new_path`）
3. 写回 `.env`（同 `save_env_settings` 模式）
4. 更新 `settings.json`：
   - 把旧路径加到 `xxx_history` 头部（如果不在已有列表中）
   - 截断到 10 条
   - 同步 `use_last_path` 偏好（如有）
5. 返回 200 + 新状态（同 GET 响应结构）

---

## settings.json 文件结构

每个模块独立的 `settings.json`：

```json
// downloader/settings.json
{
  "download_dir_history": ["..."],
  "watch_path_history":   ["..."],
  "use_last_path":        true
}

// unzipper/settings.json
{
  "watch_path_history":  ["..."],
  "output_path_history": ["..."],
  "use_last_path":       true
}
```

注意：**不保存"当前路径"**——当前路径以 `.env` 为单一真相源，启动时读取。

文件位置：项目根目录下 `downloader_settings.json` / `unzipper_settings.json`（与 `mover_state.json` 同级，避免与子模块目录混淆）。

`.gitignore` 加入这两个文件。

---

## 不在本次范围

- **迁移现有文件**：路径变更**只影响新任务**；旧文件留在原位由用户手动决定
- **Windows 实现**：`config.py` 默认值跨平台兼容，但 `start.sh` / `stop.sh` 仍是 Linux 脚本（详见 `P1-4c`）
- **路径有效性深度校验**：v1 仅做"绝对路径 + 可创建"两条；不检查权限、磁盘空间、文件系统类型
- **实时路径不一致警告**：只保留弹窗联动；banner 警告留 v2
- **mover 实现 `POST /api/settings`**：mover 没有可改的路径配置
