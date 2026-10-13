# 03-模块设计 索引

> 对应《02-技术架构.md》v8.1 附录 C。每模块一份设计文档；v1.0=完整设计（起草），v0.5=骨架（后置阶段）。

| 编号 | 模块 | 版本 | 文档 |
|---|---|---|---|
| M01 | 客户端应用框架 | v1.0 | [M01-客户端应用框架.md](M01-客户端应用框架.md) |
| M02 | Creator Center（组装工作台 + 复合积木画布 + 录制参数化） | v1.0 | [M02-CreatorCenter.md](M02-CreatorCenter.md) |
| M03 | 用户端应用 | v1.0 | [M03-用户端应用.md](M03-用户端应用.md) |
| M04 | 模型中心与凭证管理 | v1.0 | [M04-模型中心与凭证管理.md](M04-模型中心与凭证管理.md) |
| M05 | Runtime Core 与出口代理（**含 WFP/PF Spike**） | v1.0 | [M05-Runtime-Core与出口代理.md](M05-Runtime-Core与出口代理.md) |
| M06 | 浏览器 Runtime 与站点结构检测 | v1.0 | [M06-浏览器Runtime与站点结构检测.md](M06-浏览器Runtime与站点结构检测.md) |
| M07 | Block SDK 与测试框架（含录制回放） | v1.0 | [M07-BlockSDK与测试框架.md](M07-BlockSDK与测试框架.md) |
| M08 | 装配助手 Agent | v1.0 | [M08-装配助手Agent.md](M08-装配助手Agent.md) |
| M09 | 认证流水线（含本机认证器与抽查重测） | v1.0 | [M09-认证流水线.md](M09-认证流水线.md) |
| M10 | Marketplace 服务 | v1.0 | [M10-Marketplace服务.md](M10-Marketplace服务.md) |
| M11 | 健康系统（积木级） | v1.0 | [M11-健康系统.md](M11-健康系统.md) |
| M12 | Web 管理后台 | v1.0 | [M12-Web管理后台.md](M12-Web管理后台.md) |
| M13 | WASM/Docker/API Adapter | v0.5 骨架（阶段 5） | [M13-Adapter扩展.md](M13-Adapter扩展.md) |
| M14 | 积木市场 | v0.5 骨架（阶段 4） | [M14-积木市场.md](M14-积木市场.md) |
| M15 | 数据飞轮（二库）与声明式自修复 | v1.0 | [M15-数据飞轮与自修复.md](M15-数据飞轮与自修复.md) |
| M16 | Interaction Protocol（含挂起语义） | v1.0 | [M16-InteractionProtocol.md](M16-InteractionProtocol.md) |

## 评审记录（2026-10-14）

三路并行评审（客户端侧 5 份 / 运行时侧 6 份 / 服务端侧 5 份）完成，**13 项阻塞全部修复**：

- **跨模块接口断链**（最大风险类）：M02 六个接口对齐被调方实签；通知通道落 M10（notifications API + 表）；错误码→failure_class 映射归属统一为 M09（架构 §8.2）；定时/队列调度归属裁决为 M01 TaskScheduler（触发 M05 task.submit）；
- **轨迹标识统一为 `trace_ref`**（M07 权威 + recordings 表）；**确定性回放唯一入口 = M07 `replay.run`**（M06/M02 均为封装）；M08 会话 API 更名 session.pause/resume（与 M16 interact.resume 消歧）；
- **golden 分发链路闭环**：M09 接收校验 + 存储边界、M10 打包/签名剔除（双防线 + 联测验收）；
- M05 二级降级与不变量的矛盾：新增**降级属性表**（每级保留/放弃的属性 + 补偿控制）；
- M09 验收数学矛盾（48h 批次 vs 48h 报告）：改为"批次跨度 ≥48h 且提交到报告 ≤72h"；不变量补"限频"；
- M10 归因新增第五档 `attestation_fraud`（抽查不符处置链与台账打通）；verdict→状态机映射表；/blocks 命名空间属主声明；
- M11 应用健康口径修正（通过率不合成 ≠ 健康分不聚合）；component_version_id → block_version_id（M11 + 架构回写）；
- M14 循环前置修正（供给 ≥50% 从启动前提改为阶段 4 出口度量）；M13/M14 补骨架期验收；
- 激活校验时机统一（支付成功即时触发 + 启动兜底）；M04 境外提示无条件固定、credential_missing 承载分族注记、site_tier 字段更名；M15 平台 LLM 网关归属修正。

**遗留建议**（随模块细化处理）：① "代码审查"类验收转为 CI 可重复断言（IPC surface 扫描 / schema 禁字段检查）；② M16 时钟注入声明随实现同步；③ Capability API 签名权威定义处 M05↔M06 互引；④ 各文档 TBD 数值项（熔断分档、崩溃退避、通知分类清单等）。

## 实施顺序（阶段 1）

```text
M05-Spike（WFP/PF 验证，Go/No-Go）──┐
M07-a（block.yaml + lint）──────────┼→ M06-a/b ──→ M07-b/c（录制回放）──┐
M09-a（调度器 + C2 沙箱）───────────┘                                    │
M01-a（客户端壳）── M04-a（模型中心）── M02-a（Creator Center 最小版）←──┘
                                     └→ 阶段 1 出口：覆盖率实验 gate ≥60%
```

关键外部依赖关系：M07 轨迹格式冻结是 M02-b/M06-c/M09 回归路径的共同前置；M05 Spike 是全链路 Go/No-Go。
