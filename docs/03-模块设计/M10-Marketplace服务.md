# M10 Marketplace 服务 模块设计 v1.0

> **职责**：平台的服务端交易与分发底座——Block Registry 与双级签名分发、上架状态机与审核、订单结算与保障金池（含冲正分录与资金追回）。
>
> **上游依据**：`02-技术架构.md` v8.2 §3、§10（lock 与复合积木裁决见 §2.4-§2.5）；`01-产品文档.md` v14.2 §13。
>
> **状态**：起草（2026-10-14）。**阶段 2 核心交付（买家闭环）。**


## 1. 职责与边界

| IN（本模块负责） | OUT（不属于本模块） |
|---|---|
| Block Registry（blocks / block_versions / block_refs） | 认证执行与报告生成（M09；本模块只消费 verdict） |
| 应用包 + 积木包双级 ed25519 签名与密钥治理 | 健康检测与失效归因判定（M11） |
| patch 发布侧 declarative diff 强制校验 + 灰度推送 | 自修复候选生成与回归（M15） |
| 上架状态机 + 发布审核清单工作流 | 管理后台 UI（M12） |
| 订单、激活校验、24h 全退、维护期失效退款 | 用户端商店渲染与本地 lock 解析（M03 / 客户端 Update Service） |
| 结算（70/30）、保证金 20% 双月 6 期、提现实名 | 支付渠道与发票细节（外部网关，TBD（模块细化时定）） |
| 保障金池台账、冲正分录、资金追回顺序 | — |
| 审计记录与认证报告归档（≥3 年） | — |

**核心不变量**：
1. 台账**只增不改**：退款/赔付/回补一律以冲正分录实现，原分录不可修改，每笔冲正关联原始订单与归因记录；
2. 金额一律「分」（整数），时间一律 UTC ISO8601；
3. `change_kind=declarative` 是唯一自动更新通道，**发布侧签名前强制校验**文件 diff 仅限声明式资源——服务端强制，不止客户端侧条件检查；
4. 权限上限 `permissions_max` **更新不可扩大**；composite 重发布时按内层权限并集重算，扩大则引用应用重新发布时走重新授权；
5. 24h 全退唯一判据 = **激活校验时间戳**：未完成激活校验 → 全退；完成激活即视为已使用（仍适用维护期失效退款），与运行上报开关无关；
6. 上架下架态一律 `delisted`（与任务挂起态 `suspended` 严格区分，见架构 §10.1 命名说明）。


## 2. 组件分解

```text
┌───────────────────────── Marketplace 服务端 ─────────────────────────┐
│ BlockRegistry                  SigningService（分发密钥域）           │
│  · blocks / block_versions     · 积木包 ed25519 独立签名              │
│    change_kind / distribution  · 发布侧 declarative diff 强制校验     │
│  · block_refs（patch_window）  · 多公钥信任集 / 轮换 / 吊销            │
│  · 权限上限（permissions_max）  │                                      │
│ UpdateChannel                  ListingService                        │
│  · 灰度 5%→50%→100%（按引用应用）· 上架状态机 + 审核清单工作流         │
│  · 批次冻结 / 回滚              │                                      │
│ OrderService                   SettlementService + GuaranteePool     │
│  · 订单 / 激活校验 / 退款受理    · 70/30 分账、保证金双月 6 期、实名提现│
│  · 争议期仲裁对接（M12）        · 保障金池台账 / 冲正分录 / 资金追回    │
│ ArchiveService：审计日志 + 审核记录与认证报告随版本归档 ≥3 年          │
└──────────────────────────────────────────────────────────────────────┘
```


## 3. 关键流程

### 3.1 上架状态机

```text
draft → submitted → certifying → in_review → approved → published
published → delisted（平台下架/安全事件）/ deprecated（创作者废弃）
certifying 未达阈值 → rejected（附认证报告）→ 修订 → submitted（重提回边）
```

