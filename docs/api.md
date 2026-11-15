# API 参考

> 三模块（downloader / mover / unzipper）+ dashboard 的 HTTP / WebSocket 全部端点。
> 鉴权统一由 `common/auth.py` 处理，详见 §6 鉴权。

---

## 端点速查表

| 模块 | Method | Path | 一句话 |
|------|--------|------|--------|
| **Downloader (8091)** | | | |
| | GET    | `/api/state` | 完整快照（同 WS payload） |
| | GET    | `/api/status` | 精简状态（含 disk/duplicate/toast/index 计数） |
| | GET    | `/api/history` | 分页 + 排序 + 筛选已完成历史 |
| | GET    | `/api/search?q=` | iter_dialogs 服务端搜索聊天 |
| | GET    | `/api/settings` | 路径设置 + 路径历史 |
| | POST   | `/api/settings` | 修改路径 / 并发 / chunk_size |
| | GET    | `/api/duplicate-queue` | F6 重复下载队列 |
| | DELETE | `/api/duplicate-queue` | 清空队列 |
| | DELETE | `/api/duplicate-queue/{task_id}` | 忽略单条 |
| | POST   | `/api/duplicate-queue/{task_id}/download` | 重新下载单条 |
| | GET    | `/api/toasts` | MD5 dedup 待确认 toast 列表 |
| | POST   | `/api/toast/{toast_id}/queue` | 加入 duplicate_queue |
| | POST   | `/api/toast/{toast_id}/skip` | 跳过/删除已下载文件 |
| | POST   | `/api/toast/{toast_id}/download` | fuid 命中"直接下载" |
| | POST   | `/api/toast/{toast_id}/keep` | finish 命中"保留" |
| | POST   | `/api/toast/{toast_id}/open-matched` | 打开重复源文件夹 |
| | DELETE | `/api/toast/{toast_id}` | 强制删除 toast |
| | POST   | `/api/history-pull/start` | 创建历史下载 job（A/B/C） |
| | GET    | `/api/history-pull/jobs` | 列出 jobs（默认摘要；带 `?include=scan_results&job_id=` 取全量） |
| | POST   | `/api/history-pull/{job_id}/stop` | 停止扫描 |
| | POST   | `/api/history-pull/{job_id}/rescan` | 重置 last_seen_id |
| | POST   | `/api/history-pull/{job_id}/download-selected` | C 场景勾选下载 |
| | DELETE | `/api/history-pull/{job_id}` | 删除 job |
| | POST   | `/api/watch` | 添加监听频道 |
| | POST   | `/api/watch/reset-stats` | 全部频道 task_count 归零 |
| | POST   | `/api/watch/{cid}/reset-stats` | 单频道 task_count 归零 |
| | POST   | `/api/watch/{cid}/exempt` | 设置/取消"全局暂停例外"（**影响下载行为**）|
| | POST   | `/api/watch/{cid}/favorite` | 标记/取消"喜爱"（**纯前端标记，不影响下载**）|
| | DELETE | `/api/watch/{chat_id}` | 移除监听 |
| | POST   | `/api/auth` | 提交 Telegram 验证码 / 两步密码 |
| | POST   | `/api/retry` | 单条重试失败任务 |
| | POST   | `/api/retry-all-failed` | 批量重试所有 error/timeout |
| | POST   | `/api/download` | 手动下载指定 chat_id+message_id |
| | POST   | `/api/completed/clear` | 清空全部已完成（含 error） |
| | DELETE | `/api/history/done` | 仅清空 status=done |
| | POST   | `/api/history/move-group` | 整组文件夹搬到目标（走 mover） |
| | DELETE | `/api/completed/{task_id}` | 删单条历史记录 |
| | POST   | `/api/task/{task_id}/pause` | 暂停某个下载中任务 |
| | POST   | `/api/task/{task_id}/resume` | 恢复 |
| | POST   | `/api/task/{task_id}/cancel` | 取消下载 |
| | POST   | `/api/pause` | 全局软暂停监听 |
| | POST   | `/api/resume` | 恢复监听 |
| | POST   | `/api/exempt-pause` | 暂停**例外频道**的监听（与全局暂停各管一半）|
| | POST   | `/api/exempt-resume` | 恢复例外频道监听 |
| | POST   | `/api/open` | xdg-open 打开路径（限 DOWNLOAD_DIR / WATCH_PATH） |
| | WS     | `/ws` | 0.5s 推送完整 state |
| **Mover (8092)** | | | |
| | POST   | `/api/move` | 提交搬运任务（幂等 task_id） |
| | GET    | `/api/tasks` | 任务列表（status / limit / offset） |
| | GET    | `/api/tasks/{task_id}` | 单任务 |
| | DELETE | `/api/tasks/{task_id}` | 删单条记录 |
| | POST   | `/api/tasks/{task_id}/retry` | 重试 failed |
| | POST   | `/api/tasks/clear` | 清空历史 |
| | GET    | `/api/health` | 健康状态 + paused |
| | POST   | `/api/open` | 打开活跃任务 target.parent |
| | POST   | `/api/pause` / `/api/resume` | 软暂停 / 恢复 |
| | WS     | `/ws` | 1s 推送 tasks |
| **Unzipper (8093)** | | | |
| | GET    | `/api/state` | 完整快照 |
| | GET    | `/api/health` | health + paused |
| | GET    | `/api/pending` | 待确认多卷包列表 |
| | POST   | `/api/confirm/{id}` | 确认开解多卷包 |
| | POST   | `/api/submit` | 手动提交解压任务 |
| | GET    | `/api/history` | 解压历史 |
| | DELETE | `/api/history` | 清空历史 |
| | POST   | `/api/extract-status` | 批量查文件解压状态（filename） |
| | POST   | `/api/cancel/{task_id}` | 取消运行中解压任务 |
| | GET    | `/api/passwords` | 密码列表 |
| | POST   | `/api/passwords` | 添加密码 |
| | DELETE | `/api/passwords` | 删除密码 |
| | POST   | `/api/passwords/reorder` | 重排密码 |
| | GET    | `/api/concurrency` | 当前并发数 |
| | POST   | `/api/concurrency` | 修改并发数 |
| | GET    | `/api/settings` | 路径设置 |
| | POST   | `/api/settings` | 修改路径 |
| | POST   | `/api/pause` / `/api/resume` | 软暂停 / 恢复 |
| | POST   | `/api/open` | 打开 OUTPUT_PATH / WATCH_PATH 内路径 |
| | WS     | `/ws` | 1s 推送 current_tasks/pending/history |
| **Dashboard (8090)** | | | |
| | GET    | `/api/overview` | 后端代理：并发拉三模块 status 聚合 |

