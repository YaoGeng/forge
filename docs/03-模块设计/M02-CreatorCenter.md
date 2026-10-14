# M02 Creator Center（组装工作台） 模块设计 v1.0

> **职责**：应用创作者的九步主流程宿主——搜积木、画布组装、复合积木（我的模块）打包与复用、演示录制参数化 UX、草稿入口、本机认证提交、发布向导；阶段 1 为平台内部最小版（无创作者开放）。
>
> **上游依据**：`01-产品文档.md` v14.2 §8；`02-技术架构.md` v8.2 §2.5、§5.1、§8.1。
>
> **状态**：起草（2026-10-14）。阶段 1 交付最小版（内部工具级 UI），阶段 3 开放创作者并承载"创作成功率 ≥60%" gate。


## 1. 职责与边界

| IN | OUT |
|---|---|
| 九步流程编排与状态管理（会话可恢复） | 积木检索算法/参数化 LLM（M08，本模块是 UX 宿主） |
| 画布（React Flow）：拖拽/连线/接口兼容性校验/副作用规则强制 | 录制采集与回放引擎（M07，本模块提供 UX 与标注交互） |
| 复合积木：选中打包/命名/我的模块库/复用连线/app-bound 发布流转 | 认证执行（M09，本模块是提交与报告展示入口） |
| 启动表单配置（user_input_schema，含生成草案编辑） | 审核/上架状态机（M10） |
| 草稿路径入口（说一句话 → M08 draft_codegen → C0 草稿库） | 信任字段计算（M03/M10，本模块填报与预览） |
| 本地干跑触发与脆弱步骤处置 UI | — |
| 发布向导：应用信息/信任字段预览/站点合规声明 | — |

**核心不变量**：
1. 画布不可保存违反副作用规则的流程（发布/提交/支付类无后置 confirm）；
2. 含 C0 积木的应用不能进入提审（提交入口直接拦截，非审核期拦截）；**含 C0 内层的复合积木不可打包、不可用于上架应用**（PRD §3.3，两处拦截：打包时 + 提审时）；
3. 非技术用户路径上不出现代码编辑器（Monaco 仅积木作者工作台，阶段 4+）；
4. 每一步的产物自动保存（会话崩溃可恢复到最近步骤）。


## 2. 组件分解

```text
M02 Creator Center
├── FlowOrchestrator     # 九步状态机 + 会话持久化（本地 blocks_lib/tasks）
├── BlockSearchPanel     # 需求输入 → M08 推荐；列表展示通过率（带 N/时间窗，不合成）
├── Canvas               # React Flow：节点=积木/复合积木；连线=接口兼容性校验；副作用标识与保存拦截
├── CompositePackager    # 选中子图 → 打包命名 → 我的模块库（本地）；含 C0 内层拒绝打包（PRD §3.3）；上架随版本注册转 app-bound（M10）
├── RecordStudio         # 录制 UX：内嵌浏览器 + 元素圈选标注 + 脆弱步骤处置（重录该段/换积木）
├── DraftEntry           # 草稿路径：一句话 → M08 草稿生成（8 轮/熔断/进度可视）→ C0 草稿库
├── DryRunPanel          # 本地干跑（M07 Replayer）+ 步骤级结果比对视图
├── CertifyPanel         # 认证提交（C1 本机 / C2 排期）+ 认证报告展示（PRD §8.5 格式）
└── PublishWizard        # 应用信息/定价/信任字段预览（v2 规则）/站点合规声明 → 提审
```


## 3. 关键流程（九步宿主映射）

```text
1 说需求/搜积木 → BlockSearchPanel（M08 block_search）
2 画布组装      → Canvas（兼容性校验；缺口提示进入 3）
3 缺积木        → RecordStudio（录制→M08 参数化→C0 草稿）
                 └ 仍无路径 → DraftEntry（对话草稿，逃生舱）
4 启动表单      → 表单编辑器（M08 生成 schema 草案 → 人工调整）
5 本地干跑      → DryRunPanel（M07 Replayer；脆弱步骤 → RecordStudio 处置）
6 提交认证      → CertifyPanel（无登录 C2 / 含登录 C1，M09）
7 认证报告      → CertifyPanel 展示（通过率/样本/环境/归因；补测入口）
8 发布配置      → PublishWizard（信任字段预览 + 站点合规声明）
9 提审上架      → M10 状态机（certifying → in_review → …）
```

