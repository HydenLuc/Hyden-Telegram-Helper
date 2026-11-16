<p align="right"><b>English</b> | <a href="#中文">简体中文</a></p>

# Contributing

Thanks for your interest in Hyden TGhelper!

## Contributor License Agreement (CLA)

Hyden TGhelper is dual-licensed: it is published under AGPL-3.0-or-later, and HydenLuc also offers commercial licenses. To keep that possible, **every contributor must sign a Contributor License Agreement before a pull request can be merged**. The CLA lets HydenLuc license your contribution under other terms as well; you keep the copyright of your own work.

The full text is in [CLA.md](CLA.md). When you open your first pull request, a bot will ask you to sign by replying with one sentence. You only sign once; signatures are stored in this repository's `cla-signatures` branch.

## Before you open a pull request

- Run the tests: `pip install -r requirements.txt -r requirements-dev.txt && python -m pytest -q -m "not e2e"`
- Never commit credentials: `.env`, `*.session`, `passwords.json`, API keys.
- Security problems: don't open a public issue — see [SECURITY.md](SECURITY.md).
- Keep changes focused; describe *why* in the PR.

---

<a id="中文"></a>

# 参与贡献

感谢你对 Hyden TGhelper 的关注！

## 贡献者协议（CLA）

Hyden TGhelper 采用双授权：公开版按 AGPL-3.0-or-later 发布，HydenLuc 同时提供商业授权。为此，**每位贡献者在 PR 合并前都要签署贡献者协议**。协议允许 HydenLuc 以其他条款授权你贡献的代码；你自己代码的版权仍归你。

协议全文见 [CLA.md](CLA.md)。第一次提 PR 时机器人会提示你签署：在 PR 下原样回复它给的那句话即可，只需签一次；签名记录在本仓库的 `cla-signatures` 分支。

## 提 PR 之前

- 跑测试：`pip install -r requirements.txt -r requirements-dev.txt && python -m pytest -q -m "not e2e"`
- 绝不提交凭证：`.env`、`*.session`、`passwords.json`、API key。
- 安全问题不要发公开 Issue，见 [SECURITY.md](SECURITY.md)。
- 改动集中在一件事上，PR 里说清楚「为什么」。
