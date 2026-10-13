# DESIGN.md — AI 自动化平台 HTML 原型（prototype-v1）

> **作用域**：本文档仅约束 `docs/prototypes/prototype-v1.html`——产品文档配套的**静态原型稿**，用于走查产品决策（信任字段 v2、两族交互、认证报告、画布副作用规则、复合积木、C1 抽查）。非生产实现，不引入构建链。

## 0. 研究日志（greenfield 豁免记录）

- Layer A：taste-skill（操作型工具 UI，无表面野心）——按其"可用优先"纪律执行；
- Layer B / lazyweb / imagen 概念稿 / StyleGallery：**跳过**——静态原型稿，无生产表面野心，网络研究对本文档不成比例（接受债务 D-1）；
- 原型保真目标 = **对文档决策的还原度**（PRD §1.2 信任字段逐字段、§8.5 认证报告格式、两族控件、画布副作用标识），非视觉独创性。

## 1. 令牌

| 令牌 | 值 | 用途 |
|---|---|---|
| --ink | #0f172a | 主文字 |
| --ink-2 | #475569 | 次文字 |
| --ink-3 | #8896a6 | 弱文字/占位 |
| --line | #e2e8f0 | 边框/分隔 |
| --bg | #f1f5f9 | 画布底 |
| --surface | #ffffff | 卡面 |
| --primary | #2f55f5 | 主操作/链接 |
| --primary-wash | #eef2ff | 主色弱底（选中态用底色洗，不用彩边） |
| --ok / --ok-bg | #067647 / #ecfdf3 | 成功/C2 认证 |
| --warn / --warn-bg | #b54708 / #fffaeb | best-effort 警示/脆弱步骤 |
| --danger / --danger-bg | #b42318 / #fef3f2 | 副作用/拦截 |
| --cert-c1 / bg | #175cd3 / #eff8ff | C1 认证徽章 |
| --mono | ui-monospace | 代码/报告数字 |

## 2. 字体与排版

- 族：`-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`；
- 级：12 / 13 / 14（基准）/ 16 / 20 / 24；行高 1.55；数字与代码用 mono。

## 3. 空间与形状

4px 网格；卡片 radius 12、控件 8；阴影仅两档（`0 1px 2px rgba(15,23,42,.06)` / 弹层 `0 8px 24px rgba(15,23,42,.12)`）。

## 4. 组件解剖（原型内实现为 class 原语）

- `badge`（认证等级/状态）：底色洗 + 深色字，无描边；
- `banner-warn`：best-effort 首屏警示（琥珀底，含图标与说明）；
- `node`（画布积木节点）：标题 + 认证徽章 + 副作用角标（红底圆点+文字）；副作用节点带 danger 洗底；
- `composite-frame`：复合积木虚线框 + 角标签"我的模块"；
- `stepper`：发布向导步骤条；
- 选中态：**底色洗 + ✓ 字形**（禁止彩色侧边条）；focus-visible 允许主色描边环。

## 5. 图标

内联 SVG 线性图标（stroke 1.5，24 网格，自绘简单几何）——不用 emoji。

## 6. 动效

仅导航切换（display 切换，无动画）与 hover 底色变化（background-color 过渡 ≤120ms）。静态原型无滚动叙事/氛围需求。

## 7. 无障碍约束

- 对比度：正文 ≥4.5:1（ink/surface ≈ 15:1，ink-2/surface ≈ 7:1，徽章深字/浅底均 ≥4.5:1）；
- 导航用真实 button + aria-current；图标带 aria-label。

## 8. 接受债务

- D-1：跳过绿色地研究车道（lazyweb/imagen/StyleGallery）——静态原型、保真目标为文档还原；
- D-2：未跑 /visual-qa 双预言机门——原型稿以人工走查 + 令牌合规自查替代；转生产实现时必须补全（含 react 工具链与 Lighthouse 门）；
- D-3：响应式仅桌面（≥1200px）——原型走查场景为桌面客户端。
