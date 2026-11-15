# 浮动回顶按钮设计

> **状态**：✅ 已实现

## 目标

四个模块（dashboard / downloader / mover / unzipper）页面右下角各加一个固定位置的「回顶」按钮，始终显示。

## UI 规格

- **位置**：`position: fixed; bottom: 24px; right: 24px; z-index: 999`
- **形状**：直径 44px 圆形（手指点击友好）
- **图标**：`↑`（Unicode `↑`），字号 1.4rem，居中
- **背景/文字**：`background: #1f1f1f; color: #888; border: 1px solid #333`
- **悬浮态**：`hover` 时 `color: #4fc3f7; border-color: #4fc3f7`
- **点击**：`window.scrollTo({ top: 0, behavior: 'smooth' })`
- **始终显示**：不依赖滚动位置，无淡入淡出

## 不冲突保证

各模块当前页面右下角无其他 fixed 元素：
- downloader：`auth-mask` 是覆盖全屏的 modal，`z-index` 高于回顶按钮但 modal 平时隐藏（`display:none`），不冲突
- mover / unzipper / dashboard：未发现 bottom-right 固定元素

如未来要加吐司提示（toast）等，需高于 `z-index: 999`。

## 实现要点

每个模块独立加一段 HTML + CSS，**不抽公共组件**（4 份模板独立管理）。

### 1. `downloader/web/templates.py`
- HTML：在 `<body>` 末尾、`<script>` 之前插入 `<button id="scroll-top-btn" title="回到顶部">↑</button>`
- CSS：在 `<style>` 末尾追加 `.scroll-top { ... }` 一组规则
- JS：在脚本顶部加 `document.getElementById('scroll-top-btn').addEventListener('click', () => window.scrollTo({top:0,behavior:'smooth'}))`

### 2. `mover/web/templates.py`
同上，结构对称。

### 3. `unzipper/web/templates.py`
同上。

### 4. `dashboard/templates.py`
同上。

## 验收

- 4 个模块页面打开后右下角始终可见 ↑ 按钮
- 滚动到底部后点击按钮平滑回顶
- 浏览器宽度缩到 ~360px（手机模拟）按钮不超出视口
- 与现有 modal、横幅（disk-space-design.md 引入）不重叠