---

## 1. Downloader (port 8091)

### `GET /api/state`
- **响应**：完整 state（与 WS payload 同结构）。

### `GET /api/status[?slim=1]`

> ⚠️ **拉这个接口基本都该带 `?slim=1`**。默认响应含 `active` + `completed` 两个完整列表，
> 队列达到数万条时序列化出 **4.9MB**（历史峰值 22MB），downloader 忙的时候要几十秒。
> `?slim=1` 在**源头**就不序列化这两个列表，只给计数——概览/频道页要的字段一个不少。
> 实测：4,912,486 字节 / 1.23s → **18,611 字节 / 0.39s**（264 倍）。
>
> 2026-08-13 事故：dashboard 拉这个接口没带 slim → 超时 → `/api/overview` 返回
> `"data": null` → 网页频道页 504 空白、安卓 App 直接崩（JsonNull 解析异常）。
> ⚠️ **dashboard 自己的 `?slim=1` 只裁剪它发给浏览器的响应，救不了上游这一跳**——
> 两处都要带。

- **响应字段**：
  ```jsonc
  {
    "active":          [<task>...],     // 当前 active_downloads；slim=1 时为 []
    "active_count":    <int>,           // 恒有，slim 下用这个
    "completed":       [<rec>...],      // 历史记录（最大 5000）；slim=1 时为 []
    "completed_total": <int>,           // 恒有
    "watched":         {"<cid_str>": {name, watched_since, task_count, task_count_reset_at, exempt, favorite}},
    "total_speed":     <bytes_per_sec>,
    "paused":          <bool>,           // 全局暂停（管非例外频道）
    "exempt_paused":   <bool>,           // 例外暂停（管例外频道），见 exempt-channel-design.md §13
    "pending":         <int>,            // pending_tasks 数量
    "grouped_state_summary": {total_groups, done_groups},
    "disk_usage":      {free, total, pct_free, checked_at, error},
    "duplicate_count": <int>,
    "pending_toasts_count": <int>,
    "content_index_size":   {md5, fuid}
  }
  ```

