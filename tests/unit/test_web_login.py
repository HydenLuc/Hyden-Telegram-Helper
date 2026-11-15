# SPDX-License-Identifier: AGPL-3.0-or-later
"""网页登录流程（2026-11-13）。

起因：开发环境测试号登录卡死——Telegram 没在 App 里发新码，页面也不说发到了哪；
Telethon 把「不对」和「过期」都报成 `Invalid code`；没有重发按钮。
"""
import asyncio

import pytest
from telethon import errors
from telethon.tl import types

from downloader import state
from downloader.tg import web_login as wl


def _sent(t, next_type=None):
    return types.auth.SentCode(type=t, phone_code_hash="h", next_type=next_type)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    async def nop():
        pass
    import downloader.tg.handlers as h
    monkeypatch.setattr(h, "_broadcast", nop)
    state._auth_step, state._auth_future, state._auth_info = "idle", None, {}
    yield
    state._auth_step, state._auth_future, state._auth_info = "idle", None, {}


class FakeClient:
    def __init__(self, sign_in_results, sent=None):
        self.results = list(sign_in_results)   # 每次 sign_in 依次：None=成功，异常=抛出
        self.sent = sent or _sent(types.auth.SentCodeTypeApp(length=5), types.auth.CodeTypeSms())
        self.send_calls = 0
        self.sign_in_calls = []

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return False

    async def send_code_request(self, phone):
        self.send_calls += 1
        return self.sent

    async def sign_in(self, phone=None, code=None, password=None):
        self.sign_in_calls.append(code or password)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r


async def _feed(values, seen):
    """像用户一样：每当页面在等输入，就交一个值；顺便记下当时页面显示的提示。"""
    for v in values:
        for _ in range(300):
            if state._auth_future is not None and not state._auth_future.done():
                break
            await asyncio.sleep(0.005)
        seen.append((state._auth_step, dict(state._auth_info)))
        state._auth_future.set_result(v)
        await asyncio.sleep(0.01)


async def _run(client, inputs):
    seen = []
    feeder = asyncio.create_task(_feed(inputs, seen))
    await asyncio.wait_for(wl.web_login(client, "+10000000000"), 3)
    await feeder
    return seen


def test_说清验证码发到了哪里():
    app = wl.describe_sent_code(_sent(types.auth.SentCodeTypeApp(length=5), types.auth.CodeTypeSms()))
    assert "Telegram App" in app["where"] and app["length"] == 5 and app["next"] == "短信"
    sms = wl.describe_sent_code(_sent(types.auth.SentCodeTypeSms(length=5)))
    assert sms["where"] == "手机短信" and sms["next"] is None
    mail = wl.describe_sent_code(_sent(types.auth.SentCodeTypeEmailCode(email_pattern="a***@x.com", length=6)))
    assert "a***@x.com" in mail["where"]
    need = wl.describe_sent_code(_sent(types.auth.SentCodeTypeSetUpEmailRequired()))
    assert "登录邮箱" in need["where"]


async def test_一次成功():
    c = FakeClient([None])
    seen = await _run(c, ["12345"])
    assert c.sign_in_calls == ["12345"]
    assert seen[0][0] == "waiting_code" and "Telegram App" in seen[0][1]["where"]
    assert state._auth_step == "idle" and state._auth_info == {}


async def test_验证码不对_提示后可以重输():
    c = FakeClient([errors.PhoneCodeInvalidError(request=None), None])
    seen = await _run(c, ["11111", "22222"])
    assert c.sign_in_calls == ["11111", "22222"]
    assert "不对" in seen[1][1]["error"]


async def test_验证码过期_自动重发并说明():
    c = FakeClient([errors.PhoneCodeExpiredError(request=None), None])
    seen = await _run(c, ["11111", "33333"])
    assert c.send_calls == 2           # 第一次申请 + 过期后重发
    assert "过期" in seen[1][1]["error"]