- certifying 委托 M09 执行，verdict 回写后流转；阈值按 PRD §9.3（标准 ≥90% / 中变更 ≥85% / 高变更与受防护不设下限但强制 best-effort 标注）；
- **verdict → 状态机映射**：`pass` → in_review 可继续；`below_threshold` → rejected（附认证报告）；`partial`（部分认证，如缺 default_response）→ rejected（附"部分认证"标记，补齐后重提）；`rejected`（认证执行失败，如批次中断/环境不可用）→ 回 submitted 可重排期；
- in_review 审核清单：认证报告核验 + 站点合规声明 + AI 内容标识 + confirm 覆盖 + 权限最小化；
- delisted：下架应急 SOP（安全事件触发 + 用户通知推送，M12 执行）；deprecated：创作者废弃，提前 30 天通知，已购用户保留最后版本本地使用权；
- rejected 重提：修订后回 submitted 重走认证；含 C0 积木的应用不可进入 submitted。

### 3.2 双级签名与密钥治理（架构 §3.2）

- `.aapkg` 应用级签名（不内嵌积木，客户端按需拉取签名积木包）；积木包独立 ed25519 签名；**打包/签名时强制剔除 `tests/golden/`**（golden 不随包分发，架构 §2.1——签名清单不含 golden 文件，客户端验签时 golden 不在包内为验收项）；
- **认证签名密钥与分发签名密钥分离**：attestation 签名域（M09 设备密钥/认证报告）与分发签名域（Registry 签发积木包）互不混用；
- 客户端内置**多公钥信任集**：新旧密钥并行有效期 ≥2 个客户端版本，密钥与吊销清单随签名清单下发；
- 泄露应急：吊销对应密钥 + 强制客户端更新 + 受影响积木重签。

### 3.3 patch 发布侧校验与灰度推送

```text
patch 版本提交（change_kind=declarative）
  → 发布侧强制校验：文件 diff 仅限声明式资源（selector 配置/参数/prompt 文案）
     ├─ 违规 → 拒绝签名（留审计）
  → 权限集不扩大校验（vs permissions_max；违反即拒绝——防热更新提权；
     客户端侧 update_permission_escalation 安全事件由 Block Update Service 另行产生）
  → Registry 签名 → 灰度按引用应用分批推送：5% → 50% → 100%
  → 每批次客户端前置：验签 + smoke（单次干跑 + 接口 Schema 校验），失败自动回滚
  → 任一批次 smoke 失败率超阈值 → 冻结并回滚（阈值 TBD（模块细化时定））
  → 运行中任务不热替换，下次运行生效
```

- code / composite 无自动更新通道：代码文件变更 = minor/major → 重新认证（M09）→ 应用创作者重新发布；
- composite（distribution=app-bound：随应用分发、不计入积木市场、作者不可删除被引用版本）仅整体重发布，其 lock 条目 `patch_window: null`；内层原子积木 patch 走正常通道；同一应用内直接引用与经复合引用同一原子积木时统一单条 lock 条目（防 effective 归因分裂）；
- effective 变更（自动更新/回滚）写回 block_refs 并留审计；运行归因与健康聚合以 effective 为准（M11）。

### 3.4 订单与退款（PRD §13.1 / 架构 §10.2）

```text
购买（数字商品确认勾选）→ 订单 ¥P（以分记账）
  → 激活校验：支付成功即时触发（客户端会话内完成），客户端启动序列兜底（与运行上报开关无关）
     ├─ 24h 内未完成激活校验 → 全退
     └─ 完成激活 → 视为已使用，不适用 24h 全退（仍适用维护期失效退款）
维护期内积木失效超 7 天 → 按剩余维护月份比例退款
  · 失效判定以 Health 归因为准（user-side 类不算失效，矩阵见架构 §8.2）
  · 争议期 7 天，平台仲裁（M12 工作台）
```

### 3.5 结算与保证金释放（架构 §10.3）

```text
订单支付 ¥P
  ├─ 平台 30%
  └─ 创作者 70%
       ├─ 80% 可结算：跨过 24h 退款窗 + 7 天争议期后可提现（提现前实名认证）
       └─ 20% 保证金：双月释放一期，共 6 期（对齐 12 个月维护期）
```

