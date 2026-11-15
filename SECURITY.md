# Security Policy / 安全问题报告

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report it privately through GitHub: open the repository's **Security** tab → **Report a vulnerability**
(GitHub private vulnerability reporting). Include what you found, how to reproduce it, and which version
or commit you tested. You will get a reply as soon as possible; please give us a reasonable time to fix
it before disclosing it publicly.

Things that are **not** vulnerabilities in this project:

- Telegram limiting or banning an account because of automation (see the Disclaimer in the README).
- Someone who already has your `.env` or `userbot.session` being able to use your account — those files
  are your account; keep them private.
- Exposing the services to a network **without** setting `API_KEY` (the program refuses to start like
  that unless you explicitly set `ALLOW_NO_API_KEY=1`).

## 报告安全漏洞

**请不要在公开的 Issue 里报告安全问题。**

在仓库的 **Security** 页 → **Report a vulnerability** 私下提交（GitHub 的私密漏洞报告）。
写清楚发现了什么、怎么复现、测的是哪个版本或 commit。我们会尽快回复；修好之前请先别公开。

以下**不算**本项目的漏洞：

- Telegram 因为自动化操作限制或封禁账号（见 README 的免责声明）。
- 拿到了你的 `.env` 或 `userbot.session` 的人能用你的账号——这两个文件就等于你的账号，请自己保管好。
- 没设 `API_KEY` 就把服务开放到网络上（这种情况程序默认拒绝启动，除非你显式设了 `ALLOW_NO_API_KEY=1`）。
