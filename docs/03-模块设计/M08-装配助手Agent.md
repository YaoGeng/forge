# M08 装配助手 Agent 模块设计 v1.0

> **职责**：创作者侧的 LLM 装配工——理解需求、检索并推荐认证积木（搜与拼）、把演示录制轨迹参数化为积木草稿、在积木库无覆盖时按硬约束生成 C0 草稿积木（逃生舱），并产出对齐认证报告口径的创作侧汇报。
>
> **上游依据**：`02-技术架构.md` v8.1 §8、§6.4；`01-产品文档.md` v14.1 §6.1、§8.2、§8.4（报告呈现对齐 §8.5）。
>
> **状态**：起草（2026-10-14）。搜与拼/参数化随阶段 3 交付；对话式草稿生成按 PRD §15 为阶段 4 交付。


## 1. 职责与边界

| IN（本模块负责） | OUT（不属于本模块） |
|---|---|
| LangGraph 状态机编排（架构 §8.1） | 演示录制与回放执行（M07；本模块只消费轨迹） |
| 认证积木检索与推荐（ai_description + 通过率排序） | 画布 UI 与连线编辑（M02 宿主；本模块只产出草案） |
| 连线与参数草案生成（接口兼容性建议） | 积木静态检查（M07 Quality Skill，lint 独立执行） |
| 录制轨迹 LLM 参数化（三职责，§3.3） | 认证流水线（M09；report 后由创作者提交） |
| C0 草稿生成（CodeAct 执行器 + 调试循环治理） | 站点结构检测（M06）/ 模型 Key 配置（M04） |
| 创作侧汇报生成（对齐 PRD §8.5 呈现） | 用户运行中心（M03） |

**核心不变量**：
1. LLM 不产出可直接上架的代码——草稿生成物最高等级 C0（私用可用），上架必须经 M09 认证转正（PRD §8.4）；
2. 生成的代码与 CodeAct 执行器、组件进程同处一个约束域：M05 出口代理 + PermissionBroker + 资源限制，权限取目标积木声明集（架构 §6.4）；
3. 全部模型调用（含 CodeAct 的模型调用）经 ModelRouter，走创作者自配 Key（用户侧 Token 完全用户自付，PRD §16.3），逐次计量；
4. 调试循环上限 8 轮、连续 2 次同失败指纹终止转人工——实现为常量，非可配置项；
5. 参数化产物 = 录制轨迹 + 参数化配置（LLM 只做提升与标注，不发明执行逻辑）。


## 2. 组件分解

```text
Creator Center（M02 宿主：对话面板 + 画布）
   │ 会话事件 / 草案回显
   ▼
AssembleAgent（LangGraph 状态机，编排框架唯一）
  · GraphBuilder（节点/边/中断点）· SessionState（轮次/预算/失败指纹/best-so-far）
  ├─ BlockSearch：ai_description 检索 + 通过率排序，候选逐项带实测通过率
  ├─ Parameterizer：字面量→输入项 / 循环识别 / 提取字段→输出 Schema
  └─ DraftCoder：CodeAct 执行器（OpenHands SDK）+ debug_loop 治理
        │ 全部模型调用经 ModelRouter（M04）——计量 + 会话预算熔断
        ▼（熔断默认值随站点变更等级分档）
  M07 录制轨迹（参数化输入，仅本机）── M07 lint + dry_run（组件环境）
        └───── M05 约束域（出口代理 + PermissionBroker）─────┘
```

**编排与执行器边界**：LangGraph 只负责状态机编排、会话持久化与中断点（需求澄清/录制引导/转人工），不执行代码、不直连浏览器、不直连模型；OpenHands CodeAct 只是 draft_codegen 节点内的代码生成与自纠执行器，不做流程编排、不越出 M05 约束域，其模型调用同样经 ModelRouter 计量。


## 3. 关键流程

### 3.1 状态机（与架构 §8.1 一致）

```text
intake（理解需求）
  → block_search（检索认证积木，展示通过率）
  → assemble（生成连线与参数草案）
      ├─ 覆盖 → param_fill → dry_run → report
      └─ 不覆盖 → record_guide（引导演示录制，M07 执行）
                    → parameterize
                    └─ 仍不覆盖 → draft_codegen（C0 草稿，逃生舱）
```

- 覆盖判定标准：TBD（模块细化时定；方向为"目标子任务均有可用认证积木且接口可连通"）；任意节点可中断挂起（LangGraph interrupt）。**中断语义裁决**：需求澄清 = `interact.ask({type:"input"})` 经 M02 调试区宿主（M16 协议）；录制引导 = 应用内 UI 流程（**非** M16 协议承载）；转人工 = `intervention_required → takeover`（M16）。会话崩溃从最近 checkpoint 恢复。