- 台账含 `disputed` 状态与申诉流程；
- 保障金池初始资金由平台注资（30% 抽成的风险对价组成部分）；阶段 2 平台自制应用期间赔付由平台全额自担。


### 3.6 失效归因五档与保障金池

| 归因档 | 处置 |
|---|---|
| 站点变更（非创作者过错） | 释放暂停，修复后恢复，不转入保障金池 |
| 创作者超 14 天未响应修复通知（含抽查重测超期未响应） | 未释放份额转入保障金池 |
| 平台积木缺陷 | 不罚创作者；平台赔付（保障金池资金优先，不足部分平台承担） |
| 废弃（deprecated） | 剩余释放暂停；维护期内废弃退款由平台承担 |
| **认证造假 / 抽查不符**（attestation_fraud，M09 attestation_invalid 触发） | 积木版本下架 + 该创作者未释放份额转入保障金池 + 账号信用降级；**不属失效归因四档，单列第五档**（处置链经此与台账打通） |

- 保障金池专项用途：受影响买家赔付与修复激励；归因输入来自 M11 检测/上报与 M12 复核；
- **资金追回顺序**：退款发生时 → ① 该订单未释放保证金优先冲抵 → ② 创作者未结算余额冲抵 → ③ 仍不足记平台垫付应收（创作者后续收入优先偿还）。


## 4. 数据模型

```text
blocks( id, name, distribution,               # public / app-bound
  owner_id, created_at )

block_versions( id, block_id, version, semver_part,
  change_kind,                                # declarative / code / composite
  interface_hash, permissions_max,            # 权限上限（更新不可扩大）
  pkg_uri, pkg_sha256, signature,
  certification_level, reliability_json,
  deprecated_by, created_at )

block_refs( app_id, block_name,
  base_version,                               # 发布时认证通过的精确基准
  patch_window,                               # 自动应用范围（同一次版本内）；composite 为 null
  effective_version )                         # 实际生效版本，变更留审计

app_versions( id, app_id, version, status,    # 上架状态机各态
  trust_fields_json, user_input_schema_json, lock_json, maintenance_until )

orders( id, user_id, app_version_id, amount_cents,
  status,                                     # paid / refund_full / refund_partial / disputed
  activated_at,                               # 激活校验时间戳（24h 全退唯一判据；null=未激活）
  paid_at, created_at )

settlement_entries(                           # append-only（只增不改）
  id, order_id,
  entry_kind,     # platform_share / creator_settleable / guarantee_held /
                  # guarantee_release / reversal（冲正，负向金额）
  amount_cents, period_index,                 # 保证金期次 1-6（保证金类分录）
  reverses_entry_id,                          # 冲正分录指向原分录（冲正必填）
  attribution_id,                             # 冲正关联失效归因记录
  status,                                     # pending / available / withdrawn / disputed
  created_at )

guarantee_pool_ledger(                        # 保障金池台账（append-only）
  id, entry_kind,     # platform_inject / transfer_in / payout / platform_cover
  amount_cents, ref_order_id, attribution_id, approved_by, created_at )

attributions(                                 # 失效归因（五档）
  id, app_id, block_version_id,
  kind,           # site_change / creator_no_response / platform_defect / deprecate / attestation_fraud
  evidence_json, status, created_at )          # creator_no_response 的 evidence 区分两种触发源：修复通知超期 / 抽查重测超期

settlement_accounts( id, creator_id, realname_status, ... )   # 结算账户（提现实名）
withdrawals( id, account_id, amount_cents, status, created_at ) # 提现记录（append-only 关联 settlement_entries）

notifications( id, user_id, kind, payload_json, receipt_at, created_at )
                                              # 服务端通知（失效/下架应急/废弃/认证结果；M01 拉取与回执）

audit_logs（状态迁移/签名拒绝/审批全留痕），审核记录与认证报告随版本归档 ≥3 年
```


## 5. 接口

