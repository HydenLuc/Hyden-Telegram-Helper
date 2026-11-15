# SPDX-License-Identifier: AGPL-3.0-or-later
"""`.partN` 保留策略（2026-09-17 回归）。

## 这组用例防的是什么

大文件（>2GB 走 6 分块）下到尾部时某个分块卡住 → 看门狗 60s 无进度 → 取消。
原来的取消分支**无条件 `_cleanup_parts`**，把已下的几个 GB 分块全删了，
于是下一次从 0 开始，下到尾部再卡、再删 —— **永动机**。

2026-09-17 实测后果：11 个任务（2.5~3.5 GB）这么循环了一个多月，
每轮烧 3.5 GB 带宽，一个都没完成；磁盘上**一个 .partN 都找不到**。
而整套续传机制（chunker 读 .partN 已有字节接着下）完全是好的，
只是永远没有 .partN 可读。

规则：**只有「确实要从零重来」才删**。超时、FloodWait 都不算。
"""
from pathlib import Path

from downloader.download import manager


# ── 规则本身 ────────────────────────────────────────────────────────────

def test_停滞超时必须保留分块():
    """核心用例：这就是那个永动机。"""
    assert manager._should_purge_parts("stall_timeout") is False


def test_floodwait_必须保留分块():
    """临时限流而已，为它丢几个 GB 进度毫无道理。"""
    assert manager._should_purge_parts("flood_wait") is False


def test_手动取消要删():
    assert manager._should_purge_parts("manual_cancel") is True


def test_续传失败回退要删():
    """反向用例：这一种是**该删**的，旧分块可能是坏的，别把它一起改掉。"""
    assert manager._should_purge_parts("resume_fallback") is True


def test_彻底放弃要删():
    assert manager._should_purge_parts("gave_up") is True


def test_未知原因保守保留():
    """新增结束原因时忘了登记，默认也不该丢进度。"""
    for r in ("", "something_new", "网络抖动", None):
        assert manager._should_purge_parts(r) is False, f"{r!r} 落到了删除那边"


def test_两张表不重叠():
    assert not (manager._PURGE_REASONS & manager._KEEP_REASONS)


# ── _cleanup_parts 的实际行为 ───────────────────────────────────────────

def test_cleanup_只删自己那几个分块(tmp_path):
    f = tmp_path / "video.mp4"
    for i in range(3):
        (tmp_path / f"video.mp4.part{i}").write_bytes(b"x")
    (tmp_path / "video.mp4.part9").write_bytes(b"x")      # 超出 n 的
    (tmp_path / "别的文件.mp4.part0").write_bytes(b"x")     # 别的任务的

    manager._cleanup_parts(f, 3)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["video.mp4.part9", "别的文件.mp4.part0"], \
        f"删多了或删少了：{left}"


def test_cleanup_对不存在的分块不报错(tmp_path):
    manager._cleanup_parts(tmp_path / "没下过.mp4", 6)      # 不该抛


# ── 超时阈值与 Telethon 内部重试的关系（2026-09-17）────────────────────
#
# Telethon 的 flood_sleep_threshold 以内的 FloodWait 由它自己 sleep 重试，
# 这期间**零进度**。如果停滞看门狗的阈值不明显大于它，看门狗必然先开枪。
# 两者以前都是 60 —— 这就是 363 次「超过 60s 无进度」的真正来源。

def test_停滞超时必须明显大于telethon内部重试上限():
    import config
    assert config.DOWNLOAD_TIMEOUT > config.FLOOD_SLEEP_THRESHOLD, (
        "DOWNLOAD_TIMEOUT(%s) 必须大于 FLOOD_SLEEP_THRESHOLD(%s)，"
        "否则 Telethon 还在正常等限流，看门狗就把下载杀了"
        % (config.DOWNLOAD_TIMEOUT, config.FLOOD_SLEEP_THRESHOLD)
    )
    assert config.DOWNLOAD_TIMEOUT >= config.FLOOD_SLEEP_THRESHOLD * 2, (
        "余量太小：Telethon 可能连续等好几次，至少留 2 倍"
    )


def test_客户端真的把阈值传进去了():
    """光在 config 里写没用，得真传给 TelegramClient。"""
    import inspect
    from downloader.tg import client as c
    src = inspect.getsource(c)
    assert "flood_sleep_threshold=config.FLOOD_SLEEP_THRESHOLD" in src, \
        "TelegramClient 没接上 FLOOD_SLEEP_THRESHOLD，config 改了也不生效"
