# M05 Runtime Core 与出口代理 模块设计 v1.0

> **职责**：本地运行时的安全底座——出口代理与平台网络强制、Capability API 与 PermissionBroker、sidecar 生命周期、组件环境隔离、DAG 执行器（含副作用语义）。
>
> **上游依据**：`02-技术架构.md` v8.1 §2.3、§6；`01-产品文档.md` v14.1 §4。
>
> **状态**：起草（2026-10-14）。**阶段 1 第一个模块，含前置 Spike。**


## 1. 职责与边界

| IN | OUT |
|---|---|
| Egress Proxy（本地代理 + 策略引擎） | 浏览器自动化实现（M06） |
| 平台网络强制（WFP / PF / netns） | 积木 SDK 与测试框架（M07） |
| Capability API 外观 + PermissionBroker | Interaction 面板 UI（M03/M16） |
| Sidecar 进程模型与生命周期 | 模型中心/凭证存储（M04，仅调用） |
| 组件环境隔离（venv/白名单安装） | 认证流程编排（M09，复用本模块） |
| DAG executor（状态机/checkpoint/副作用矩阵） | — |

**核心不变量**：
1. 在**目标级位**下，组件进程（含 CodeAct、依赖安装器）出网**唯一通道**是本地 Egress Proxy，直连在网络层被丢弃；级位降级时本不变量按 §2.3 降级属性表弱化并启用补偿控制；
2. 副作用节点禁止自动重试，由类型系统（side_effects × 错误码）保证而非约定；
3. 权限判定 API 层（PermissionBroker）与网络层（Egress Proxy）**双闸独立**，任一层拒绝即拒绝。


## 2. 前置 Spike（阶段 1 第一个迭代，Go/No-Go）

### 2.1 Windows WFP 验证

- 目标：按进程树（sidecar 子进程）注册 WFP callout/provider，将出网流量重定向至本地代理端口，未注册进程直连丢弃；
- 验证点：① 子进程树继承规则（孙进程）；② 重定向后应用层可达性（代理收到原始目标）；③ 绕过尝试（raw socket、绑定其他网卡）被丢弃；④ 性能开销：与无代理直连对比的**握手 + TTFB 附加延迟 p95 <10%**（Spike 筛选口径；交付验收以 §10.7 代理总附加 p95 <100ms 为准）；
- 产出：Spike 报告 + Go/No-Go + 降级决策。

### 2.2 macOS PF 验证

- 目标：组件进程以专用用户/组运行，PF anchor 按 ugid 规则重定向至代理；
- 验证点同上 ②③④；额外验证专用用户的权限最小化（无文件系统越权）。

### 2.3 No-Go 降级路径与降级属性表

一级：容器级隔离（仅已具备容器环境的场景，消费级 Windows 不依赖）→ 二级：系统防火墙出站白名单（Windows 防火墙 / macOS pf 全局规则，粒度粗但零新依赖，最低保底）。降级决策写入 Spike 报告并同步架构文档。

**降级属性表（每级保留/放弃的安全属性与补偿控制，判定清单）：**

| 属性 | L0 WFP/PF | L1 容器级 | L2 防火墙白名单 |
|---|---|---|---|
| 组件出网唯一通道（代理策略引擎生效） | ✓ | ✓（容器 netns 内） | ✗ **放弃**——仅"白名单外阻断" |
| 白名单外域名阻断 | ✓ | ✓ | ✓（防火墙层） |
| 浏览器三策略（主文档限域/子资源放行记录/CDP 审计） | ✓ | ✓ | ✗ 弱化为 CDP 审计 + 白名单 |
| DNS 经代理（防隧道） | ✓ | ✓ | ✗（仅防火墙域名规则） |
| **补偿控制** | — | — | PermissionBroker API 层收紧（逐调用域校验）+ CdpAuditor 全量审计 + 高风险动作强制 confirm + 违规即安全事件 |

降级判定：Spike 报告按上表逐项给出各平台实测结论，Go/No-Go 与降级级别决策以本表为准；二级降级下 §10 验收②按"白名单外阻断"口径执行。


## 3. Egress Proxy 设计

### 3.1 架构

```text
组件进程（受限网络强制）──→ 本地 Egress Proxy（loopback）
                              ├── 策略引擎（ grants → domain 白名单 ）
                              ├── 浏览器策略路由（3.3）
                              ├── 安装期白名单通道（3.4）
                              └── 审计日志（CDP 注入异常告警接入）
```

### 3.2 组件流量策略

- 依据：运行会话的 grants（应用授权聚合后的 `domain:<host>` 集合）；
- 行为：白名单外连接 → 断开 + `egress_denied`（终态，记安全事件，security 归因）；
- DNS：组件进程 DNS 查询一并经代理解析（防 DNS 隧道外泄）。

### 3.3 浏览器流量三策略

| 流量类型 | 策略 | 实现点 |
|---|---|---|
| 页面导航主文档 | 仅允许声明域 | 代理层阻断（导航 URL 域名校验） |
| 页面子资源（CDN/字体/统计） | 放行并记录 | 代理层标记 passthrough |
| CDP 注入的非导航请求 | lint 静态禁止 + 运行时 CDP 事件审计 | M06 桥接上报；异常域名重复出现 → 告警 + 安全事件 |

