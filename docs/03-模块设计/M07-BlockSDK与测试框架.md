# M07 Block SDK 与测试框架（含录制回放） 模块设计 v1.0

> **职责**：积木的"开发语言"——block.yaml 规范与 SDK、测试断言体系（schema / golden 相似度）、演示录制与确定性回放、认证响应脚本夹具、幂等键钩子、静态检查（lint）规则集。
>
> **上游依据**：`02-技术架构.md` v8.2 §2.1-2.3、§5；`01-产品文档.md` v14.2 §8.3。
>
> **状态**：起草（2026-10-14）。**阶段 1 地基模块，轨迹格式是 M02/M06/M08/M09 的共同依赖，须最先冻结。**


## 1. 职责与边界

| IN | OUT |
|---|---|
| block.yaml v2 schema + 组件 SDK（Python/Node） | 轨迹的 LLM 参数化（M08，消费本模块轨迹格式） |
| Recorder：CDP 演示录制（轨迹+DOM 快照+网络） | 画布/录制 UX（M02 宿主） |
| Replayer：确定性回放（开发干跑/golden 回归/结构化执行协议） | 沙箱/本机认证编排（M09 宿主，复用 Replayer） |
| 断言体系：`assertion: schema \| golden_similarity` | 声明式自修复候选生成（M15，消费 lint 与 golden） |
| 认证响应脚本夹具（default_response） | 浏览器执行（M06 StructuredRunner 执行本模块协议） |
| idempotency_key 钩子规范（强制，lint 保证） | Registry 存储（M10） |
| lint 规则集（质量技能的机械化） | — |

**核心不变量**：
1. **golden 不随积木包分发**——仅存创作者本机（本地干跑）与认证服务端（回归），上传 golden 子集必须值脱敏为占位符；
2. 回放确定性：同轨迹同参数同 golden 环境下结果唯一（时间敏感步骤必须显式声明）；
3. 副作用积木无 `idempotency_key` 实现 → lint 失败 → 不可提交认证；
4. 轨迹格式一经冻结，破坏性变更走 minor（触发全部依赖模块适配评审）。


## 2. 组件分解

```text
M07 Block SDK 与测试框架
├── BlockSDK            # block.yaml 读写/校验；capabilities/permissions/interactions 声明；ComponentError
├── Recorder            # 内嵌浏览器 CDP 采集：轨迹（click/input/scroll/wait/nav）+ 每步 DOM 快照 + 网络请求
├── Replayer            # 确定性回放：轨迹驱动 + DOM 锚点等待 + 步骤校验；宿主=本地干跑/沙箱回归/M06 结构化执行
├── TestRunner          # 断言执行：schema 断言 / golden 相似度（嵌入余弦 + 字段级数值容差）
├── ResponseFixtures    # 认证响应脚本（default_response）夹具：confirm 自动应答 + 副作用两遍幂等验证
└── Linter              # 规则集（§6）：静态强制，M09 提交前置门
```


## 3. 关键流程

### 3.1 演示录制（创作侧，宿主 M02）

```text
创作者在内嵌浏览器亲手操作
  ↓ Recorder（CDP 采集，操作与 DOM 快照按步骤对齐）
轨迹 + 快照集 + 网络记录（仅存本机）
  ↓（轨迹格式交给 M08 参数化；本模块提供"字面量标注"接口：
     录制时可圈选元素/文本 → 标记为候选输入项，降低参数化歧义）
本地回放自检（Replayer）→ 脆弱步骤标记
```

### 3.2 golden 采集与回归

- 采集：认证通过的某次真实运行，录制为 golden（DOM/网络存根，值脱敏）；
- 回归：patch 发布前（M09 §3.5）与自修复回归（M15）执行——mock 网络存根重放比对；
- 相似度：`golden_similarity = 嵌入余弦(结构) ∧ 字段级容差(数值/集合)`；阈值按积木类型标定（标定记录随认证报告存档，初值 TBD 模块细化时定）。

### 3.3 断言执行

```text
test.yaml: assertion: schema        → 输出过 interface.json 校验即通过
          assertion: golden_similarity → TestRunner 相似度 ≥ 阈值
非确定性输出（AI 总结/抓取结果）默认 golden_similarity；确定性输出默认 schema。
```

### 3.4 认证响应脚本

- 声明于 interactions.yaml（confirm 类）或 block.yaml（副作用）；
- M09 沙箱/本机认证时由 ResponseFixtures 执行：confirm 自动应答；副作用自动执行两遍并校验幂等键防重。


## 4. 数据模型

