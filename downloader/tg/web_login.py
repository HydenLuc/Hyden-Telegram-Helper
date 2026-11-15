# SPDX-License-Identifier: AGPL-3.0-or-later
"""没有终端时的网页登录流程（2026-11-13）。

为什么不直接用 Telethon 的 client.start(code_callback=...)：
1. 它不告诉你验证码**发到了哪里**。Telegram 不一定发到 App：可能是短信、邮箱、电话，
   新号还可能要求先绑定登录邮箱。用户只能瞎找。
2. 它把「验证码不对」和「验证码过期」合成同一句 `Invalid code`，用户分不清该重输还是重发。
3. 没有「重新发送」。重启程序会重新申请登录，但 Telegram 常常**不再发新消息**，
   旧码又对不上新的申请 → 永远登不上。
   2026-11-13 开发环境测试号登录就卡在这里：只收到前一晚的一条码，重启两次都没新码，
   填进去一直 `Invalid code`。

还提供**扫码登录**（同一天加）：上面那次 Telegram 回复「已发到 App」，App 里却一条都没有，
验证码这条路彻底走不通。扫码不需要验证码：手机 Telegram → 设置 → 设备 → 扫描二维码。

终端模式（前台运行）仍用 client.start，那边 Telethon 会直接在终端里提示。
"""
import asyncio
import logging

from telethon import errors
from telethon.tl import types

from downloader import state

_log = logging.getLogger("downloader")

# 扫码登录成功 / 扫完要两步验证密码时，扫码任务用这两个暗号把主流程叫醒
_QR_OK  = "\x00qr-ok"
_QR_2FA = "\x00qr-2fa"
_qr_task: asyncio.Task | None = None

# 验证码送达方式 → 给人看的说明
_SENT_TYPES = {
    "SentCodeTypeApp":        "Telegram App：这个号已经登录的手机 / 电脑上，「Telegram」官方对话（带蓝色认证标）里",
    "SentCodeTypeSms":        "手机短信",
    "SentCodeTypeFirebaseSms": "手机短信",
    "SentCodeTypeSmsWord":    "手机短信（验证码是一个单词）",
    "SentCodeTypeSmsPhrase":  "手机短信（验证码是一句短语）",
    "SentCodeTypeCall":       "电话语音（会有电话打进来念验证码）",
    "SentCodeTypeFlashCall":  "未接来电（来电号码的末几位就是验证码）",
    "SentCodeTypeMissedCall": "未接来电（来电号码的末几位就是验证码）",
    "SentCodeTypeFragmentSms": "Fragment 匿名号码",
}
_NEXT_TYPES = {
    "CodeTypeSms":         "短信",
    "CodeTypeCall":        "电话语音",
    "CodeTypeFlashCall":   "未接来电",
    "CodeTypeMissedCall":  "未接来电",
    "CodeTypeFragmentSms": "Fragment 短信",
}


def describe_sent_code(sent) -> dict:
    """把 Telegram 返回的 SentCode 翻成页面上能看懂的话。"""
    t = sent.type
    name = type(t).__name__
    where = _SENT_TYPES.get(name, name)
    if isinstance(t, types.auth.SentCodeTypeEmailCode):
        where = f"登录邮箱 {t.email_pattern}"
    elif isinstance(t, types.auth.SentCodeTypeSetUpEmailRequired):
        where = ("Telegram 要求这个号先绑定一个登录邮箱才能在新设备登录。"
                 "请在已登录这个号的手机 App 里：设置 → 隐私与安全 → 登录邮箱，设好后点「重新发送」")
    elif isinstance(t, types.auth.SentCodeTypeFragmentSms):
        where = f"Fragment 匿名号码（到 {t.url} 查看）"
    nxt = getattr(sent, "next_type", None)
    return {
        "type":   name,
        "where":  where,
        "length": getattr(t, "length", None),
        # 点「重新发送」时 Telegram 会改用的方式；None = 只能原方式再发
        "next":   _NEXT_TYPES.get(type(nxt).__name__) if nxt else None,
        "timeout": getattr(sent, "timeout", None),
        "error":  "",
    }


async def _wait_input(step: str) -> str:
    from downloader.tg.handlers import _broadcast   # 延迟导入：handlers import 了 client
    state._auth_step = step
    state._auth_future = asyncio.get_running_loop().create_future()
    await _broadcast()
    try:
        return await state._auth_future
    finally:
        state._auth_future = None


async def _set_error(msg: str) -> None:
    from downloader.tg.handlers import _broadcast
    state._auth_info["error"] = msg
    _log.warning(f"[登录] {msg}")
    await _broadcast()