### 3.2 搜与拼（block_search / assemble）

- 检索：积木 `ai_description`（block.yaml 声明）语义匹配 + 站点/能力/权限过滤；数据源 M10 Registry，可靠性数据来自 M09；
- 排序与展示：候选按认证等级与实测通过率排序，逐项展示通过率（纯真实运行口径，带样本量与测量时间）、认证等级、站点变更等级；高变更/受防护站点附 best-effort 标注；复合积木展示组成明细，不展示合成通过率（PRD §9.5）；
- assemble：生成 workflow.json 草案（节点/连线/参数初值）；接口兼容性以 JSON Schema 匹配校验（M02 画布最终裁决）；草案生成即遵守画布规则——副作用积木后必须接 confirm 积木（PRD §8.6）。

### 3.3 参数化（parameterize，输入来自 M07 录制轨迹）

本模块不做录制。输入 = M07 录制器产物：操作轨迹（click/input/scroll/wait/nav）+ 每步 DOM 快照 + 网络请求（仅存本机）。LLM 三职责：

1. **字面量 → 输入项**：识别演示中的字面量（搜索词、商品名等），提升为 `user_input_schema` 输入项（标题/类型/示例值取自演示值，脱敏为占位符）；
2. **循环识别**：识别重复操作模式，生成循环节点（重复段边界 + 每轮变化量与输入项的绑定）；
3. **提取字段 → 输出 Schema**：标记演示中被提取/复制/导出的字段，聚合生成 interface.json 输出 Schema。

产物 = 录制轨迹 + 参数化配置 + interface.json（C0 积木草稿，架构 §5.1）；全部结果可人工编辑（提升/取消/调整循环边界），LLM 只出草案；脆弱步骤（M07 回放标记失败）汇总提示重录该段或改用站点积木（PRD §8.3）。

### 3.4 草稿生成（draft_codegen，硬约束）

触发：block_search 无覆盖且录制路径仍不覆盖，创作者显式选择后进入。调试循环对齐架构 §8.3：

```text
codegen → lint（M07）→ dry_run（M07 组件环境）
  ├─ 通过 → report（C0，标注未认证）
  └─ 失败 → debug_loop（上限 8 轮）
        ├─ Token/金额硬上限熔断（ModelRouter 强制，默认值随站点变更等级分档）
        ├─ 每轮留存 best-so-far，预算/轮次耗尽回滚到最优版本而非最后版本
        ├─ 失败指纹 = hash(failure_class + selector/url + error_code)
        └─ 连续 2 次同指纹 → 终止转人工（intervention_required → takeover，M16）
```

- 熔断分档默认值与 best-so-far 评判标准：TBD（模块细化时定；方向为 lint 通过 + dry_run 前进最远）；创作者可配置会话预算（架构 §8.4），熔断机制不可关闭；
- 约束域：生成代码在 M07 组件环境（独立 venv、白名单依赖）执行，浏览器操作经 M06 调试链路，全程 M05 双闸；产物最高等级 C0（标注"未认证"，私用可用），上架必须提交 M09 认证转正。

### 3.5 模型路由与计量

- 全部调用经 ModelRouter，走创作者自配 Key；能力分级 fast/reasoning/vision，未配置回退 fast 并提示（M04）；会话级明细 provider/model/tokens/cost；创作耗时与 Token 成本 p50/p95（PRD §14 校准类指标）数据由此管道上报。

### 3.6 汇报格式（report，对齐 PRD §8.5）

```text
装配汇报：{积木/应用名} v{版本}
覆盖路径：认证积木组装（组成积木实测通过率明细）/ 录制参数化草稿（C0，未认证）
干跑：N 次本地干跑，通过 M 次（回归口径，标注"非统计值"；实测通过率以认证报告为准）
环境：{OS / 浏览器 / 本机}
失败归因：{failure_class 明细}；脆弱步骤：{列表或"无"}
需要的权限：{domain / credential / ai / interact …}
需要的交互：{login / input / confirm …}
站点变更等级：{等级}（高变更/受防护 → best-effort 标注）
[提交认证]  [补跑干跑]  [查看失败详情]  [转人工]
```

口径约束：本模块只产生干跑/回归口径数据；live 通过率仅由 M09 认证批次产生，两口径不得混算（架构 §4.2）。


## 4. 数据模型