```text
trace/
├── manifest.yaml       # 版本、站点、登录步骤标记、时间敏感步骤声明
├── steps.ndjson        # {seq, action, target_selector, dom_anchor, value?, wait_condition, ts_offset}
├── snapshots/          # 每步 DOM 快照（脱敏后为 golden 素材）
└── network.json        # 请求存根（golden mock 用；值→占位符）

golden/（积木 tests/ 内，不随包分发）
├── run_meta.json       # 环境指纹、采集时间、来源认证 run id
├── expected_steps.ndjson
└── network_stubs.json
```

**接口约定**：轨迹主标识全链路统一为 **`trace_ref`**（M02/M06/M08 一律引用 trace_ref，不得使用其他命名）；本地登记表 `recordings(id, trace_ref, site, created_at, fragile_steps_json)`（架构 §12.3 客户端清单）。`manifest.yaml` 的版本字段为**格式主版本**：Recorder/Replayer 拒绝不兼容主版本，次版本向后兼容（格式变更走四方会签 + 版本协商）。


## 5. 接口

- SDK：`block.load/save/validate()`、`runtime.*` 外观（对接 M05 Capability API）；
- Recorder：`record.start(host) / record.stop() → trace_ref`；`record.annotate(trace_ref, step_seq, element_ref, hint) → annotation`（元素圈选标注 API，M02 消费）；
- Replayer：`replay.run(trace_ref, params, {mode: local|golden|structured}) → step_results`——**确定性回放的唯一入口**（M06 `browser.run_structured` 与 MCP `structured_script_run` 均为本入口在浏览器宿主的封装；M02 干跑调用 `mode=local`）；
- TestRunner：`assert(run_output, test.yaml) → verdict`；
- Linter：`lint(block_dir) → violations[]`（M09/M10 提交入口调用）。


## 6. lint 规则集（静态强制）

| 规则 | 判定 | 后果 |
|---|---|---|
| 禁止裸调用 | AST 禁止 requests/urllib/httpx 直连 | 拒绝 |
| 白名单依赖 | requirements 不在白名单 | 拒绝 |
| 必须生成测试 | tests/ 缺失或断言未声明 | 拒绝 |
| 能力声明一致 | runtime.* 调用 ⊆ capabilities/permissions 声明 | 拒绝 |
| 交互声明一致 | interact.ask 类型 ⊆ interactions.yaml | 拒绝 |
| 发布类必须 confirm | 发布/提交/支付类调用无对应 confirm 声明 | 拒绝 |
| 副作用幂等键 | side_effects=true 且无 idempotency_key | 拒绝 |
| 凭证外传 | credential 句柄出现在网络请求体/URL | 拒绝（一票否决） |
| 超时声明 | adapter 无 timeout_sec | 拒绝 |
| 异常处理 | 未抛 ComponentError 的裸 except | 警告→拒绝（阈值 TBD） |


## 7. 依赖与被依赖

- 依赖：M05（Capability API/出口代理）、M06（Recorder 依附的浏览器会话）。
- 被依赖：M02（录制 UX/干跑）、M06（StructuredRunner 消费轨迹协议）、M08（参数化输入=轨迹+标注）、M09（TestRunner/ResponseFixtures/Replayer 回归）、M10（lint 作为提交门）、M15（golden 回归）。


## 8. 验收标准

1. 轨迹格式 v1 冻结评审通过（M02/M06/M08/M09 会签）；
2. 录制→本地回放自检→脆弱步骤标记，全链路在 3 个种子站点（含 1 个高变更）演示通过；
3. 回放确定性：标准站点同轨迹 10 次重放结果一致（**一致判据**：step_results 逐字段相等；声明的时间敏感步骤按容差；动态内容字段按 golden_similarity 阈值——本判据与 M06 §7.3 共用，不重复验收）；
4. golden 脱敏：上传包检查无原始值（占位符替换验证）；
5. lint 10 条规则全部有正反用例（违规拒绝/合规放行）；
6. 副作用两遍执行幂等验证夹具可用（M09 认证路径联调）。


## 9. 工作量与里程碑（估）

| 里程碑 | 内容 | 估 |
|---|---|---|
| M07-a | block.yaml v2 + SDK + lint 规则集 | 12-18 人日 |
| M07-b | Recorder + 元素圈选标注 + 本地回放自检 | 15-20 人日 |
| M07-c | Replayer 三模式（local/golden/structured）+ TestRunner | 15-20 人日 |
| M07-d | ResponseFixtures + golden 脱敏管道 | 6-10 人日 |

M07-b/c 与 M06-a/b 并行；轨迹格式冻结是 M07-c 开工前置。