async def send_code(client, phone: str) -> None:
    """申请（或重发）验证码，并把「发到哪里」写进 state 给网页显示。

    Telethon 的 send_code_request：本进程第一次调 = 新申请；之后再调 = ResendCodeRequest
    （按 next_type 换一种方式发），旧码过期时它会自己改成新申请。
    """
    from downloader.tg.handlers import _broadcast
    sent = await client.send_code_request(phone)
    state._auth_info = describe_sent_code(sent)
    _log.info(f"[登录] 验证码已发出 → {state._auth_info['where']}"
              f"（{state._auth_info['type']}；重发会改用：{state._auth_info['next'] or '原方式'}）")
    await _broadcast()


async def resend_code(client, phone: str) -> dict:
    """网页「重新发送」按钮调这里。"""
    try:
        await send_code(client, phone)
    except errors.FloodWaitError as e:
        await _set_error(f"Telegram 限制了发送频率，请 {max(1, e.seconds // 60)} 分钟后再点重新发送")
    except errors.RPCError as e:
        await _set_error(f"重新发送失败：{e.__class__.__name__}")
    return state._auth_info


def _qr_data_uri(url: str) -> str:
    import segno
    return segno.make(url, error="m").svg_data_uri(scale=5, border=2, dark="#000", light="#fff")


def _wake_main(value: str) -> None:
    if state._auth_future is not None and not state._auth_future.done():
        state._auth_future.set_result(value)


async def _qr_loop(client) -> None:
    """一直出二维码直到扫码成功；二维码约 30 秒过期，过期自动换新的。"""
    from downloader.tg.handlers import _broadcast
    while state._auth_step == "waiting_code":
        qr = await client.qr_login()
        state._auth_info["qr"] = _qr_data_uri(qr.url)
        state._auth_info["error"] = ""
        await _broadcast()
        try:
            await qr.wait()
        except asyncio.TimeoutError:
            continue                     # 过期 → 换一张
        except errors.SessionPasswordNeededError:
            _log.info("[登录] 扫码成功，这个号开了两步验证，等网页输密码")
            _wake_main(_QR_2FA)
            return
        _log.info("[登录] 扫码登录成功")
        _wake_main(_QR_OK)
        return


async def start_qr(client) -> dict:
    """网页「改用扫码登录」按钮调这里。只会有一个扫码任务在跑。"""
    global _qr_task
    if state._auth_step != "waiting_code":
        return {"ok": False, "error": "现在没有在等登录"}
    if _qr_task is None or _qr_task.done():
        async def run():
            try:
                await _qr_loop(client)
            except Exception as e:      # 别让扫码出错把整个登录流程带崩，用户还能用验证码
                _log.exception("[登录] 扫码登录出错")
                await _set_error(f"扫码登录出错：{e.__class__.__name__}，可以再点一次或改用验证码")
                state._auth_info.pop("qr", None)
        _qr_task = asyncio.create_task(run())
    return {"ok": True}


async def _password_loop(client) -> None:
    state._auth_info["error"] = ""
    while True:
        pwd = await _wait_input("waiting_password")
        try:
            await client.sign_in(password=pwd)
            return
        except errors.PasswordHashInvalidError:
            await _set_error("两步验证密码不对，请重输")
        except errors.FloodWaitError as e:
            await _set_error(f"输错太多次，Telegram 要求等 {max(1, e.seconds // 60)} 分钟再试")


async def web_login(client, phone: str) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return
    _log.info("[登录] 这个号还没登录，开始网页登录（打开下载器页面按提示填写）")
    try:
        await send_code(client, phone)
    except errors.FloodWaitError as e:
        state._auth_info = {"where": "（还没发出）", "next": None, "error": "", "type": "", "length": None}
        await _set_error(f"Telegram 限制了发送频率，{max(1, e.seconds // 60)} 分钟后自动重试")
        await asyncio.sleep(e.seconds + 5)
        await send_code(client, phone)

    try:
        while True:
            raw = await _wait_input("waiting_code")
            if raw == _QR_OK:
                break
            if raw == _QR_2FA:
                await _password_loop(client)
                break
            code = raw.replace(" ", "").replace("-", "")
            try:
                await client.sign_in(phone=phone, code=code)
                break
            except errors.PhoneCodeInvalidError:
                await _set_error("验证码不对。请核对是不是最新的那一条（看上面写的发送位置）")
            except errors.PhoneCodeExpiredError:
                await _set_error("这条验证码已过期，正在重新发送…")
                await resend_code(client, phone)
                if not state._auth_info.get("error"):
                    state._auth_info["error"] = "旧验证码已过期，已重新发送，请看上面写的位置"
            except errors.FloodWaitError as e:
                await _set_error(f"输错太多次，Telegram 要求等 {max(1, e.seconds // 60)} 分钟再试")
            except errors.SessionPasswordNeededError:
                await _password_loop(client)
                break
    finally:
        from downloader.tg.handlers import _broadcast
        if _qr_task is not None and not _qr_task.done():
            _qr_task.cancel()
        state._auth_step = "idle"
        state._auth_info = {}
        await _broadcast()
    _log.info("[登录] 网页登录成功")
