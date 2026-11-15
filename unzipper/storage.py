# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
from pathlib import Path

import config
from common.atomic_io import atomic_write_json
from common.env_writer import save_env_value
from common.settings_store import SettingsStore
from common.logger import get_logger

_log = get_logger("unzipper")

_STORAGE_FILE = config.STATE_DIR / "unzipper_history.json"  # 状态目录见 config.STATE_DIR（Docker = /state；原生 = 项目 state/）
_ENV_FILE     = config.ENV_FILE  # 统一走 config（原生 = 项目根的 .env；Docker = /state/.env 覆盖层），见 config.py 开头
_MAX_HISTORY  = 100

_settings_store = SettingsStore(config.UNZIPPER_SETTINGS_FILE, ["watch_path", "output_path"])


def _atomic_write_json(path: Path, data) -> None:
    try:
        atomic_write_json(path, data)
    except Exception as e:
        _log.error(f"[unzipper] 保存 {path.name} 失败: {e}")


def load_history() -> list:
    if not _STORAGE_FILE.exists():
        return []
    try:
        data = json.loads(_STORAGE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        _log.error(f"[unzipper] 加载 history 失败: {e}")
        return []


def save_history(history: list):
    data = history[-_MAX_HISTORY:] if len(history) > _MAX_HISTORY else history
    _atomic_write_json(_STORAGE_FILE, data)


def save_setting_to_env(key: str, value: str):
    """原子写 key=value 到 .env，已存在则替换，否则追加。"""
    try:
        save_env_value(_ENV_FILE, key, value)
    except Exception as e:
        _log.error(f"[unzipper] 保存 {key} 到 .env 失败: {e}")


# ── P1-pwd: 密码独立 JSON 存储 + 旧 .env 格式迁移 ────────────────────────────

def load_passwords() -> list[str]:
    """加载 passwords.json；不存在 → 尝试从 .env PASSWORDS= 迁移；都没有返回 []."""
    if config.PASSWORDS_FILE.exists():
        try:
            data = json.loads(config.PASSWORDS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [p for p in data if isinstance(p, str)]
            return []
        except Exception as e:
            _log.error(f"[unzipper] 加载 passwords.json 失败: {e}")
            return []

    # 兼容性迁移：从 .env PASSWORDS= 读一次（不再删除 .env 行，让用户自己保留备份）
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


# 兼容旧调用（向后兼容，但后续会删；新代码请用 save_passwords）
def save_passwords_to_env(passwords: list[str]):
    """已废弃：旧版逗号分隔格式。新版直接调 save_passwords()."""
    save_passwords(passwords)


# ── P1-6: unzipper_settings.json (路径历史 + 偏好) ────────────────────────────

def load_settings() -> dict:
    return _settings_store.load()


def save_settings(data: dict) -> None:
    _settings_store.save(data)


def add_path_to_history(settings: dict, field: str, path_str: str) -> None:
    _settings_store.add_to_history(settings, field, path_str)
