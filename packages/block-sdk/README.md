# forge-block-sdk（packages/block-sdk）

Forge 积木 SDK：block.yaml v2 校验器、lint 十规则、ComponentError、runtime 外观桩（M07；Python 双端复用）。

## 内容

| 路径 | 说明 |
|---|---|
| `python/forge_block_sdk/model.py` | block.yaml v2 / interactions.yaml 类型（frozen dataclass）；`FAMILIES`/`has_capability` 为 lint 与 runtime 共用的单一来源 |
| `python/forge_block_sdk/validate.py` | 手写校验器（stdlib + PyYAML，无 schema 引擎）；错误一律 `ValidationError` + 字段路径 |
| `python/forge_block_sdk/rules.py` | lint 十规则纯函数（AST 一层别名跟踪；M07 §6 编码） |
| `python/forge_block_sdk/lint.py` | `lint(block_dir)` 编排：loader 短路 → adapter 门 → 十规则 → 稳定排序 → 阈值判定 |
| `python/forge_block_sdk/errors.py` | `ComponentError`（附录 D 组件可抛三码）+ `PermissionDenied`（Broker 域）+ `BackendNotWired` |
| `python/forge_block_sdk/runtime.py` | runtime 外观桩：M05 §4 十一家族命名空间 + 声明级权限门，门后统一 `BackendNotWired`（M05 sidecar 接线后替换） |
| `python/forge_block_sdk/data/dependency_whitelist.txt` | 依赖白名单 v1 占位空表（M10 Registry 接管后换源） |
| `tests/corpus/valid/demo_block/` | 合规示例积木（全链校验验收交付物） |

## 公开面（Python）

`BlockSpec / PermissionSpec / RuntimeSpec / ReliabilitySpec / InteractionSpec`、`load_block / load_interactions / validate_block_dir / ValidationError`、`lint / LintResult / Violation / LintContext`、`ComponentError / COMPONENT_ERROR_CODES / PermissionDenied / BackendNotWired`、`RuntimeFacade / CredentialHandle / for_block`

## 消费方

- M09/M10：`lint(block_dir)` 为提交前置门（违规拒绝；warning 阈值 v1=0）；
- M02 Creator Center：`validate_block_dir` 结构校验；`for_block` 提供干跑用的 runtime 桩面；
- M05 sidecar 接线后：`BackendNotWired` 调用点替换为真实后端，`PermissionDenied` 映射附录 D `permission_denied`。

## 版本纪律与裁定

字段语义冻结自 `docs/02-技术架构.md` §2.1 与 `docs/03-模块设计/M07`；表达细节裁定 C1-C15 见 `docs/10-MS1C执行计划.md` §3，变更走计划修订登记。**golden 不随积木包分发、幂等键强制等不变量由 lint 静态保证**（M07 §1）。

## 复跑

```bash
# 仓库根（venv 含 PyYAML>=6.0）
spikes/.venv/Scripts/python -m pytest packages/block-sdk/tests -q
```

依赖登记：PyYAML>=6.0（D-M1B.1 既有，无新增依赖）。
