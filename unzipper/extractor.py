# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Optional

import config
from common.logger import get_logger
from common.pathlimits import MAX_NAME_BYTES, FS_NAME_LIMIT_BYTES

_log = get_logger("unzipper")

def _find_7z() -> Optional[str]:
    """找 7-Zip 的命令行程序，返回可执行文件路径；找不到返回 None。

    以前只认 PATH 里的 `7z`，于是（2026-11-11 跨环境排查发现）：
      · macOS：brew 的 `sevenzip` 包装出来的命令叫 `7zz`，不叫 7z
      · Windows：7-Zip 默认装在 Program Files，不会加进 PATH
    两种情况多卷包都会直接解压失败。现在的查找顺序：
      1. 环境变量 SEVENZIP_BIN（用户自己指定，最优先）
      2. PATH 里的 7z / 7zz / 7za
      3. Windows 默认安装目录
    """
    env_bin = os.getenv("SEVENZIP_BIN", "").strip()
    if env_bin:
        found = env_bin if Path(env_bin).is_file() else shutil.which(env_bin)
        if found:
            return found
        _log.warning(f"[unzipper] SEVENZIP_BIN={env_bin} 找不到这个程序，改为自动查找")
    for name in ("7z", "7zz", "7za"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                candidate = Path(base) / "7-Zip" / "7z.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


SEVEN_ZIP: Optional[str] = _find_7z()
HAS_7Z = SEVEN_ZIP is not None
if HAS_7Z:
    _log.info(f"[unzipper] 使用 7-Zip：{SEVEN_ZIP}")
else:
    _log.warning("[unzipper] 警告：未找到 7-Zip（7z / 7zz / 7za），多卷包支持受限。"
                 "Linux 装 p7zip-full，macOS `brew install sevenzip`，Windows 装 7-Zip；"
                 "装在别处可以用环境变量 SEVENZIP_BIN 指定路径")



def _rar_tool_ok() -> bool:
    """rar 要靠外部程序解（unrar / unar / 7z / bsdtar 任一）。启动时查一次，缺了就提前说，
    别等第一个 rar 包解失败才发现（2026-11-13）。"""
    try:
        import rarfile
        rarfile.tool_setup()
        return True
    except Exception:
        return False


HAS_RAR_TOOL = _rar_tool_ok()
if not HAS_RAR_TOOL:
    _log.warning("[unzipper] 警告：找不到能解 rar 的程序，.rar 文件会解压失败。"
                 "装其中一个即可：Linux `apt install unrar`（或 7zip），macOS `brew install unar`；"
                 "Docker 镜像里已经装好")

# Windows 上 7-Zip 默认按系统代码页（GBK / cp1252）输出，中文文件名会乱码；
# 这个参数让它输出 UTF-8。只在 Windows 加：老版本的 Linux p7zip 不一定认识它。
_7Z_CHARSET_ARGS = ["-sccUTF-8"] if os.name == "nt" else []

async def warn_if_names_too_long(archive_path: Path, password: Optional[str] = None) -> int:
    """解压**前**用 `7z l` 扫一遍条目名，超长的先告警。返回超长条目数。

    为什么要有这一步：`7z x` 没有「解压时改名」的选项，包里那个 288 字节的条目
    会照原样去创建，在 ZFS/APFS 上直接 ENAMETOOLONG。7z 会把它算进
    `Sub items Errors`，整个任务判失败——**但错误信息里只有一个路径，
    看不出「是名字太长」这回事**，排查起来是个谜。先扫一遍就能一眼看到。

    只是告警，不阻止解压：多数情况下其余条目能正常解出来，
    落盘之后再由 manager 调 `fix_long_names` 收拾。

    ⚠️ 扫不动就返回 0（无 7z / 加密包 / 格式不支持），**不能因此挡住解压**。
    """
    if not HAS_7Z:
        return 0
    cmd = [SEVEN_ZIP, "l", "-ba", "-slt", *_7Z_CHARSET_ARGS, str(archive_path)]
    if password:
        cmd.append(f"-p{password}")
    else:
        cmd.append("-p")          # 空密码，避免加密包卡在交互提示上
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except (OSError, asyncio.TimeoutError):
        return 0

    n = 0
    for line in out.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("Path = "):
            continue
        entry = line[len("Path = "):]
        for part in entry.replace("\\", "/").split("/"):
            if len(part.encode("utf-8")) > MAX_NAME_BYTES:
                n += 1
                _log.warning(
                    f"[unzipper] ⚠️ {archive_path.name} 里有超长条目名"
                    f"（{len(part.encode('utf-8'))} 字节 > {MAX_NAME_BYTES}）："
                    f"{part[:60]!r}…  文件系统上限是 {FS_NAME_LIMIT_BYTES} 字节，"
                    f"这一条很可能解不出来")
                break
        if n >= 20:
            _log.warning(f"[unzipper] ⚠️ {archive_path.name} 超长条目太多，只列前 20 条")
            break
    return n


# 7z / unrar 的进度行内含 "XX%"。单字节流读取，按 \r/\n 切片。
_RE_PCT = re.compile(rb"(\d{1,3})%")

# 7z 超时：硬编码 600s 对几十 GB 的大包在 USB/网络盘上几乎必超时（正常解压中）。
# 按体积估算，UNZIPPER_7Z_TIMEOUT 环境变量可整体覆盖（秒）。
_7Z_MIN_TIMEOUT_S    = 600                # 原有下限：小文件也要留够启动/校验开销
_7Z_MIN_THROUGHPUT_BPS = 5 * 1024 * 1024  # 5 MB/s，USB/网络盘保守估计下限


def _compute_7z_timeout(archive_path: Path) -> float:
    override = os.getenv("UNZIPPER_7Z_TIMEOUT")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    try:
        if archive_path.name.lower().endswith('.7z.001'):
            size = sum(p.stat().st_size for p in find_multipart_parts(archive_path))
        else:
            size = archive_path.stat().st_size
    except OSError:
        size = 0
    return max(_7Z_MIN_TIMEOUT_S, size / _7Z_MIN_THROUGHPUT_BPS)


class ExtractError(Exception):
    """Raised by extract() on failure; carries a short reason string."""
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def archive_stem(path: Path) -> str:
    name = path.name
    if name.lower().endswith('.7z.001'):
        return name[:-len('.7z.001')]
    return path.stem


def find_multipart_parts(first: Path) -> list[Path]:
    stem = first.name[:-len('.001')]   # e.g. "archive.7z"
    parts = []
    i = 1
    while True:
        part = first.parent / f"{stem}.{i:03d}"
        if not part.exists():
            break
        parts.append(part)
        i += 1
    return parts


def find_missing_volume(first: Path) -> Optional[int]:
    """检测多卷序列是否有缺口。

    收集目录内所有 <stem>.NNN 卷号，若最大卷号之前有缺号（例如有 .003 和 .005 但缺 .004），
    返回第一个缺失卷号；序列连续则返回 None。用于解压前预判"卷缺失"，避免误报密码错误。
    """
    stem = first.name[:-len('.001')]   # e.g. "archive.7z"
    pat = re.compile('^' + re.escape(stem) + r'\.(\d{3})$')
    nums: set[int] = set()
    try:
        for e in os.scandir(first.parent):
            m = pat.match(e.name)
            if m:
                nums.add(int(m.group(1)))
    except OSError:
        return None
    if not nums:
        return None
    for k in range(1, max(nums) + 1):
        if k not in nums:
            return k
    return None


# ── 进度流解析 ────────────────────────────────────────────────────────────────

async def _stream_progress(proc, on_pct: Optional[Callable[[int], Awaitable[None]]]):
    """读 proc.stdout 字节流，解析 'XX%' 进度，去重后回调 on_pct(pct)。"""
    if on_pct is None or proc.stdout is None:
        # 仍然 drain stdout 防止管道阻塞
        if proc.stdout is not None:
            await proc.stdout.read()
        return
    last_pct = -1
    buf = b""
    try:
        while True:
            chunk = await proc.stdout.read(256)
            if not chunk:
                # 解析最后剩余 buf
                if buf:
                    matches = _RE_PCT.findall(buf)
                    if matches:
                        try:
                            pct = int(matches[-1])
                            if 0 <= pct <= 100 and pct != last_pct:
                                await on_pct(pct)
                        except ValueError:
                            pass
                return
            buf += chunk
            # 找到最后一次 \r 或 \n 之前的 line
            last_idx = max(buf.rfind(b"\r"), buf.rfind(b"\n"))
            if last_idx < 0:
                continue
            line = buf[:last_idx + 1]
            buf = buf[last_idx + 1:]
            matches = _RE_PCT.findall(line)
            if not matches:
                continue
            try:
                pct = int(matches[-1])
            except ValueError:
                continue
            if 0 <= pct <= 100 and pct != last_pct:
                last_pct = pct
                try:
                    await on_pct(pct)
                except Exception:
                    pass    # 进度回调异常不影响解压
    except Exception as e:
        _log.warning(f"[unzipper] 进度解析异常: {type(e).__name__}: {e}")


# ── async 7z（带进度）────────────────────────────────────────────────────────

async def _extract_7z_async(archive_path: Path, out_dir: Path, password: Optional[str],
                            on_pct: Optional[Callable[[int], Awaitable[None]]],
                            register_proc: Optional[Callable[[Optional[asyncio.subprocess.Process]], None]] = None):
    """走系统 7z 命令，asyncio subprocess + 实时进度解析。
    无 7z 命令时降级到 py7zr（同步，无实时进度）。
    register_proc(proc): 暴露 process handle 给外层（用于 P2-4 取消）。
    """
    if HAS_7Z:
        # -bsp1: progress to stdout (default stderr); -bso0: silence file list output;
        # -bse2: errors to stderr (default).
        cmd = [SEVEN_ZIP, "x", str(archive_path), f"-o{out_dir}", "-y", "-bsp1", "-bso0", *_7Z_CHARSET_ARGS]
        cmd.append(f"-p{password}" if password else "-p")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if register_proc:
            try:
                register_proc(proc)
            except Exception:
                pass
        # 同时读 stdout（进度）和 stderr（错误）
        stderr_chunks: list[bytes] = []
        async def _drain_stderr():
            while True:
                chunk = await proc.stderr.read(1024)
                if not chunk:
                    return
                stderr_chunks.append(chunk)

        timeout_s = _compute_7z_timeout(archive_path)
        try:
            try:
                await asyncio.wait_for(
                    asyncio.gather(_stream_progress(proc, on_pct), _drain_stderr(), proc.wait()),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise RuntimeError(f"7z 解压超时（>{int(timeout_s)}s）")
        finally:
            if register_proc:
                try:
                    register_proc(None)
                except Exception:
                    pass

        if proc.returncode != 0:
            err = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
            raise RuntimeError(err or f"7z 退出码 {proc.returncode}")
        return

    # py7zr fallback：同步，无进度
    import py7zr
    loop = asyncio.get_event_loop()
    def _do():
        kwargs = {'password': password} if password else {}
        with py7zr.SevenZipFile(archive_path, mode='r', **kwargs) as z:
            z.extractall(path=out_dir)
    await loop.run_in_executor(None, _do)


# ── sync 包装为 async（zip/rar 没有进度）────────────────────────────────────

async def _extract_zip_async(archive_path: Path, out_dir: Path, password: Optional[str],
                             on_pct: Optional[Callable[[int], Awaitable[None]]],
                             register_proc: Optional[Callable] = None):
    import pyzipper
    pwd_bytes = password.encode() if password else None
    loop = asyncio.get_event_loop()
    def _do():
        with pyzipper.AESZipFile(archive_path) as z:
            z.extractall(out_dir, pwd=pwd_bytes)
    await loop.run_in_executor(None, _do)


async def _extract_rar_async(archive_path: Path, out_dir: Path, password: Optional[str],
                             on_pct: Optional[Callable[[int], Awaitable[None]]],
                             register_proc: Optional[Callable] = None):
    import rarfile
    loop = asyncio.get_event_loop()
    def _do():
        with rarfile.RarFile(archive_path) as r:
            if password:
                r.setpassword(password)
            r.extractall(out_dir)
    await loop.run_in_executor(None, _do)


def _detect_tar_mode(name: str) -> Optional[str]:
    """从文件名后缀判断 tar 解压 mode；返回 None 表示不是 tar。"""
    n = name.lower()
    if n.endswith('.tar'):                                  return 'r:'
    if n.endswith('.tar.gz') or n.endswith('.tgz'):         return 'r:gz'
    if n.endswith('.tar.bz2') or n.endswith('.tbz2'):       return 'r:bz2'
    if n.endswith('.tar.xz') or n.endswith('.txz'):         return 'r:xz'
    return None


async def _extract_tar_async(archive_path: Path, out_dir: Path, password: Optional[str],
                             on_pct: Optional[Callable[[int], Awaitable[None]]],
                             register_proc: Optional[Callable] = None):
    """tarfile 标准库；不支持加密（password 参数忽略）。"""
    import tarfile
    mode = _detect_tar_mode(archive_path.name)
    if mode is None:
        # extract() 已经按后缀路由到这里，理论不会发生；防御性 raise
        raise RuntimeError(f"无法识别 tar 类型：{archive_path.name}")
    loop = asyncio.get_event_loop()
    def _do():
        with tarfile.open(archive_path, mode=mode) as tf:
            # filter='data'（PEP 706）拒绝 ../ 路径穿越、绝对路径、设备文件等；
            # tar 里的文件名同样来自发送方，不可信。Python < 3.12 无此参数则退化。
            try:
                tf.extractall(out_dir, filter='data')
            except TypeError:
                tf.extractall(out_dir)
    await loop.run_in_executor(None, _do)


# ── 异步密码尝试 ────────────────────────────────────────────────────────────

async def _try_passwords(fn, archive_path: Path, out_dir: Path,
                         passwords: list[str],
                         on_attempt: Optional[Callable[[Optional[str]], Awaitable[None]]] = None,
                         on_pct: Optional[Callable[[int], Awaitable[None]]] = None,
                         register_proc: Optional[Callable] = None,
                         ) -> Optional[str]:
    # Always try no-password first to avoid false positives on unencrypted files.
    trials: list[Optional[str]] = [None] + [p for p in passwords if p is not None]
    last_exc: Exception = RuntimeError("未知错误")
    for pwd in trials:
        if on_attempt:
            await on_attempt(pwd)
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            await fn(archive_path, out_dir, pwd, on_pct, register_proc)
            return pwd
        except OSError:
            raise  # disk-full etc — propagate immediately, no point retrying passwords
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"所有密码均失败（{archive_path.name}）: {last_exc}") from last_exc


# ── public API ─────────────────────────────────────────────────────────────────

async def extract(archive_path: Path,
                  output_base: Optional[Path] = None,
                  passwords: Optional[list[str]] = None,
                  on_attempt: Optional[Callable[[Optional[str]], Awaitable[None]]] = None,
                  on_pct: Optional[Callable[[int], Awaitable[None]]] = None,
                  register_proc: Optional[Callable] = None,
                  explicit_out_dir: Optional[Path] = None,
                  ) -> tuple[Path, Optional[str]]:
    """
    Extract archive_path.

    on_pct: 解压进度回调（0-100），仅 7z 命令路径会触发。
            zip/rar/py7zr 路径不会触发（传 -1 表示未知，由 manager 层负责）。
    register_proc(proc | None): 暴露 7z 子进程 handle 给外层（P2-4 取消）；
            非 7z 路径不调用。

    Returns (out_dir, used_password_or_None).
    Raises ExtractError on failure (with .reason = short classification string).
    """
    if output_base is None:
        output_base = config.OUTPUT_PATH or archive_path.parent
    if passwords is None:
        passwords = config.PASSWORDS

    out_dir     = explicit_out_dir if explicit_out_dir is not None else (output_base / archive_stem(archive_path))
    content_dir = out_dir / "解压内容"
    out_dir.mkdir(parents=True, exist_ok=True)

    name   = archive_path.name.lower()
    suffix = archive_path.suffix.lower()

    # 多卷缺口预检：缺卷直接报"卷缺失（缺第N卷）"，不去逐个试密码
    # （否则每次尝试都因缺卷失败 → 被误报成"密码错误"）
    if name.endswith('.7z.001'):
        missing = find_missing_volume(archive_path)
        if missing is not None:
            raise ExtractError(
                f"多卷不完整：缺第 {missing} 卷（{archive_path.name} 系列）", "卷缺失")

    try:
        if name.endswith('.7z.001') or suffix == '.7z':
            used_pwd = await _try_passwords(_extract_7z_async, archive_path, content_dir, passwords, on_attempt, on_pct, register_proc)
        elif suffix == '.zip':
            used_pwd = await _try_passwords(_extract_zip_async, archive_path, content_dir, passwords, on_attempt, on_pct, register_proc)
        elif suffix == '.rar':
            used_pwd = await _try_passwords(_extract_rar_async, archive_path, content_dir, passwords, on_attempt, on_pct, register_proc)
        elif _detect_tar_mode(name) is not None:
            # tar 系列不支持加密，直接调用，无需密码重试
            if on_attempt:
                await on_attempt(None)
            content_dir.mkdir(parents=True, exist_ok=True)
            await _extract_tar_async(archive_path, content_dir, None, on_pct, register_proc)
            used_pwd = None
        else:
            raise ValueError(f"不支持的格式: {archive_path.suffix}")
    except Exception as exc:
        # Clean up empty content_dir left by last failed attempt
        try:
            if content_dir.exists() and not any(content_dir.iterdir()):
                content_dir.rmdir()
        except OSError:
            pass
        from unzipper.utils import classify_error
        raise ExtractError(str(exc), classify_error(exc)) from exc

    # Move archive file(s) into out_dir (task root)
    if archive_path.name.lower().endswith('.7z.001'):
        for part in find_multipart_parts(archive_path):
            shutil.move(str(part), str(out_dir / part.name))
    else:
        shutil.move(str(archive_path), str(out_dir / archive_path.name))

    pwd_file = out_dir / "password.txt"
    if used_pwd:
        pwd_file.write_text(f"解压密码：{used_pwd}\n", encoding="utf-8")
    else:
        pwd_file.write_text("此压缩包没有密码\n", encoding="utf-8")

    return out_dir, used_pwd
