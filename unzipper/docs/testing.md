# 测试记录

## 测试策略

目前项目没有自动化测试（pytest），所有验证通过手动脚本 + 端到端实测完成。测试脚本在运行时生成于 `/tmp/`，未进入仓库。

---

## 已覆盖的测试场景

### 解压引擎

- [x] 无密码 `.zip`
- [x] 有密码 `.zip`（AES 加密，pyzipper）
- [x] 无密码单体 `.7z`
- [x] 有密码单体 `.7z`
- [x] 无密码多卷 `.7z.001/.002`（py7zr 简单分卷）
- [x] 真实多卷 `.7z.001/.002/.003`（系统 `7z` 命令生成）
- [x] 密码逐个尝试直到成功
- [x] 全部密码失败 → 分类为"密码错误"
- [x] 无密码包优先尝试无密码（避免假阳性）

### 文件夹任务

- [x] 简单文件夹（含 zip + 非压缩包文件）
- [x] 多层嵌套文件夹（3 层目录 + 子目录里的压缩包）
- [x] 真实 Telegram 下载文件夹（10+ GB，4 个多卷包）
- [x] 部分失败场景（6 个压缩包，4 成功 2 失败）
- [x] 非压缩包文件按相对目录结构移入任务根
- [x] 源文件夹无残留时自动删除

### 失败处理

- [x] 密码全错 → `任务失败.txt` + 移入 `@任务失败/`
- [x] 文件夹任务部分失败 → 整体移入 `@任务失败/`
- [x] 失败原因正确分类（密码错误、文件损坏、卷缺失等）

### API

- [x] `GET /api/health`
- [x] `POST /api/submit`（单包 + 文件夹 + 多卷）
- [x] `GET /api/pending`
- [x] `GET /api/history`（含 `status`/`kind` 过滤和 `limit`/`offset` 分页）
- [x] `DELETE /api/history`
- [x] `GET /POST /DELETE /api/passwords`
- [x] `GET /POST /api/concurrency`
- [x] `POST /api/open`（路径安全校验：绝对路径、存在、不在 OUTPUT_PATH 内）

### 并发

- [x] 3 个大文件同时提交，验证加速比 2.9×（100 MB × 3，tmpfs）
- [x] 运行时调整并发数（`POST /api/concurrency {"max": N}`）
- [x] 前端多任务卡片并行显示
- [x] 每个任务独立计时器（`elapsedTimers Map`）

### UI

- [x] WebSocket 自动重连
- [x] 失败行红色高亮 + 错误详情列
- [x] 文件夹任务详情展开（显示子压缩包列表）
- [x] 展开状态在 WebSocket 推送后保持（`expandedRows Set`）
- [x] 打开文件夹按钮（`xdg-open`）

### 持久化

- [x] 历史记录 `unzipper_history.json`（重启后恢复）
- [x] 密码修改通过 API 后回写 `.env`
- [x] 并发数修改通过 API 后回写 `.env`

---

## 未覆盖的场景 / 已知风险

- [ ] 超大文件（> 10 GB）解压中途中断恢复
- [ ] 磁盘空间不足（`OSError: [Errno 28] No space left on device`）的完整路径（错误分类已实现，未实测）
- [ ] watchdog 在 NFS / SMB 挂载目录的兼容性
- [ ] 中文文件名在非 UTF-8 locale 下的编码问题
- [ ] 压缩炸弹（zip bomb）防护
- [ ] 单元测试覆盖率（`utils.py` / `storage.py` 的纯函数最适合先写）

---

## 如何复现核心测试

以下脚本可直接复制运行（在项目根目录，已激活 venv）。

### 无密码 zip

```bash
mkdir -p /tmp/nopass_test
.venv/bin/python - << 'EOF'
import zipfile
with zipfile.ZipFile("/tmp/nopass_test/plain.zip", "w") as z:
    z.writestr("hello.txt", "Hello World")
EOF

.venv/bin/python - << 'EOF'
import asyncio, sys
sys.path.insert(0, ".")
from unzipper.extractor import extract
from pathlib import Path
result = asyncio.run(extract(
    Path("/tmp/nopass_test/plain.zip"),
    explicit_out_dir=Path("/tmp/nopass_test/out"),
))
print(result)
EOF
```

### 有密码 zip（AES）

```bash
.venv/bin/python - << 'EOF'
import pyzipper
with pyzipper.AESZipFile("/tmp/pass_test.zip", "w",
    compression=pyzipper.ZIP_DEFLATED,
    encryption=pyzipper.WZ_AES) as z:
    z.setpassword(b"test123")
    z.writestr("secret.txt", "加密内容")
EOF

.venv/bin/python - << 'EOF'
import asyncio, sys
sys.path.insert(0, ".")
from unzipper.extractor import extract
from pathlib import Path
result = asyncio.run(extract(
    Path("/tmp/pass_test.zip"),
    passwords=["wrong1", "test123"],
    explicit_out_dir=Path("/tmp/pass_out"),
))
print(result)
EOF
```

### 文件夹任务（含多层嵌套）

```bash
.venv/bin/python - << 'EOF'
import zipfile, os
from pathlib import Path

base = Path("/tmp/folder_test/input")
(base / "sub/deep").mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(base / "top.zip", "w") as z:
    z.writestr("a.txt", "top level")
with zipfile.ZipFile(base / "sub" / "nested.zip", "w") as z:
    z.writestr("b.txt", "nested")
(base / "readme.txt").write_text("non-archive file")
EOF

.venv/bin/python - << 'EOF'
import asyncio, sys
sys.path.insert(0, ".")
from pathlib import Path
import unzipper.manager as manager
import unzipper.state as state

async def run():
    await manager._process_folder(Path("/tmp/folder_test/input"))
    for h in state.history:
        print(h["name"], h["status"])

asyncio.run(run())
EOF
```

### 并发验证（3 任务同时提交）

```bash
# 准备 3 个 100 MB 测试文件（tmpfs）
for i in 1 2 3; do
  dd if=/dev/urandom bs=1M count=100 2>/dev/null | gzip > /tmp/big${i}.gz
  .venv/bin/python -c "
import zipfile; z = zipfile.ZipFile('/tmp/concurrent${i}.zip','w',zipfile.ZIP_STORED)
z.write('/tmp/big${i}.gz','big.gz'); z.close()
"
done

# 提交并检查时间戳重叠
curl -s -X POST http://localhost:8093/api/submit -H "Content-Type: application/json" \
  -d '{"path":"/tmp/concurrent1.zip"}' &
curl -s -X POST http://localhost:8093/api/submit -H "Content-Type: application/json" \
  -d '{"path":"/tmp/concurrent2.zip"}' &
curl -s -X POST http://localhost:8093/api/submit -H "Content-Type: application/json" \
  -d '{"path":"/tmp/concurrent3.zip"}' &
wait

# 查看历史，确认 started_at 重叠（3 个任务开始时间 < 最短单任务耗时）
sleep 5
curl -s http://localhost:8093/api/history | python3 -m json.tool | grep -E '"started_at|finished_at|name"'
```
