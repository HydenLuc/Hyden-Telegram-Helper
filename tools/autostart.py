# SPDX-License-Identifier: AGPL-3.0-or-later
"""开机自动启动（2026-11-13，hyden 要求：断电来电 / 重开机后程序自己起来）。

    python -m tools.autostart status | on | off

  · Docker 部署：不归这里管。容器 `restart: unless-stopped` + Docker 开机自启就够了
    （Docker Desktop 要在它的设置里勾「登录时启动」）。
  · macOS 原生：~/Library/LaunchAgents/<label>.plist，**登录后**跑 `start.sh --boot`。
    要「来电自己开机、不用人登录」：系统设置里打开自动登录 + 「停电后自动启动」。
  · Linux 原生：systemd 用户服务 ~/.config/systemd/user/<name>.service。
    要「开机不登录也启动」需要一次 `sudo loginctl enable-linger <用户>`（status 会提示）。
  · Windows 原生：不支持（Windows 请用 Docker Desktop，见 README）。

label / 服务名带上项目目录名（例如 tghelper-dev），同一台机器上装好几份互不干扰。
开关**只写 / 删配置文件，不会立刻启动或停止程序**：程序已经在跑的话，立刻 bootstrap
会让 start.sh 报「已在运行」，没意义。
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SLUG = re.sub(r"[^A-Za-z0-9.-]+", "-", ROOT.name).strip("-") or "tghelper"
MAC_LABEL = f"com.tghelper.{_SLUG}"
LINUX_UNIT = f"tghelper-{_SLUG}.service"


def _is_docker() -> bool:
    import config        # 跟其他模块用同一个判定
    return config.IS_DOCKER


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def _linux_unit() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / LINUX_UNIT


def _mac_plist_text() -> str:
    from xml.sax.saxutils import escape as e
    root = e(str(ROOT))
    # PATH：launchd 默认只有 /usr/bin:/bin:/usr/sbin:/sbin，Homebrew 装的 7z / unrar 找不到
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{e(MAC_LABEL)}</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>{root}/start.sh</string><string>--boot</string></array>
  <key>WorkingDirectory</key><string>{root}</string>
  <key>RunAtLoad</key><true/>
  <!-- start.sh 把四个模块放到后台就退出；不加这个，launchd 会在它退出时把整组进程杀掉 -->
  <key>AbandonProcessGroup</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>{root}/logs/autostart.log</string>
  <key>StandardErrorPath</key><string>{root}/logs/autostart.log</string>
</dict>
</plist>
"""


def _linux_unit_text() -> str:
    return f"""[Unit]
Description=TGhelper ({ROOT.name}) 开机自启
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory={ROOT}
ExecStart=/bin/bash {ROOT}/start.sh --boot
ExecStop=/bin/bash {ROOT}/stop.sh

[Install]
WantedBy=default.target
"""


def _linger_on() -> bool | None:
    if not shutil.which("loginctl"):
        return None
    try:
        out = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
                             capture_output=True, text=True, timeout=5).stdout
        return "Linger=yes" in out
    except Exception:
        return None


def status() -> dict:
    """{supported, enabled, how, note}：给设置页和命令行看。"""
    if _is_docker():
        return {"supported": False, "enabled": True, "how": "docker",
                "note": "Docker 部署由 Docker 负责开机自启（容器 restart: unless-stopped；"
                        "Docker Desktop 要在它的设置里勾「登录时启动」）。这里不用设置。"}
    system = platform.system()
    if system == "Darwin":
        on = _mac_plist().exists()
        return {"supported": True, "enabled": on, "how": "launchd", "path": str(_mac_plist()),
                "note": "登录这台 Mac 后自动启动。要停电来电后不用人管：系统设置里打开「自动登录」，"
                        "节能里打开「停电后自动启动」。"}
    if system == "Linux":
        on = _linux_unit().exists()
        linger = _linger_on()
        note = "开机后自动启动。"
        if linger is False:
            note += f"⚠️ 现在要登录这个用户才会启动；要开机不登录也启动，执行一次：sudo loginctl enable-linger {os.environ.get('USER', '<用户名>')}"
        return {"supported": True, "enabled": on, "how": "systemd --user", "path": str(_linux_unit()),
                "linger": linger, "note": note}
    return {"supported": False, "enabled": False, "how": None,
            "note": "Windows 原生部署不支持开机自启，请用 Docker Desktop 部署（README 里有说明）。"}


def enable() -> dict:
    s = status()
    if not s["supported"]:
        return {"ok": False, **s}
    if s["how"] == "launchd":
        p = _mac_plist()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_mac_plist_text(), encoding="utf-8")
    else:
        p = _linux_unit()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_linux_unit_text(), encoding="utf-8")
        for cmd in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", LINUX_UNIT]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return {"ok": False, **status(), "error": f"{' '.join(cmd)} 失败：{r.stderr.strip()}"}
    return {"ok": True, **status()}


def disable() -> dict:
    s = status()
    if not s["supported"]:
        return {"ok": False, **s}
    if s["how"] == "launchd":
        # 已加载的话卸掉（只是不再管它，不会停掉正在跑的程序：start.sh 早就退出了）
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{MAC_LABEL}"],
                       capture_output=True, timeout=15)
        _mac_plist().unlink(missing_ok=True)
    else:
        subprocess.run(["systemctl", "--user", "disable", LINUX_UNIT], capture_output=True, timeout=15)
        _linux_unit().unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=15)
    return {"ok": True, **status()}


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    fn = {"status": lambda: {"ok": True, **status()}, "on": enable, "off": disable}.get(cmd)
    if fn is None:
        print(__doc__)
        return 2
    r = fn()
    state = "已开启" if r.get("enabled") else "未开启"
    print(f"开机自动启动：{state}（{r.get('how') or '—'}）")
    if r.get("path"):
        print(f"  配置文件：{r['path']}")
    print(f"  {r.get('note', '')}")
    if r.get("error"):
        print(f"  ✗ {r['error']}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