### 3.4 安装期通道

依赖安装（uv venv 创建、包下载）走专用白名单源通道（PyPI 官方源 + 锁定哈希校验），源清单由平台签名下发，不可客户端配置。


## 4. Capability API 与 PermissionBroker

- 外观：browser / file / office / ai / code / data / api / credential / confirm / interact / probe（签名见架构 §6.4）；
- PermissionBroker：每次调用校验 grants（类型级）；credential 发放不透明 CredentialHandle；
- CodeAct 执行器与组件进程同一约束域（broker + egress + 资源限制，权限取积木声明集）；
- `runtime.confirm` / `runtime.interact.ask` 走 M16 协议（本模块只做 API 面）。


## 5. Sidecar 生命周期与安全

- 进程模型：Electron Main 拉起 sidecar（Python/FastAPI），崩溃监督 + 自动重启（会话上下文 SQLite 持久化，重启后节点级恢复）；
- 通道：named pipe（Windows）/ Unix socket（macOS）+ ACL 限本用户；会话期 HMAC 每请求校验（密钥启动时协商，不落命令行/环境变量）；
- 版本对齐：sidecar 版本与客户端版本锁死（manifest 声明，不匹配拒绝启动）；sidecar 更新随客户端更新通道；
- Chromium 获取：首启下载 HTTPS + 哈希校验（清单平台签名）。


## 6. 组件环境隔离

- 每积木独立 venv（uv 管理，锁定哈希）；
- 依赖白名单：Registry 侧维护（M10），安装请求经 3.4 通道；
- 隔离粒度：venv 级文件隔离 + 进程级网络强制；无跨组件可见性。


## 7. DAG 执行器

**任务控制 API（执行器面，M03 运行中心消费）**：`task.submit(app_ref, params, {schedule})` / `task.cancel(id)` / `task.defer(id)`（稍后继续 → suspended）；定时/队列调度由 M01 TaskScheduler 承载（触发时调用 task.submit），本模块只做执行。

### 7.1 会话状态机（与架构 §6.3 一致）

```text
queued → running → succeeded
   │ → failed / waiting_user / suspended（72h）→ cancelled / partial_succeeded
```

- waiting/suspended：组件进程存活，上下文持久化；浏览器会话挂起 2h 后关闭（该节点恢复时节点级重跑）；
- 崩溃/休眠恢复：不支持组件内恢复 → checkpoint 节点级重跑。

### 7.2 checkpoint

- 每节点输出持久化（artifacts + 结构化 output）；续跑 = 跳过已成功节点并注入缓存输出；
- 归因与统计按 lock `effective` 版本记录（运行时解析）。

### 7.3 副作用矩阵（retryable 判定）

| | 纯计算节点 | side_effects 节点 |
|---|---|---|
| 可重试错误（component_timeout 等） | 自动重试（按节点策略） | **禁止自动重试** → `side_effect_confirm_required` → waiting_user(confirm) |
| 不可重试错误 | → failed | → failed |
| 幂等 | 天然 | `idempotency_key` 强制（lint 前置）；confirm 对话框提示"重复执行可能产生重复效果" |

半执行态（请求已发出未收到响应）：保守处理为"已完成"，恢复时提示用户核查（不自动重发）。


## 8. 日志与脱敏挂点

- 统一 JSONL；本模块产生：安全事件（egress_denied/permission_denied/update_permission_escalation）、会话状态转移审计、安装审计；
- 全部日志经脱敏管道（M05 提供格式，脱敏引擎配置由平台签名下发）。


## 9. 依赖与被依赖

- 依赖：无内部前置（Spike 是唯一起点）；外部 Patchright/Browser-Use 经 M06 使用。
- 被依赖：M06（浏览器进程约束）、M07（组件运行环境）、M09（本机认证器复用 sidecar）、M16（状态机宿主）、M02/M03（任务执行宿主）。


## 10. 验收标准

1. **Spike Go/No-Go 报告**（Windows + macOS 双平台），No-Go 时降级方案决策已写入；
2. 绕过测试：组件进程尝试直连白名单外域名 → 全平台被丢弃并产生 `egress_denied` 安全事件；
3. 双闸测试：API 层放行但网络层未授权（或反之）→ 拒绝；
4. 副作用测试：构造超时的副作用节点 → 不自动重试、进入 confirm；半执行态标记"已完成"+ 提示；
5. 挂起测试：waiting_user 超时 → suspended；72h 窗口恢复成功；超窗 → cancelled（**TimeoutGovernor 支持时钟注入**，72h 窗口以最小可测时间单元回归，不按真实时长测试）；
6. 隔离测试：两个组件依赖同库不同版本 → 互不影响；
7. 性能：代理附加延迟 p95 < 100ms（局域网目标站点）。


## 11. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M05-Spike | WFP/PF 双平台验证 + 报告 + 降级决策 | 10-15 人日 |
| M05-a | Egress Proxy + 策略引擎 + 网络强制集成 | 15-20 人日 |
| M05-b | Sidecar 生命周期 + 通道安全 + 环境隔离 | 10-15 人日 |
| M05-c | DAG 执行器（状态机/checkpoint/副作用矩阵） | 15-20 人日 |

M05-Spike 必须最先完成；M09-a 可与 M05-a 并行。