async def test_两步验证密码_错了能重输():
    c = FakeClient([errors.SessionPasswordNeededError(request=None),
                    errors.PasswordHashInvalidError(request=None), None])
    seen = await _run(c, ["12345", "wrong", "right"])
    assert [s[0] for s in seen] == ["waiting_code", "waiting_password", "waiting_password"]
    assert "密码不对" in seen[2][1]["error"]
    assert c.sign_in_calls == ["12345", "wrong", "right"]


async def test_输入里的空格和横线去掉():
    c = FakeClient([None])
    await _run(c, ["12 3-45"])
    assert c.sign_in_calls == ["12345"]


async def test_重发按钮_限流时给出等待时间():
    class Limited(FakeClient):
        async def send_code_request(self, phone):
            raise errors.FloodWaitError(request=None, capture=600)
    state._auth_info = {"where": "x", "error": ""}
    info = await wl.resend_code(Limited([]), "+10000000000")
    assert "10 分钟" in info["error"]


async def test_已经登录过就不再要验证码():
    class Authed(FakeClient):
        async def is_user_authorized(self):
            return True
    c = Authed([])
    await wl.web_login(c, "+1")
    assert c.send_calls == 0


class _FakeQR:
    def __init__(self, outcome):
        self.url = "tg://login?token=abc"
        self.outcome = outcome            # None=扫码成功 / 异常=抛出

    async def wait(self, timeout=None):
        await asyncio.sleep(0.01)
        if isinstance(self.outcome, BaseException):
            raise self.outcome


class QRClient(FakeClient):
    def __init__(self, qr_outcomes, sign_in_results=()):
        super().__init__(sign_in_results)
        self.qr_outcomes = list(qr_outcomes)
        self.qr_made = 0

    async def qr_login(self):
        self.qr_made += 1
        return _FakeQR(self.qr_outcomes.pop(0))


async def _login_by_qr(client, then_inputs=()):
    """等页面出现验证码框 → 点「改用扫码登录」→（需要的话）再输密码。"""
    seen = []
    task = asyncio.create_task(wl.web_login(client, "+10000000000"))
    for _ in range(300):
        if state._auth_step == "waiting_code" and state._auth_future is not None:
            break
        await asyncio.sleep(0.005)
    assert (await wl.start_qr(client))["ok"]
    for _ in range(300):
        if state._auth_info.get("qr"):
            break
        await asyncio.sleep(0.005)
    seen.append(dict(state._auth_info))
    if then_inputs:                        # 要输密码：等扫码结果回来、密码框真的弹出再填
        for _ in range(300):
            if state._auth_step == "waiting_password":
                break
            await asyncio.sleep(0.005)
    await _feed(then_inputs, seen)
    await asyncio.wait_for(task, 3)
    return seen


async def test_扫码登录_过期自动换码_扫完就登录():
    c = QRClient([asyncio.TimeoutError(), None])
    seen = await _login_by_qr(c)
    assert seen[0]["qr"].startswith("data:image/svg+xml")
    assert c.qr_made == 2                  # 第一张过期，换了一张
    assert c.sign_in_calls == []           # 全程没用验证码
    assert state._auth_step == "idle"


async def test_扫码后要两步验证_接着输密码():
    c = QRClient([errors.SessionPasswordNeededError(request=None)], [None])
    seen = await _login_by_qr(c, ["mypwd"])
    assert seen[1][0] == "waiting_password"
    assert c.sign_in_calls == ["mypwd"]


async def test_扫码出错不影响继续用验证码():
    c = QRClient([RuntimeError("boom")], [None])
    task = asyncio.create_task(wl.web_login(c, "+1"))
    for _ in range(300):
        if state._auth_future is not None:
            break
        await asyncio.sleep(0.005)
    await wl.start_qr(c)
    for _ in range(300):
        if "扫码登录出错" in state._auth_info.get("error", ""):
            break
        await asyncio.sleep(0.005)
    assert "扫码登录出错" in state._auth_info["error"]
    state._auth_future.set_result("12345")
    await asyncio.wait_for(task, 3)
    assert c.sign_in_calls == ["12345"]
