# SPDX-License-Identifier: AGPL-3.0-or-later
"""通用 settings.json 读写（路径历史 + use_last_path 偏好）。

downloader 和 unzipper 各自实例化一份 SettingsStore，传入文件路径和管理的字段名列表。
"""
import json
from pathlib import Path

from common.atomic_io import atomic_write_json

_HISTORY_MAX = 10


class SettingsStore:
    def __init__(self, file_path: Path, history_keys: list[str]):
        self.file_path = file_path
        self.history_keys = list(history_keys)

    def _default(self) -> dict:
        return {
            "path_history": {k: [] for k in self.history_keys},
            "use_last_path": True,
        }

    def load(self) -> dict:
        if not self.file_path.exists():
            return self._default()
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return self._default()
        except Exception as e:
            print(f"[settings_store] 加载 {self.file_path.name} 失败: {e}")
            return self._default()
        data.setdefault("path_history", {})
        for k in self.history_keys:
            data["path_history"].setdefault(k, [])
        data.setdefault("use_last_path", True)
        return data

    def save(self, data: dict) -> None:
        atomic_write_json(self.file_path, data)

    def add_to_history(self, data: dict, field: str, path_str: str) -> None:
        """旧路径插入历史头部 + 去重 + 截 10 条。原地修改 data。"""
        if not path_str:
            return
        history = data.setdefault("path_history", {}).setdefault(field, [])
        history = [p for p in history if p != path_str]
        history.insert(0, path_str)
        data["path_history"][field] = history[:_HISTORY_MAX]
