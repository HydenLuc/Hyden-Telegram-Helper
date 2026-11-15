# AI Agent 集成指南

## 概述

### Unzipper 作为 AI Agent 工具

Unzipper 是一个本地 HTTP 服务，为 AI agent 提供"给一个路径，自动解压"的能力。agent 只需提交文件路径，解压格式识别、密码管理、并发控制、失败处理全部由服务内部完成，结果通过历史记录或 WebSocket 事件返回。

### 适用场景

- 文件下载 agent 下载完压缩包后交给 unzipper 解压
- 数据清理 agent 批量处理归档文件
- 多步工作流中"解压"作为一个原子步骤
- RAG 系统处理压缩的文档库

### 不适用的场景

- 需要不解压直接读取压缩包内容
- 超大文件（> 10 GB）需要实时进度反馈（建议直接调用 `7z` 命令）
- 跨机器调度（unzipper 只处理本地路径）

---

## Agent 友好特性

1. **幂等健康检查**：`GET /api/health` 任何时候都安全，无副作用
2. **统一响应格式**：成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": "..."}`
3. **自解释错误**：`error` 字段是可读字符串，已分类（密码错误 / 文件损坏 / 卷缺失 / 磁盘空间不足 / 其他）
4. **路径安全校验**：agent 传入的路径会经过服务端验证，不会误操作 `OUTPUT_PATH` 里的已解压内容
5. **异步 + 轮询**：提交任务立即返回，agent 可并行处理其他事情
6. **历史持久化**：agent 崩溃重启后能通过 `GET /api/history` 查到之前任务的结果

---

## 核心工作流

### 工作流 A：提交单个任务并等待结果

最常见模式——提交一个 `.zip`，轮询直到完成。

```python
import requests
import time

BASE = "http://localhost:8093"

def submit_and_wait(path: str, timeout: int = 600) -> dict:
    """提交一个路径，等待完成，返回历史记录条目。"""
    r = requests.post(f"{BASE}/api/submit", json={"path": path})
    r.raise_for_status()
    data = r.json()
    if not data["ok"]:
        raise RuntimeError(data.get("error"))

    if data.get("pending_id"):
        # 文件夹或多卷包需要确认，agent 可选择自动确认
        raise RuntimeError(f"Task needs confirmation: {data['pending_id']}")

    name = data["name"]
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(3)
        r = requests.get(f"{BASE}/api/history", params={"limit": 10})
        for h in r.json()["items"]:
            if h["name"] == name and h["status"] in ("done", "failed", "partial"):
                return h

    raise TimeoutError(f"Task {name} did not complete in {timeout}s")

# 使用
result = submit_and_wait("/downloads/archive.zip")
if result["status"] == "done":
    print(f"Extracted to: {result['out_dir']}")
    print(f"Password used: {result.get('password') or '无密码'}")
else:
    print(f"Failed: {result.get('error')}")
```

### 工作流 B：批量提交并行处理

```python
import requests
import time

BASE = "http://localhost:8093"

# 按需调整并发数
requests.post(f"{BASE}/api/concurrency", json={"max": 6})

# 批量提交
archives = ["/downloads/a.zip", "/downloads/b.zip", "/downloads/c.zip"]
for path in archives:
    r = requests.post(f"{BASE}/api/submit", json={"path": path})
    print(r.json())

# 等待所有任务完成
while True:
    h = requests.get(f"{BASE}/api/health").json()
    if h["running_tasks"] == 0 and h["queue_depth"] == 0:
        break
    time.sleep(2)

# 查看最近结果
r = requests.get(f"{BASE}/api/history", params={"limit": len(archives)})
for item in r.json()["items"]:
    print(item["name"], item["status"], item.get("out_dir"))
```

### 工作流 C：处理需要确认的任务（文件夹 / 多卷包）

```python
r = requests.post(f"{BASE}/api/submit", json={"path": "/downloads/my_folder"})
data = r.json()

if data.get("pending_id"):
    # 自动确认（agent 决策：信任已知来源的路径则自动确认）
    pending_id = data["pending_id"]
    time.sleep(0.5)
    requests.post(f"{BASE}/api/confirm/{pending_id}")
```

### 工作流 D：密码错误时追加密码重试

```python
# 查询最近一条失败且原因是密码错误的记录
r = requests.get(f"{BASE}/api/history", params={"limit": 1, "status": "failed"})
items = r.json()["items"]

if items and items[0].get("error") == "密码错误":
    # 追加新密码
    requests.post(f"{BASE}/api/passwords", json={"password": "newpass"})
    # 重新提交原路径（需要 agent 记住路径，history 里不存原始路径）
    requests.post(f"{BASE}/api/submit", json={"path": "/downloads/archive.zip"})
```

---

## WebSocket 订阅（实时事件）

对需要实时反应的 agent，可用 WebSocket 替代轮询：

