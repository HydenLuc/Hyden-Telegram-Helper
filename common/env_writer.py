# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from common.atomic_io import atomic_write_text


def _rewrite_env(env_path: Path, kvs: dict[str, str]) -> None:
    # 值可能来自用户表单（如 DOWNLOAD_DIR 等路径字段），若含 \n/\r/\x00，写文件时
    # 会被解释成新的一行，等于任意注入 .env 变量（含 API_KEY/BOT_TOKEN）。统一在
    # 写入前拦截，而不是只在某一个调用方（如 dashboard /api/config）校验。
    for k, v in kvs.items():
        if any(c in k for c in "\n\r\x00=") or any(c in v for c in "\n\r\x00"):
            raise ValueError(f".env 字段包含非法字符（换行/NUL/等号），拒绝写入：{k}")

    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    written: set[str] = set()
    result: list[str] = []
    for line in lines:
        k = line.split("=", 1)[0].strip()
        if k in kvs:
            result.append(f"{k}={kvs[k]}")
            written.add(k)
        else:
            result.append(line)
    for k, v in kvs.items():
        if k not in written:
            result.append(f"{k}={v}")
    atomic_write_text(env_path, "\n".join(result) + "\n")


def save_env_value(env_path: Path, key: str, value: str) -> None:
    """原子写单个 key=value 到 .env 文件。

    - 已有该 key → 替换对应行
    - 没有该 key → 追加到末尾
    - 使用 tmp + os.replace 原子写，避免半截文件
    """
    _rewrite_env(env_path, {key: value})


def save_env_values(env_path: Path, kvs: dict[str, str]) -> None:
    """批量原子写多个 key=value 到 .env 文件。"""
    if not kvs:
        return
    _rewrite_env(env_path, kvs)