### `GET /api/history`
- **Query**：
  - `limit` (1–200, 默认 50)
  - `offset` (默认 0)
  - `sort_by` ∈ `filename | filesize | status | finished_at | queued_at | extract_status`
  - `sort_order` ∈ `asc | desc`
  - `filter_status` 逗号分隔 extract_status 值
- **响应**：`{ok, items: [<rec>...], total, limit, offset}`

### `GET /api/search?q=<keyword>`
- **响应**：`[{name, id}, ...]`，最多 30 条 dialog。

### `GET /api/settings` / `POST /api/settings`
- **GET 响应**：
  ```jsonc
  {
    ok: true,
    max_total_connections, chunk_size,
    download_dir, watch_path,
    default_download_dir, default_watch_path,
    download_dir_history: [...], watch_path_history: [...],
    move_target_history:  [...],
    use_last_path: <bool>
  }
  ```
- **POST body**（任意字段可选）：`{download_dir?, watch_path?, max_total_connections?, chunk_size?, use_last_path?, sync_unzipper?}`

### `GET /api/duplicate-queue` / `DELETE` / `DELETE /api/duplicate-queue/{task_id}` / `POST /api/duplicate-queue/{task_id}/download`
- **GET 响应**：`{ok, queue: [<entry>...], count}`
- entry 字段（F6）：`task_id, chat_id, message_id, filename, size_mb, source_label, last_downloaded_at, previous_status, queued_at, grouped_id, duplicate_type, matched_filename, matched_path, matched_finished_at`

### `GET /api/toasts` / `POST /api/toast/{id}/{queue|skip|download|keep|open-matched}` / `DELETE /api/toast/{id}`
- toast 字段：`toast_id, trigger_source, duplicate_type, task_id, chat_id, message_id, filename, size_mb, source_label, matched_filename, matched_path, matched_finished_at, downloaded_path, created_at, expires_at_epoch`
- 详见 [md5-dedup-design.md §8](md5-dedup-design.md)

### `POST /api/history-pull/start`
- **body**：
  ```jsonc
  {
    scene: "A" | "B" | "C",
    chat:  "频道 ID 或 @username",
    filter_type: null | "id" | "date",   // 仅 B
    min_id?, max_id?, min_date?, max_date?,
    resume?: bool, force?: bool
  }
  ```
- **响应**：`{ok, job_id, chat_id, chat_name}` 或 `409 {existing_job_id, error}`

### `GET /api/history-pull/jobs?include=scan_results&job_id=<id>`
- 不带 `include`：返回摘要列表（`scan_results` 字段被替换为 `scan_results_count`）
- 带 `include`：返回单 job 全量（`{ok, job: {...}}`）

### `POST /api/history-pull/{job_id}/{stop|rescan|download-selected}` / `DELETE`
- `download-selected` body：`{message_ids: [int, ...]}`

### `POST /api/watch/{cid}/favorite`
- **body**：`{"favorite": true | false}`
- ⚠️ **纯展示标记，不影响任何下载行为**（跟 `exempt` 不同——那个会改暂停时收不收）。
  只给前端做置顶和筛选：两端都是 ⭐ 前缀 + 恒置顶（置顶逻辑放在升降序之后，
  否则选「升序」会把喜爱的埋到最底）。老频道记录没有这个键，读时一律 `.get("favorite", False)`。

### `POST /api/exempt-pause` / `POST /api/exempt-resume`
- 只管 `exempt=true` 的频道；与 `/api/pause`（管其余频道）各管一半，组合成四种状态。
- 不持久化，重启回默认。⚠️ **`bot.py` 启动时把两个都置 True**（重启永不静默开始下载）。
- 设计与真值表见 `exempt-channel-design.md` §13。