客户端（SQLite，架构 §12.3 归属）：

```text
agent_sessions(
  id, creator_id, workflow_id,
  state,                    # 状态机全态 + done / aborted
  requirement_json,         # intake 结构化产物（目标站点/动作/输入输出/是否登录）
  coverage_verdict,         # covered / record_path / draft_path
  budget_json, spent_json,  # 会话预算（分档默认 + 创作者配置）/ ModelRouter 累计
  best_run_id,              # best-so-far 指针（draft 路径）
  created_at, finished_at
)
parameterize_runs(
  id, session_id, trace_ref,       # → M07 recordings（主标识统一为 trace_ref）
  param_config_json,        # 输入项映射 / 循环 / 提取字段（人工可编辑）
  interface_draft_json, fragile_steps_json, created_at
)
draft_debug_runs(
  id, session_id, round_no,          # ≤ 8（常量）
  code_hash, lint_result, dry_run_result,
  fingerprint,               # hash(failure_class + selector/url + error_code)
  is_best, terminated_reason, created_at
)                            # terminated_reason：passed / rounds_exhausted /
                             # budget_exceeded / repeated_fingerprint
```

检索候选（block_search 结果）作为会话工件存 artifacts，不单列持久表。


## 5. 接口

**客户端模块 API（对 M02 宿主）**：
- `start_session(requirement_text) → session_id`；`search_blocks(session_id) → candidates[]`（逐项含通过率 + 样本量 + 时间窗 + 等级 + 站点变更等级）；
- `assemble(session_id, chosen_refs) → workflow_draft`；`parameterize(session_id, trace_ref) → param_draft`；
- `draft_codegen(session_id, spec) → draft_result`（受 §3.4 硬约束）；`session.pause/session.resume(session_id)`（**会话管理 API，非 M16 协议**——协议级交互经 `interact.ask/interact.resume`，M16；转人工走 takeover）；
- 事件流：状态转移/轮次进度/熔断与终止事件（WS，M01 通道）。

**消费的服务端 API**：
- `GET /blocks/search`（M10 Registry：ai_description 语义检索）；`GET /blocks/{name}/versions/{v}/reliability`（M09 详情页初始分，带 N 与时间窗）。


## 6. 依赖与被依赖

- 依赖：M04（ModelRouter 路由/计量/熔断）、M05（约束域：出口代理 + PermissionBroker + 资源限制）、M06（浏览器调试链路）、M07（录制轨迹输入、lint、dry_run、组件环境）、M02（宿主 UI）、M09（可靠性数据源与认证提交）、M10（积木检索数据源）、M16（takeover/挂起协议）。
- 被依赖：M02（创作主流程的智能层）、M07/M09（parameterize 与 draft 产物为认证候选来源）、M14（阶段 4 草稿入口的产品承载）。


## 7. 验收标准

1. 状态机三条路径端到端可演示：覆盖路径（intake→…→report）、录制参数化路径、草稿生成路径各一条完整会话记录；
2. block_search 候选逐项带实测通过率与样本量；样本不足显示"数据不足"；任意输出不出现合成通过率；
3. 参数化：给定含字面量、重复模式、提取字段的录制轨迹 → 产物含输入项提升、循环节点、输出 Schema，全部可人工编辑；脆弱步骤被标记并给出重录/改站点积木提示；
4. 草稿生成：第 9 轮请求被常量拒绝；预算耗尽后交付物为 best-so-far；构造连续 2 次同指纹失败 → 会话终止并进入 takeover；
5. 约束域：CodeAct 执行器内访问白名单外域名 → `egress_denied`；未声明权限调用 Capability API → `permission_denied`（双闸各验证一例）；
6. 计量：任一会话可查 provider/model/tokens/cost 明细；全部调用记账到创作者自配 Key，无平台代付路径；
7. 汇报口径：report 中干跑数据标注"非统计值"，不产生 live_pass_rate 字段。


## 8. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M08-a | LangGraph 骨架 + intake/block_search/assemble（检索 + 通过率排序 + 草案） | 12-18 人日 |
| M08-b | parameterize（三职责 + 脆弱步骤 + 可编辑草案 + interface 生成） | 12-18 人日 |
| M08-c | draft_codegen（CodeAct 集成 + 8 轮/熔断/best-so-far/指纹/转人工） | 15-20 人日 |
| M08-d | report 汇报 + ModelRouter 计量/熔断对接 | 5-8 人日 |

M08-a/b 随阶段 3（画布完整版）；M08-c 按阶段 4 交付；parameterize 依赖 M07 录制器最小版。
