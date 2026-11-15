# 文档总目录

> 本目录索引整个 `docs/` 下的全部文档。各 `*-design.md` 是历史决策记录，**保留不删**；状态见每份文档头部的 `> **状态**：...` 行。

## 运行手册

| 文档 | 简介 |
|------|------|
| [deployment.md](deployment.md) | 进阶部署：系统要求、Docker / 原生细节、局域网访问、升级、备份、FAQ、公网安全清单 |
| [config.md](config.md) | `.env` 配置项与运行时可变配置 |
| [integration.md](integration.md) | 三模块流水线集成与原子搬运契约 |

## 架构

| 文档 | 简介 |
|------|------|
| [architecture.md](architecture.md) | 模块树、依赖图、数据流、并发模型、状态机 |

## API 参考

| 文档 | 简介 |
|------|------|
| [api.md](api.md) | 三模块 + dashboard 全部 HTTP / WebSocket 端点（结构化） |

## 已实现功能的设计文档

按"消息处理 / 下载 / 解压 / 配置与 UI"分组。每份头部有 `> **状态**：✅ 已实现` 一行。

### 消息处理 / 监听

| 文档 | 简介 |
|------|------|
| [pause-design.md](pause-design.md) | 三模块统一软暂停（P1-5a Q4） |
| [startup-pause-design.md](startup-pause-design.md) | 启动时默认暂停监听（F5） |
| [exempt-channel-design.md](exempt-channel-design.md) | 全局暂停下对单频道开启监听 |
| [watch-list-design.md](watch-list-design.md) | 监听列表统计、排序、折叠（P1-7） |
| [watch-search-design.md](watch-search-design.md) | 监听列表实时搜索 |
| [duplicate-download-design.md](duplicate-download-design.md) | 重复下载确认队列（F6） |

### 下载

| 文档 | 简介 |
|------|------|
| [history-pull-design.md](history-pull-design.md) | 频道历史媒体批量下载（4 场景） |
| [md5-dedup-design.md](md5-dedup-design.md) | MD5 内容去重 + fuid 预检 + toast 通知 |
| [pagination-design.md](pagination-design.md) | 历史分页 + 排序 + 8 状态解压追踪（P1-8） |
| [queue-pagination-design.md](queue-pagination-design.md) | 下载队列分页（下载中/排队中分离） |
| [completed-actions-design.md](completed-actions-design.md) | 4A 清空 done + 4B 移动整组文件夹 |
| [path-config-design.md](path-config-design.md) | 输出路径管理（三模块联动） |

### 解压 / 搬运

| 文档 | 简介 |
|------|------|
| [mover-ui-design.md](mover-ui-design.md) | mover 前端 UI（P1-9） |
| [password-ui-design.md](password-ui-design.md) | 解压密码管理 UI |

### 显示与监控

| 文档 | 简介 |
|------|------|
| [disk-space-design.md](disk-space-design.md) | 磁盘空间显示 + Telegram 阈值告警 |
| [scroll-top-design.md](scroll-top-design.md) | 4 模块浮动回顶按钮 |

## 阅读顺序（新接手时）

1. **运行起来**：[根目录 README](../README.zh-CN.md) → [deployment.md](deployment.md) → [config.md](config.md)
2. **理解架构**：[architecture.md](architecture.md) → [integration.md](integration.md)
3. **了解 API**：[api.md](api.md)
4. **历史决策**：各 `*-design.md`（按主题）