**服务端 REST（/api/v1）**——**`/blocks/*` 资源根属主为本模块（Registry 属主）**；M09 子资源 `/blocks/.../reliability`、M11 `/blocks/.../health` 挂靠本命名空间，路由与版本化以本模块契约为准：
- 商店：`GET /apps`、`GET /apps/{id}`（信任字段 v2 素材：分列通过率——认证初始 + 用户滚动两维、维护期截止日、Token 成本区间、best-effort 标注、页脚声明）；
- 上架：`POST /apps/{id}/submit`、`POST /apps/{id}/versions`（版本注册入口，发布侧校验在此执行）；
- 分发：`GET /blocks/{name}/versions/{v}/pkg`（包 + 签名清单，**不含 tests/golden/**）、`GET /trust/keys`（多公钥信任集/吊销清单）、`GET /updates/plan?app_id=&client_version=`（灰度批次计划，Block Update Service 消费，含 smoke 失败率回报）；
- 交易：`POST /orders`、`POST /orders/{id}/activate`（支付成功即时触发，客户端启动兜底）、`POST /orders/{id}/refund-request`；
- 结算：`POST /withdrawals`（前置校验实名状态）、`GET /creators/me/settlements`；
- 通知（M01 消费）：`GET /notifications?since=`、`POST /notifications/{id}/receipt`；
- 指标接收：`POST /metrics/creation_funnel`（M02 创作漏斗事件落点，按月聚合成创作成功率，PRD §14）；
- 管理（M12 消费）：审核队列、下架应急、仲裁处置、保障金池审批、对账报表。


## 6. 依赖与被依赖

- 依赖：M09（认证 verdict、reliability_json）、M11（失效归因与退款判据输入）、M15（修复记录回填）、对象存储（包与报告）、外部支付渠道（TBD（模块细化时定））。
- 被依赖：M03（商店/订单/更新拉取）、客户端 Block Update Service（灰度计划、信任集、smoke 上报）、M12（审核/仲裁/财务工作台）、M11（Registry 版本元数据）、M14（阶段 4 积木市场在 Registry 上扩展）。


## 7. 验收标准

1. 发布侧校验：提交含代码文件变更的 patch → Registry 拒绝签名并留审计（服务端独立于客户端检查）；
2. 提权防护：patch 权限超 permissions_max → 拒绝发布；composite 重发布权限并集扩大 → 引用应用标记需重新授权；
3. 灰度：5%→50%→100% 分批可见；构造批次 smoke 失败率超阈值 → 冻结并回滚；运行中任务不热替换（下次运行生效）；
4. 状态机：全部迁移边可走通（含 rejected→submitted 重提、delisted/deprecated 终态与通知）；上架域不出现 `suspended` 命名；
5. 台账：退款/赔付后原分录不可变；冲正分录关联原始订单与归因记录；单订单分录代数和恒等于净额（对账测试）；
6. 资金追回：构造未释放保证金不足的退款 → 依次按 ①② 冲抵，缺口记平台垫付应收；
7. 24h 全退：未激活订单全退、激活订单不适用；关闭运行上报的账号无套利空间（判据与上报无关，联测）；
8. 归档：审核记录与认证报告随版本归档 ≥3 年且可检索；
9. 口径：全表金额为分（整数）、时间 UTC ISO8601（schema 层校验）；
10. golden 分发拦截：签名产物包内检索 `tests/golden/` 为空（任一渠道拉取的积木包断言）；
11. 通知：失效/下架应急事件入 notifications 且 M01 可拉取回执。


## 8. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M10-a | Block Registry + 双级签名 + 密钥治理（信任集/轮换/吊销） | 15-20 人日 |
| M10-b | 发布侧 declarative diff 校验 + 灰度推送 + 冻结回滚 | 10-15 人日 |
| M10-c | 上架状态机 + 审核清单工作流 API | 10-15 人日 |
| M10-d | 订单 + 退款 + 结算 + 保障金池台账/冲正/资金追回 | 20-25 人日 |

M10-d 的归因档依赖 M11 输出；M10 整体为阶段 2 买家闭环核心（gate：30 天退款率 <5% 且首跑成功率 ≥80%）。
