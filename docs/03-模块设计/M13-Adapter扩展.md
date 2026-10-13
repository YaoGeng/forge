# M13 WASM/Docker/API Adapter 模块设计 v0.5（骨架）

> **职责**：Runtime 执行形态扩展——wasm / docker / api 三类 adapter 的接入边界、权限类型、与出口代理/沙箱的约束关系。本骨架只锁定边界与启用前置条件，不含详细设计。
>
> **上游依据**：`02-技术架构.md` v8.1 §2.1（runtime.adapter 预留位）、§6.6（沙箱分级）、§11.1（权限全链路）；`01-产品文档.md` v14.1 §3.1、§15（WASM/Docker 移至阶段 5）；`04-评审报告-2026-10-13.md` §过度设计清单。
>
> **状态**：骨架（2026-10-14），**后置阶段 5**。阶段 1-4 的执行需求由既有 python / node / agent 三类 adapter 承载，本模块不投入实现资源。


## 1. 职责与边界

| IN | OUT |
|---|---|
| `runtime.adapter` 枚举扩展（wasm / docker / api）与运行时派发 | Linux 客户端整体支持（同阶段相邻事项，网络强制 netns 机制归 M05） |
| wasm 执行器接入（wasmtime，WASM 级沙箱） | 服务端认证沙箱的容器基础设施（M09 复用，非本模块范围） |
| docker 执行器接入（客户端侧执行形态，容器级沙箱） | Capability API 语义变更（沿用 M05 外观，不新增能力面） |
| api 执行器（外部 API 调用形态，具体形态 TBD） | 积木规范与认证流水线本身的改造（M07 / M09 各自扩展） |

**核心不变量**：

1. 三类 adapter 与 python / node / agent **同一约束域**：PermissionBroker + Egress Proxy + 资源限制，权限取积木声明集（对齐架构 §6.4 CodeAct 条款）——不因 adapter 类型放宽任何约束；
2. 出网唯一通道不变：wasm 实例、容器内进程、api 调用的出网一律经本地 Egress Proxy，未授权直连在网络强制层被丢弃（对齐 M05 核心不变量 1）；
3. wasm 二进制 / 容器镜像的变更属**代码变更**（minor/major、重新认证真实运行 N≥20、应用创作者重新发布）；其声明式资源是否保留 declarative patch 通道 TBD（阶段 5 前定）。


## 2. 为什么后置（评审结论）

- `04-评审报告-2026-10-13.md` §过度设计清单第 2 条：WASM/Docker Adapter 属过度设计——"买家装 Docker 是荒诞的；**python+agent 覆盖 95% 需求**"；
- 阶段 1-4 场景（站点积木、通用积木、录制回放、Agent 装配）全部落在 python / node / agent 执行形态内；剩余长尾需求（本地原生库、重型依赖、纯 API 集成）不足以在买家闭环与生态验证之前占用实现资源；
- 立项前必须以实际需求数据复核剩余需求规模与商业必要性（§4 第 1 条）。


## 3. 接入设计（骨架）

### 3.1 adapter 字段扩展

- `block.yaml` 的 `runtime.adapter` 在 `python / node / agent` 基础上扩展 `wasm / docker / api`（架构 §2.1 预留位）；
- Registry（M10）同步扩展枚举、包格式与签名分发校验；
- api adapter：积木主体为对外部 API 的调用描述（形态与 Schema TBD，阶段 5 前定），出网按既有 `domain` 权限逐域授权。

### 3.2 权限类型

| adapter | 权限类型 |
|---|---|
| wasm | 新增 `wasm_exec`（审批与默认策略 TBD，阶段 5 前定） |
| docker | 新增 `docker_exec`（审批与默认策略 TBD，阶段 5 前定） |
| api | 复用既有 `domain` 类型（按目标 API 域名逐域授权） |

- 新增类型进入权限全链路（架构 §11.1）：积木声明 → 应用聚合（lock）→ 安装授权 → 本地 grants → PermissionBroker / Egress Proxy 双闸；
- 安装含 `wasm_exec` / `docker_exec` 积木的应用时向用户显式授权（展示形态 TBD，阶段 5 前定）。

### 3.3 与 M05 出口代理 / 沙箱的约束关系

| 项 | 约束 |
|---|---|
| 沙箱级别（架构 §6.6） | wasm → WASM 级（wasmtime）；docker → 容器级（Docker / containerd）；api → 进程级（与 python / node 同域） |
| 出口代理接入 | wasmtime 实例与容器网络接入本地 Egress Proxy 的实现方式（消费级机器可行性）TBD，阶段 5 前定 |
| 防御边界 | 同 M05 诚实声明：网络强制防越权直连与低成本外泄，不防蓄意对抗；主防线 = 依赖白名单 + lint + 审核 + 签名 + 最小权限 |
| 静态检查 | wasm 二进制 / 容器镜像的 lint 检查面（能力声明一致、副作用声明、幂等键强制如何落地）TBD，阶段 5 前定 |


## 4. 启用前置条件清单（阶段 5 gate）

1. 阶段 4 gate 已达成（积木作者供给 ≥ 平台自营 50%），且存在经产品确认的"python / node / agent 无法覆盖"需求清单与规模评估；
2. Docker adapter 消费级可用性评估通过（目标机器容器环境装机率证据或免安装方案）；
3. `wasm_exec` / `docker_exec` 权限类型的全链路设计与安装授权 UI 评审通过；
4. wasm 模块白名单机制、镜像分发与哈希校验链设计完成（对齐 M05 §3.4 安装期通道原则）；
5. 出口代理对 wasmtime 实例 / 容器网络的强制覆盖方案经 Spike 验证（方式对齐 M05 §2）；
6. M09 认证流水线完成三类 adapter 的环境矩阵与断言方式适配；
7. M07 Block SDK 支持三类 adapter 的开发与调试回路；
8. 本模块详细设计 v1.0 评审通过。


## 5. 依赖与被依赖

- 依赖：M05（出口代理与网络强制、PermissionBroker、Capability API、沙箱与资源限制）、M07（Block SDK）、M09（认证适配）、M10（Registry 枚举 / 白名单 / 签名分发）；
- 被依赖：无内部下游——应用创作者经画布（M02）间接使用；装配助手（M08）检索展示不受 adapter 类型影响。

## 5.5 骨架期验收

- 前置条件可判定：§4 八项均引用可执行锚点（阶段 gate / Spike / 评审记录），无循环依赖（阶段 4 gate 作为本模块前置属正确方向：出口度量 ≠ 启动前置）；
- 边界可执行：`runtime.adapter` 枚举扩展方案与 M05 约束关系表经 M05/M07/M09 三方确认。
