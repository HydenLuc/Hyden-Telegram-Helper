# Mover 测试场景清单

## 测试策略

自动化测试在 `tests/integration/test_mover_*.py`；下面是最初手动端到端验证用的场景清单，留作参考。

---

## 基本搬运

- [ ] 单文件同文件系统：`source` 为单个文件，source 和 target 在同一磁盘，验证文件完整到达
- [ ] 文件夹同文件系统：`source` 为目录，验证目录结构和所有子文件完整到达
- [ ] 单文件跨文件系统：source 和 target 在不同磁盘，验证内容一致（md5），源文件被删除
- [ ] 文件夹跨文件系统：同上，目录结构和所有子文件完整，源目录被删除

## 原子性验证

- [ ] 搬运过程中 target_parent 下不出现正式目录名（只有 `.mover_staging_*` 隐藏目录）
- [ ] rename 完成后隐藏目录消失，正式目录出现
- [ ] unzipper 的 watchdog **不触发** staging 隐藏目录（需要 unzipper 配合过滤 `.` 开头）
- [ ] unzipper 的 watchdog **触发** rename 后的正式目录

## 幂等性

- [ ] 同 `task_id`，status=`pending`：重复提交返回 `{"ok": true, "in_progress": true}`，不新增任务
- [ ] 同 `task_id`，status=`copying`：重复提交返回 `{"ok": true, "in_progress": true}`，不干扰正在进行的搬运
- [ ] 同 `task_id`，status=`done`：重复提交返回 `{"ok": true, "already_moved": true, "target_path": "..."}`，不重复搬运
- [ ] 同 `task_id`，status=`failed`：重复提交覆盖旧记录，重新入队执行

## 并发测试

- [ ] 同时发起 3 个不同 task_id 的 move 请求（等于 `MOVER_MAX_CONCURRENT` 默认值）：全部并发执行
- [ ] 同时发起 5 个请求（超过默认并发数）：前 3 个并发，后 2 个排队等待 Semaphore
- [ ] 并发中其中一个失败：不影响其他任务继续执行

## 失败与回滚

- [ ] 搬运目标父目录不可写（权限不足）：任务立即进入 `failed`，staging 不残留，源文件完整
- [ ] 复制中途磁盘写满：任务进入 `failed`，清理 staging，源文件完整
- [ ] 单个子文件复制失败：整个任务 `failed`（All-or-nothing），staging 被清理，已完成的子文件也删除
- [ ] 失败任务重试（`POST /api/tasks/{task_id}/retry`）：source 仍存在时能成功重新执行

## 重启恢复

- [ ] 任务处于 `copying` 时强制杀进程重启：重启后 staging 目录被清理，任务标记 `failed`
- [ ] 任务处于 `pending` 时强制杀进程重启：重启后任务仍是 `pending`，重新入队（TODO：当前实现需确认是否重新调度）
- [ ] 孤儿 staging 目录（来自旧版/崩溃）：启动时被自动清理

## 边界情况

- [ ] 目标路径已存在同名目录：mover 用 `_000/_001` 递增后缀解决冲突，返回实际 `target_path`
- [ ] source 路径不存在：立即返回 400/404 错误，不创建任务
- [ ] source 和 target 在同一路径：返回 400 错误（避免自移动循环）
- [ ] source 是 target 的子目录：返回 400 错误
- [ ] 超大文件（> 10 GB）跨文件系统：验证进度正常更新，WebSocket 推送 `files_completed` 递增
- [ ] task_id 包含特殊字符（空格、`/`、Unicode）：验证持久化和查询不出错

## WebSocket 推送

- [ ] 任务从 `pending` → `copying` → `done` 全流程 WebSocket 事件顺序正确
- [ ] `files_completed` 在搬运过程中单调递增
- [ ] `failed` 时 WebSocket 推送包含 `error` 字段和 `failed_at` 文件路径
