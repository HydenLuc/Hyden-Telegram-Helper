# SPDX-License-Identifier: AGPL-3.0-or-later
"""downloader 与 mover 模块的 HTTP 交互客户端。"""
import asyncio
import re
from pathlib import Path

import aiohttp

import config
from common.constants import ARCHIVE_EXTS
from common.logger import get_logger

_log = get_logger("downloader")

MULTIPART_RE = re.compile(r'\.7z\.\d+$')


def _should_auto_move(file_path: Path) -> bool:
    if not config.AUTO_MOVE:
        return False
    if config.WATCH_PATH is None:
        return False
    name = file_path.name.lower()
    return file_path.suffix.lower() in ARCHIVE_EXTS or bool(MULTIPART_RE.search(name))


# 提交搬运的重试节奏（秒）：首次立即 + 后续退避。避免 mover 完成那一刻偶发
# 不可达/超时导致压缩包永远留在 download/ 成为孤儿（不进 move/ → unzipper 认不出）。
_SUBMIT_BACKOFFS = (0, 2, 5, 10, 20)


async def auto_submit_to_mover(file_path: Path, target_dir: Path, task_id: str) -> None:
    """提交搬运请求；连接类失败自动重试。所有异常捕获，不向上抛出。

    仅对「没送达 mover」的传输错误（不可达/超时/其它异常）重试；一旦 mover
    应答（不论 ok 与否）即视为已受理，不再重试——那是 mover 的确定性判定。
    """
    url = f"http://{config.MOVER_HOST}:{config.MOVER_PORT}/api/move"
    payload = {"source": str(file_path), "target": str(target_dir), "task_id": task_id}
    last_err = ""
    for i, delay in enumerate(_SUBMIT_BACKOFFS):
        if delay:
            await asyncio.sleep(delay)
        if not file_path.exists():
            _log.error(f"[downloader→mover] 放弃提交（源文件已不存在）：{file_path.name}")
            return
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5), headers={'X-API-Key': config.API_KEY}) as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
            if data.get("ok"):
                suffix = f"（重试第 {i} 次成功）" if i else ""
                _log.info(f"[downloader→mover] 提交搬运：{file_path.name} → task_id={task_id}{suffix}")
            else:
                _log.error(f"[downloader→mover] 提交搬运被拒（{data.get('error')}）：{file_path.name}")
            return  # mover 已应答，无论 ok 都不再重试
        except aiohttp.ClientConnectorError:
            last_err = "mover 不可达"
        except asyncio.TimeoutError:
            last_err = "连接超时"
        except Exception as e:
            last_err = str(e)
        if i + 1 < len(_SUBMIT_BACKOFFS):
            _log.warning(f"[downloader→mover] 提交搬运第 {i + 1} 次失败（{last_err}），将重试：{file_path.name}")
    _log.error(f"[downloader→mover] 提交搬运重试耗尽（{last_err}），压缩包留在 download/ 未搬：{file_path.name}")
