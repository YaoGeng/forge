# M16 Interaction Protocol 模块设计 v1.0

> **职责**：运行中一切"暂停 → 用户操作 → 恢复"的统一协议——InteractionBroker（权限+Schema+记录）、超时分级与挂起（suspended）、72h 恢复窗口、崩溃恢复语义、两族控件协议、创作者调试区与用户运行中心共用的宿主规范。
>
> **上游依据**：`01-产品文档.md` v14.1 §4；`02-技术架构.md` v8.1 §6.3、附录 D。
>
> **状态**：起草（2026-10-14）。阶段 1-2 逐步交付（waiting_user → suspended → 恢复窗口）。


## 1. 职责与边界

| IN | OUT |
|---|---|
| `runtime.interact.ask(spec)` 的 Broker（权限校验/Schema 校验/记录） | 控件的具体 UI 实现（M03/M02 宿主渲染） |
| 状态机片段：waiting_user ↔ suspended → cancelled（M05 状态机的协议方） | 登录态捕获与落库（M04，login 完成事件触发） |
| 超时分级（表单族 10min / 浏览器族 2h，可续期）与续期 API | 浏览器会话保活策略（M06，协议只发指令） |
| 恢复响应校验（response schema + interaction_id 匹配） | 任务队列/定时调度（M01 TaskScheduler 承载，M03 管理 UI） |
| interactions 表全生命周期（pending / suspended / resolved / cancelled / timeout） | 通知推送通道（M01，事件出口） |
| 崩溃/休眠后的恢复裁决（节点级重跑建议） | — |

**核心不变量**：
1. 交互响应必须过 Schema 校验且 interaction_id 匹配——不匹配即拒绝（防串台/重放）；响应写入审计日志（PRD §4 威胁：交互欺骗）；
2. 登录、验证码、确认类交互**永不预授权**——无人值守只允许"挂起等人"，不允许"代答"；
3. 挂起/取消不回滚已发生的外部副作用；副作用节点的 confirm 对话框固定携带"重复执行可能产生重复效果"提示。


## 2. 组件分解

```text
M16 Interaction Protocol
├── InteractionBroker    # ask 入口：interact:<type> 权限校验 → spec 校验 → id 生成 → interactions 落库 → 状态机转移
├── ResumeService        # resume 入口：id+response 校验 → 会话恢复；续期（extend）
├── TimeoutGovernor      # 超时矩阵执行：表单族 10min/浏览器族 2h 默认，可续期；到期 → suspended
├── SuspensionManager    # suspended 生命周期：72h 恢复窗口、通知、浏览器会话关闭指令（挂起 2h 后）、超窗 → cancelled
├── PanelProtocol        # 控件族协议：spec → 控件渲染描述（两族八类型），宿主无关
└── RecoveryAdvisor      # 崩溃/休眠后：按 checkpoint 与副作用状态给出节点级重跑计划
```


## 3. 关键流程

### 3.1 ask → waiting_user → resume

```text
组件 runtime.interact.ask(spec)
  ↓ Broker：interact:<type> 权限（无 → permission_denied）
  ↓ spec Schema 校验 → interaction id → interactions(pending)
  ↓ 会话 running → waiting_user（携带 spec）
  ↓ PanelProtocol 推送到宿主（M03 运行中心 / M02 调试区）
用户操作 → resume {interaction_id, response}
  ↓ Broker：id 匹配 + response Schema 校验（不过 → interaction_invalid_response → failed）
  ↓ interactions(resolved) → waiting_user → running → 组件收到响应继续
```

### 3.2 超时与挂起

```text
等待中 → 超时矩阵到期（表单族 10min / 浏览器族 2h，宿主可提示续期）
  → interactions(timeout) → 会话 → suspended
  → 通知用户（M01 推送）；浏览器族进入挂起时即提示"会话将在 2 小时后关闭"
72h 恢复窗口：
  ├─ 用户恢复 → suspended → running（浏览器会话已关的节点 → RecoveryAdvisor 节点级重跑）
  └─ 超窗 → session_expired → cancelled
```

### 3.3 崩溃/休眠恢复

- waiting/suspended 期间客户端崩溃或休眠：组件内恢复**不支持**；
- RecoveryAdvisor：读 checkpoint（M05 §7.2）→ 已完成节点跳过 → 当前节点重跑；副作用节点 → 先 `side_effect_confirm_required`（confirm + "可能已执行"提示）再重跑。

### 3.4 两族控件协议（PanelProtocol）

| 族 | 类型 | 渲染描述要点 |
|---|---|---|
| 表单族 | input/select/confirm/review | 按 spec.schema 渲染表单控件；review 带 items 列表+勾选+actions |
| 浏览器族 | login/captcha/pick/takeover | 内嵌浏览器 + 提示 + 完成按钮；login 完成事件触发 M04 凭证落库；pick 高亮候选元素 |

宿主差异仅容器（运行中心面板 / 创作者调试区），协议与控件一致。

**凭证配置类 waiting_user 的承载映射**：`credential_missing / credential_revoked`（附录 D）触发的"凭证配置"交互按来源分族——站点凭证缺失/过期 → **浏览器族 login**（重新登录）；模型 Key 缺失（M04）→ **表单族 input**（模型配置引导）；两族的 spec 规范与其他同类交互一致，不新增控件类型。


## 4. 数据模型

```text
interactions(
  id, task_id, node_id, type, family,        # family: form | browser
  spec_json, response_json,
  status,        # pending / resolved / cancelled / timeout / suspended
  timeout_at, extended_count,
  created_at, resolved_at
)
```

全部交互记录走脱敏管道；隐私政策披露留存策略，设置内可清理（M03）。


## 5. 接口

- sidecar API：`interact.ask(spec)` / `interact.resume(id, response)` / `interact.extend(id)`；
- 客户端 IPC：`panel.push(interaction)` / `panel.submit(id, response)`；
- 事件出口：`interaction.created / resolved / timeout / suspended`（M01 通知订阅）。


## 6. 依赖与被依赖

- 依赖：M05（状态机与 checkpoint）、M04（login 落库钩子）、M06（浏览器族会话指令）。
- 被依赖：M03/M02（宿主渲染）、M08（装配会话的需求澄清经 M02 调试区宿主走 `type=input` 交互；转人工走 takeover）、M09（认证中 confirm 走 ResponseFixtures 而非面板——同一 spec 规范）、M01（通知）、M12（交互审计查询）。


## 7. 验收标准

1. 权限缺失的 ask 被拒绝且记安全事件；响应 id 不匹配/Schema 不过均拒绝（`interaction_invalid_response`）；
2. 超时矩阵：表单族 10min、浏览器族 2h 实测触发 suspended；续期有效；到期通知送达；
3. 72h 窗口：窗口内恢复成功；超窗 `session_expired → cancelled`；
4. 浏览器族挂起 2h 后会话关闭，恢复时该节点走重跑且副作用节点先 confirm；
5. 崩溃恢复：kill 客户端后重启，checkpoint 跳过已完成节点，副作用节点不自动重发；
6. 两族控件在运行中心与调试区两个宿主渲染一致（同一 spec 快照测试）；
7. 登录/验证码/确认类无任何自动应答路径（代码审查 + 集成测试双证）。


## 8. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M16-a | Broker + interactions 表 + ask/resume + 表单族协议 | 12-15 人日 |
| M16-b | 超时矩阵 + suspended + 通知 + 恢复窗口 | 10-14 人日 |
| M16-c | 浏览器族协议 + 会话关闭/恢复联动 | 8-12 人日 |
| M16-d | RecoveryAdvisor + 崩溃恢复联调 | 6-10 人日 |