**复合积木流**：画布选中子图 → CompositePackager 打包命名 → 入我的模块库 → 拖入其他画布作为单节点（可展开）→ 应用提审时自动 app-bound 注册（作者不可删被引用版本）。

**脆弱步骤处置**：干跑失败步骤 → 高亮定位 → 两个动作：重录该段（保留其余轨迹）/ 替换为站点积木（若覆盖）。


## 4. 数据模型（本地）

```text
modules_lib(            # 我的模块库（复合积木）
  id, name, title, nodes_json, interface_json,
  side_effects, interactions_decl,
  cert_status,          # 聚合状态（组成积木明细 + 整链验证 N=1）
  created_at, updated_at
)
creation_sessions(      # 九步会话
  id, step, draft_workflow_json, lock_draft_json,
  recordings_refs, autosave_at
)
c0_drafts(              # 草稿积木库
  id, name, origin,     # record | dialog
  trace_ref, block_dir, created_at
)
```


## 5. 接口

- 内部：FlowOrchestrator 步骤 API（`goto/complete/rollback`，产物自动保存钩子）；
- 对 M08：`start_session(requirement_text)` / `search_blocks(session_id)` / `assemble(session_id, chosen_refs)` / `parameterize(session_id, trace_ref)` / `draft_codegen(session_id, spec)` / `session.pause/resume(session_id)`（会话管理，非 M16 协议）；
- 对 M07：`record.start(host)` / `record.stop() → trace_ref` / `record.annotate(trace_ref, step_seq, element_ref, hint)` / `replay.run(trace_ref, params, mode=local)`（干跑）；
- 对 M09：`POST /certifications`（提交）/ `GET /certifications/{id}`（报告）；客户端侧 `certify(block_ref, n, params)`；抽查任务 `GET /certifications/spotcheck/tasks` + `POST .../accept`；
- 对 M05：`task.submit / task.cancel / task.defer`（调试运行经 sidecar 任务控制）；
- 对 M10：`POST /apps/{id}/submit`（提审）/ `POST /apps/{id}/versions`（版本注册；复合积木 app-bound 注册随版本注册执行，无独立接口）；创作漏斗 `POST /metrics/creation_funnel`。


## 6. 依赖与被依赖

- 依赖：M07（录制/回放/SDK）、M08（检索/参数化/草稿）、M09（认证）、M10（发布/注册）、M16（调试区交互宿主）、M01（窗口/存储）、M06（内嵌浏览器会话）。
- 被依赖：无（终端 UX 模块）；阶段 3 gate 的创作成功率埋点由本模块上报（会话漏斗：各步骤进入/完成/放弃）。


## 7. 验收标准

1. **阶段 1 最小版**：平台内部用户用九步流程完成 3-5 个自制应用（含 1 个高变更站点场景），全程不打开代码编辑器；
2. 副作用拦截：无 confirm 后置的发布类积木流程无法保存（自动化测试）；
3. C0 拦截：含未认证积木的应用在提审入口被拦截并给出转正路径提示；
4. 复合积木：打包→模块库→复用→连线→提审 app-bound 注册全链路可演示；嵌套 2 层上限与引用环拒绝生效；**含 C0 内层的复合积木在打包与提审两处被拦截**；
5. 会话恢复：任一步骤杀死客户端，重启后回到最近自动保存点；
6. 脆弱步骤：干跑失败→重录该段→再次干跑通过，用例可复现；
7. **阶段 3 gate 埋点**：创作漏斗（步骤进入/完成/放弃、耗时、Token）全量上报，支撑"创作成功率 ≥60%"口径；
8. 通过率展示：任何列表/详情中的通过率均带 N 与时间窗（无样本量显示"数据不足"）；C1 场景强制显示"创作者环境实测，平台抽查复核"标注；整链验证结果标注"非统计值"。


## 8. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M02-a（阶段 1 最小版） | FlowOrchestrator + Canvas 基础 + DryRunPanel + CertifyPanel（内部工具级） | 20-30 人日 |
| M02-b | RecordStudio（录制 UX + 圈选标注 + 脆弱步骤处置） | 15-20 人日 |
| M02-c | CompositePackager + 模块库 | 10-15 人日 |
| M02-d（阶段 3） | DraftEntry + PublishWizard + 创作漏斗埋点 + 非技术用户可用性打磨 | 15-25 人日 |

M02-a 依赖 M07-a/b、M09-a/b 就绪；M02-d 前置为阶段 2 gate 通过。
