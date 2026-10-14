# M06 浏览器 Runtime 与站点结构检测 模块设计 v1.0

> **职责**：浏览器自动化的执行底座——Patchright 会话管理、MCP 调试链路、站点结构检测（含礼仪强制）、结构化执行宿主、浏览器出网策略执行点、人工介入与验证码边界。
>
> **上游依据**：`02-技术架构.md` v8.2 §6.2（浏览器出网边界）、§7；`01-产品文档.md` v14.2 §7。
>
> **状态**：起草（2026-10-14）。阶段 1 模块，依赖 M05 Spike 结论。


## 1. 职责与边界

| IN | OUT |
|---|---|
| BrowserManager（Patchright 会话池/生命周期） | 录制轨迹的参数化（M08，消费本模块轨迹） |
| BrowserAgentBridge（MCP Server，标准环境配置） | 积木业务逻辑（M07 SDK 之上） |
| SiteInspector（站点结构检测 + 礼仪校验） | 页面结构特征库存储（M15，本模块只写入） |
| StructuredRunner（结构化执行回放宿主） | 出口代理与网络强制本体（M05，本模块是被约束方） |
| CdpAuditor（非导航注入请求审计上报） | 交互面板 UI（M16 协议 + M03/M02 渲染） |
| TakeoverService（人工介入会话移交） | 站点变更分级判定规则（M10 元数据，本模块只消费） |

**核心不变量**：
1. 浏览器出网遵守 M05 §3.3 三策略：导航主文档仅声明域、子资源放行并记录、CDP 注入非导航请求全量上报 CdpAuditor（M05 级位降级时按其 §2.3 降级属性表弱化并启用补偿控制）；
2. 站点结构检测的礼仪约束（目标域 ∈ 声明域、频次上限、单会话、仅公开页、robots、UA 与真实浏览器一致）在入口处强制校验，违规直接拒绝执行；
3. 验证码不处理、不重试、不代答——检测到即抛 `captcha_detected`（认证中计失败，运行中转交互）。


## 2. 组件分解

```text
M06 浏览器 Runtime
├── BrowserManager        # Patchright 会话池：启动/复用/销毁；环境标准化配置（架构 §7.4 分层归属）
├── BrowserAgentBridge    # MCP Server：Browser-Use 工具集 + 平台扩展工具
├── SiteInspector         # site_inspect：礼仪校验 → 采集 → 结构报告
├── StructuredRunner      # 结构化执行：按 M07 轨迹确定性回放（高变更站点主路径）
├── CdpAuditor            # CDP 事件流审计：非导航请求域名异常检测 → 安全事件
└── TakeoverService       # 会话移交：takeover 交互期间用户直操浏览器的通道管理
```


## 3. 关键流程

### 3.1 站点结构检测

```text
site_inspect(url, declared_domains)
  ↓ 礼仪校验（域 ∈ declared_domains；频次上限查询；单会话；公开页）
启动 Patchright（标准环境配置）
  ↓ 访问目标页
采集：DOM 结构 / selector 候选 / 登录流程形态 / 访问稳定性信号
  （响应状态、加载成功率、变更频率——无访问控制类字段）
  ↓
结构报告 → 写入 page_structures（M15）
  ↓
报告返回调用方（M08 开发计划 / M09 认证环境参考）
```

命中验证码 → 该次失败（captcha 归因），不重试不代答。

### 3.2 结构化执行（高变更站点主路径）

- 输入：M07 参数化轨迹 + 运行参数；
- 每步：按轨迹操作（click/input/scroll/wait/nav）→ 等待目标状态（来自录制的 DOM 锚点）→ 校验 → 下一步；
- 轨迹节奏保持录制时的真实时序（节奏控制层，架构 §7.4）；
- 步骤失败 → 标记脆弱步骤（返回 M02 提示重录/改用站点积木）；运行中则按节点错误码走 DAG 语义（M05 §7.3）；
- **回放入口裁决**：结构化执行经 M07 `replay.run(trace_ref, params, mode=structured)` 唯一入口发起，本模块的 StructuredRunner 为其在浏览器宿主的执行引擎封装。

### 3.3 人工介入（takeover）

```text
Agent 请求介入 → runtime.interact.ask({type:"takeover"})
  → TakeoverService 冻结自动化控制、移交用户直操通道
  → 用户完成 → 完成按钮 → 控制权回收 → 从当前页面状态续跑（节点级）
```

### 3.4 CDP 注入审计

- 订阅 CDP Network 域事件；过滤页面自然导航/子资源；
- 组件经 CDP 在页面内发起的 fetch/XHR：记录域名；lint（M07）静态禁止是第一道，本模块为运行时第二道；
- 同一非常规域名重复出现（阈值 TBD，模块细化时定）→ 安全事件 + 告警（M12 审计）。


## 4. 数据模型

```text
site_inspect_reports(          # 结构报告（客户端/服务端共用 schema）
  id, url, declared_domains_json,
  dom_digest, selector_candidates_json,
  login_flow_shape,            # 形态描述，不含凭证
  stability_json,              # 响应状态/加载成功率/变更频率
  robots_respected bool, created_at
)
cdp_audit_events( id, session_id, kind, domain, count, flagged bool, created_at )
```

写入 page_structures 走 M15 白名单校验（无访问控制类字段，拒收即告警）。


## 5. 接口

MCP 工具（BrowserAgentBridge，Browser-Use 工具集 + 扩展）：
`dom_snapshot` / `network_logs` / `console_logs` / `selector_pick` / `session_takeover_*` / `structured_script_run(trace_ref, params)` / `site_inspect(url)`。

内部 API（sidecar）：
- `browser.open(domain) → session`（域校验后创建）
- `browser.run_structured(trace_ref, params) → step_results`（= M07 `replay.run(mode=structured)` 的浏览器宿主封装）
- `browser.inspect(url) → report`
- 会话异常（崩溃/断连）→ 产生 `browser_crash`（附录 D）→ BrowserManager 自动重启会话 → 所在节点按 checkpoint 语义节点级重试（M05 §7）


## 6. 依赖与被依赖

- 依赖：M05（出口代理/沙箱约束域）、M07（轨迹格式与回放协议）、M16（interact.ask 协议）。
- 被依赖：M08（调试链路）、M09（沙箱执行器复用 StructuredRunner）、M02（录制/调试宿主）、M15（结构报告写入）。


## 7. 验收标准

1. 礼仪强制：对未声明域/超频次的 site_inspect 请求被拒绝并留审计记录；
2. 出网三策略实测：导航白名单外域被阻断、子资源放行有记录、注入请求进入审计流；
3. 结构化执行：同轨迹同参数在标准站点上重放 10 次结果一致（除声明的时间敏感步骤）；
4. 验证码：命中即 captcha 归因，无任何自动应答路径（代码审查 + 集成测试双证）；
5. takeover：移交-回收-续跑链路可演示，期间自动化控制确已冻结；
6. 结构报告入库通过 M15 白名单校验（含"拒收告警"用例）。


## 8. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M06-a | BrowserManager + MCP 桥 + 标准环境配置 | 12-18 人日 |
| M06-b | SiteInspector + 礼仪校验 + 报告管道 | 8-12 人日 |
| M06-c | StructuredRunner（依赖 M07 轨迹格式冻结） | 10-15 人日 |
| M06-d | CdpAuditor + TakeoverService | 8-12 人日 |