### `POST /api/watch` / `POST /api/watch/reset-stats` / `POST /api/watch/{cid}/{reset-stats|exempt}` / `DELETE /api/watch/{chat_id}`
- **add body**：`{id: <int>, name: <str>}`
- **exempt body**：`{exempt: bool}`

### `POST /api/auth`
- body：`{value: <code或password>}`，仅当 `state._auth_step` 非 idle 时有效。

### `POST /api/retry` / `POST /api/retry-all-failed`
- **retry body**：`{task_id: <str>}`
- **retry-all-failed**：无 body；响应 `{ok, total, queued, skipped: [{task_id, error}, ...]}`

### `POST /api/download`
- body：`{chat_id: int, message_id: int}`
- 响应：`{ok, task_id, filename, save_dir}` 或 `{ok, duplicate_pending: true, toast_id}`（fuid 命中）

### `POST /api/completed/clear` / `DELETE /api/history/done` / `POST /api/history/move-group` / `DELETE /api/completed/{task_id}`
- **move-group body**：`{gs_key: str, target_dir: str}`；走 mover，watcher 协程在 mover 完成后清理 completed 记录。

### `POST /api/task/{task_id}/{pause|resume|cancel}`
- 仅对 active_downloads 中状态为 `downloading`（pause）或 `waiting`/`paused`/`flood_wait`（cancel）的任务有效。

### `POST /api/pause` / `POST /api/resume`
- 全局软暂停 `state.monitoring_paused`；不影响 history-pull、retry、/api/download、recover。

### `POST /api/open`
- body：`{path: <abs_path>}`；只允许 `DOWNLOAD_DIR` / `WATCH_PATH` 内的路径。

### `WS /ws`
- 推送频率：0.5s + 状态变化即时推
- payload 字段（增量）：`active, completed, watched, auth, total_speed, active_conns, waiting_count, paused, disk_usage, duplicate_queue, duplicate_count, pending_toasts, history_jobs, settings`
- `history_jobs` 是**摘要模式**（不含完整 scan_results）

---

## 2. Mover (port 8092)

### `POST /api/move`
- body：`{source: <abs file/dir>, target: <abs parent dir>, task_id: <str>}`
- 幂等：
  - `task_id` 已 done → `{ok, already_moved, target_path}`
  - `pending`/`copying` → `{ok, in_progress, task_id}`
  - `failed` → 重排队
- 校验：source 必须在 `DOWNLOAD_DIR` / `WATCH_PATH` 内；target 不能在系统黑名单（`/etc /bin /usr ...`）

### `GET /api/tasks?status=&limit=&offset=`
- 响应：`{items: [<task>...], total}`，按 created_at 倒序

### `GET /api/tasks/{task_id}` / `DELETE /api/tasks/{task_id}` / `POST /api/tasks/{task_id}/retry` / `POST /api/tasks/clear`
- task 字段：`task_id, source, target, status, created_at, completed_at, error, files_attempted, files_completed, failed_at, error_source, is_cross_fs, total_size`

### `GET /api/health`
- 响应：`{ok, paused, semaphore_available}`

### `POST /api/open`
- body：`{path}`；仅允许活跃任务 target.parent

### `POST /api/pause` / `POST /api/resume`
- mover 暂停时新 submit 入队 status=pending；resume 触发批量 dispatch

### `WS /ws`
- 1s + 状态变化推送 tasks dict

---

## 3. Unzipper (port 8093)

### `GET /api/state` / `GET /api/health`
- state：`{current_tasks, pending, history, paused}`
- current_tasks 字段（含 P2-2/P2-4 新增）：`name, kind, status, started_at, trying_password, progress_pct, total_archives?, current_archive_idx?, current_archive?`
- 注意：`proc` 和 `cancel_event` 字段被 `_sanitize_current_tasks` 过滤，不出现在 WS / API

### `GET /api/pending` / `POST /api/confirm/{id}`
- 多卷包等待用户确认

### `POST /api/submit`
- body：`{path: <abs path to archive or folder>}`