```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)

    # 正在运行的任务
    for tid, task in (data.get("current_tasks") or {}).items():
        print(f"[{tid}] {task['name']} - 密码: {task.get('trying_password')}")

    # 检查最新完成记录
    history = data.get("history") or []
    if history:
        latest = history[-1]
        if latest["status"] in ("done", "failed", "partial"):
            print(f"Completed: {latest['name']} → {latest['status']}")

ws = websocket.WebSocketApp(
    "ws://localhost:8093/ws",
    on_message=on_message,
)
ws.run_forever(reconnect=5)
```

WebSocket 推送频率约 1 次/秒（`_broadcast_loop` 广播循环），内容为完整状态快照（`current_tasks` + `pending` + `history`）。

---

## 路径安全约定

Agent 向 `/api/submit` 提交的路径须满足：

| 规则 | 说明 |
|------|------|
| 绝对路径 | 必须以 `/` 开头 |
| 路径存在 | 文件或目录必须已存在 |
| 不在 OUTPUT_PATH 内 | 防止 agent 意外处理输出目录 |

`/api/open` 的限制相反：路径**必须在** `OUTPUT_PATH` 内（防止 agent 打开任意文件）。

---

## 错误处理最佳实践

### 按错误类别处理

| `error` 字段值 | 建议处理 |
|----------------|----------|
| `"密码错误"` | 追加新密码（`POST /api/passwords`）后重新提交 |
| `"文件损坏"` | 重新下载源文件后重新提交 |
| `"卷缺失"` | 补全缺失分卷后重新提交 |
| `"磁盘空间不足"` | 清理 `OUTPUT_PATH` 或切换到其他分区 |
| `"其他: ..."` | 记录日志，人工介入 |

### HTTP 错误码处理

- `400 / 404 / 409`：参数问题，检查 agent 的调用逻辑
- `500`：服务端内部错误，可以重试一次

---

## 多 Agent 协作模式

```
下载 Agent
  ↓  下载完成，得到本地路径
  ↓  POST /api/submit {"path": "/downloads/x.zip"}
  ↓
Unzipper（本服务）
  ↓  解压完成，广播 WebSocket 事件
  ↓
整理 Agent（订阅 WebSocket）
  ↓  收到 history 新条目
  ↓  读取 out_dir，整理或索引文件
```

---

## 性能建议

| 场景 | 建议并发数 | 备注 |
|------|-----------|------|
| HDD 存储 | 2–3 | I/O 瓶颈，并发过高反而变慢 |
| SATA SSD | 4–6 | 读写各一块盘时可适当提高 |
| NVMe SSD | 6–12 | CPU 通常成为瓶颈 |
| 单文件 < 100 MB | 任意 | 延迟可忽略 |
| 大文件（1 GB+） | 用 WebSocket 监听完成事件 | 避免轮询超时 |

调整命令：

```bash
curl -X POST http://localhost:8093/api/concurrency \
  -H "Content-Type: application/json" \
  -d '{"max": 6}'
```

---

## 限制与注意事项

1. **无认证**：当前 API 无需任何凭证，建议仅本地或内网使用
2. **全局密码列表**：所有 agent 共享同一个密码列表，添加密码会对所有任务生效
3. **历史记录 100 条上限**：超出后最早记录被丢弃，长期批量任务需自行备份结果
4. **文件夹任务须确认**：设计上防止误触发，agent 可主动调用 `/api/confirm/{id}` 跳过
5. **路径仅限本机**：unzipper 只处理本地文件系统路径，不支持 URL 或远程路径

---

## 调试技巧

```bash
# 查看服务状态
curl http://localhost:8093/api/health | jq

# 查看最近 5 条历史
curl "http://localhost:8093/api/history?limit=5" | jq

# 订阅实时事件（需安装 websocat）
websocat ws://localhost:8093/ws

# 测试路径提交
curl -X POST http://localhost:8093/api/submit \
  -H "Content-Type: application/json" \
  -d '{"path": "/some/path"}' -v
```

---

## 完整示例：最简 Agent

```python
#!/usr/bin/env python3
"""
监控下载目录，自动提交新压缩包到 unzipper 解压。
"""
import time
import requests
from pathlib import Path

UNZIPPER_BASE = "http://localhost:8093"
WATCH_DIR = Path("/downloads")
EXTENSIONS = {".zip", ".rar", ".7z"}

seen = set()

while True:
    for f in WATCH_DIR.iterdir():
        if f.suffix not in EXTENSIONS or f.name in seen:
            continue
        seen.add(f.name)

        r = requests.post(
            f"{UNZIPPER_BASE}/api/submit",
            json={"path": str(f.resolve())}
        )
        data = r.json()
        if data["ok"]:
            print(f"[agent] Submitted: {f.name}")
            if data.get("pending_id"):
                # 自动确认
                requests.post(f"{UNZIPPER_BASE}/api/confirm/{data['pending_id']}")
        else:
            print(f"[agent] Error: {data.get('error')}")

    time.sleep(10)
```
