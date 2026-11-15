# SPDX-License-Identifier: AGPL-3.0-or-later
"""E2E 崩溃恢复（需要真实服务运行；默认 skip）。

跑法：pytest -m e2e tests/e2e/
"""
import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e


def test_pending_task_branch2_size_match(tmp_path: Path):
    """场景：注入一个 pending_task 指向已经存在且大小匹配的文件，
    重启后 recover_pending_tasks 走分支 2 → 标 done。

    这个测试需要：
    1. 启动 downloader 进程
    2. 写入 pending_tasks.json
    3. kill -9
    4. 重启
    5. 验证 completed.json 出现该 task_id
    """
    pytest.skip("需要真实进程编排，人工验证")


def test_pending_task_branch1_file_missing(tmp_path: Path):
    """场景：pending_task 指向不存在的文件 → 重新下载。"""
    pytest.skip("需要 Telethon 真实 message_id；人工测试覆盖")
