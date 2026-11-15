# SPDX-License-Identifier: AGPL-3.0-or-later
"""跨模块设置同步（fire-and-forget HTTP 调用）。"""
import aiohttp


async def post_settings(port: int, api_key: str, payload: dict, *,
                        host: str = "127.0.0.1", label: str = "peer_sync") -> bool:
    """向同机另一模块的 POST /api/settings 发送同步请求。

    失败仅打 warning log，不抛异常；返回 True/False。
    label 用于日志区分调用方向（如 'downloader→unzipper'）。
    """
    url = f"http://{host}:{port}/api/settings"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=3),
            headers={"X-API-Key": api_key},
        ) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    print(f"[{label}] 同步失败: {data.get('error')}")
                    return False
                print(f"[{label}] 已同步: {payload}")
                return True
    except Exception as e:
        print(f"[{label}] 同步异常: {e}")
        return False