### `GET /api/history` / `DELETE /api/history`
- history 字段：`name, kind, status (done|failed|partial|cancelled), out_dir, password, error, error_detail, archives, residuals, started_at, finished_at`

### `POST /api/extract-status`
- body：`{filenames: [str, ...]}`
- 响应：每个 filename → `{status, output_path, finished_at}` 或 `null`
- status 枚举：`extracting | pending_extract | extracted | extract_failed`

### `POST /api/cancel/{task_id}`
- 终止 7z 子进程 + 删除 target_dir + 写 cancelled history（P2-4）

### `GET/POST /api/passwords` / `DELETE /api/passwords` / `POST /api/passwords/reorder`
- 密码列表 CRUD + 拖拽排序

### `GET/POST /api/concurrency`
- 修改 `MAX_CONCURRENT_TASKS`，立即生效 + 写 .env

### `GET/POST /api/settings`
- 类似 downloader，含 watch_path / output_path / 路径历史

### `POST /api/pause` / `POST /api/resume`
- pause：watcher 不再入队；resume：扫描 WATCH_PATH 补提交未处理归档

### `POST /api/open`
- body：`{path}`；仅允许 OUTPUT_PATH / WATCH_PATH 内

### `WS /ws`
- 1s 推送（解压粒度较粗）

---

## 4. Dashboard (port 8090)

### `GET /api/overview`
- 后端代理：`asyncio.gather` 并发拉 downloader `/api/status` + mover `/api/health` + unzipper `/api/state`
- 离线判定：连续 2 次失败标 offline；1 次成功立即恢复
- 响应：
  ```json
  {
    "downloader": {"online": bool, "data": <full status>},
    "mover":      {"online": bool, "data": <health>},
    "unzipper":   {"online": bool, "data": <state>}
  }
  ```

---

## 5. WebSocket 鉴权

实现：`common/auth.py:check_ws_auth`。

### 检查顺序

1. `config.API_KEY` **为空字符串** → 所有 `/ws` 放行（兼容旧用户）
2. 非空时按以下顺序检查：
   - **query string**：`ws://host/ws?key=<API_KEY>`（首选；浏览器 WebSocket 不支持自定义 header）
   - **header**：`X-API-Key: <API_KEY>`（服务端调用，如 dashboard 后端代理）
3. 都不命中 → `401 Unauthorized`

### 浏览器示例

```js
const API_KEY = '__API_KEY__';
const ws = new WebSocket(`ws://${location.host}/ws?key=${encodeURIComponent(API_KEY)}`);
fetch('/api/status', {headers: {'X-API-Key': API_KEY}});
```

---

## 6. 鉴权 中间件

`common/auth.py:auth_middleware`：
- `config.API_KEY` 非空 + 路径以 `/api/` 开头 → 强制 `X-API-Key` header
- `/`（HTML）等静态路径不受保护

---

## 7. 错误码

| Status | 含义 |
|--------|------|
| 400 | 参数缺失 / 类型错误 / 格式校验失败 |
| 401 | API key / WebSocket key 不匹配 |
| 403 | 路径不在允许范围 / target 在黑名单 |
| 404 | 任务 / 资源 / 频道不存在 |
| 409 | 重复（如 history-pull 同 chat+scene 已有 job、密码重复）|
| 500 | 内部错误 / 子进程失败 |
| 502 | mover / 下游模块不可达 |

---

## 8. 内部约定

- 所有 `/api/` 端点 JSON 响应统一含 `ok: bool`；错误时含 `error: str`
- 时间字段：ISO 8601 字符串（`datetime.isoformat()`）；少数旧字段是 epoch float（`finished_at` 在某些路径）
- task_id 形式：
  - watch 触发：`{chat_id}_{message_id}`
  - `/api/download` 手动：`{chat_id}_{message_id}_api{ts}`
  - duplicate-queue 重新下载：`{chat_id}_{message_id}_dup{ts}`
  - history-pull：`{chat_id}_{message_id}_hist_{job_id_short}_{seq}`
  - mover：透传 downloader 的 task_id；move-group 用 `movegrp_{gs_key}`
