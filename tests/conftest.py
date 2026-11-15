# SPDX-License-Identifier: AGPL-3.0-or-later
"""共享 fixtures。

加载 .env 时使用项目根目录的 .env，但单元测试应避免污染——
每个 test 用 tmp_path 隔离。
"""
import os
import sys
from pathlib import Path

# Make project root importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set required-but-empty env vars before importing config
# （config.py 在 import 时会读 API_ID 等，缺失会 ValueError）
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "deadbeef" * 4)
os.environ.setdefault("PHONE", "+1234567890")

# 状态目录用一次性的临时目录（2026-11-11 起状态统一放 config.STATE_DIR）。
# 不设的话原生环境默认是项目里的 state/ —— 测试会往真实的状态目录里写东西。
import tempfile as _tempfile
os.environ.setdefault("STATE_DIR", _tempfile.mkdtemp(prefix="tghelper-test-state-"))
# 测试只听本机：不让开发机 .env 里的 LISTEN_HOST=0.0.0.0（又没设 API_KEY）触发「拒绝启动」。
# load_dotenv 不覆盖已有环境变量，所以这里先设好就行。
os.environ.setdefault("LISTEN_HOST", "127.0.0.1")

import pytest


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """空 .env 路径用于 env_writer 测试。"""
    return tmp_path / ".env"


@pytest.fixture
def tmp_settings_file(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"
