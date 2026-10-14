# forge-proto（packages/proto）

Forge 接口冻结清单的类型化定义。当前承载 **轨迹格式 v1**（`docs/03-模块设计/M07-BlockSDK与测试框架.md` §4，D-2 冻结）。

## 内容

| 路径 | 说明 |
|---|---|
| `schema/*.schema.json` | 跨语言契约工件（JSON Schema draft-07 子集：type/enum/required/properties/additionalProperties/items/minItems/minimum/pattern/format:date-time） |
| `python/forge_proto/` | Python 类型（frozen dataclass）+ 手写校验器（stdlib + PyYAML，不引 schema 引擎） |
| `ts/trace.d.ts` | TS 类型；`npm run typecheck` 为类型门（typescript 仅 devDependency） |
| `tests/` | TDD 用例（冻结字段名集合、NDJSON 解析、主版本门、快照一一对应、Schema 对齐） |

## 公开面（Python）

`forge_proto.CURRENT_MAJOR / FormatError / Manifest / Step / TimeSensitiveStep / NetworkEntry / NetworkLog / RunMeta / load_manifest / load_steps / load_network / load_run_meta / is_compatible / validate_trace_dir / validate_golden_dir`

## 消费方与版本纪律

- 消费方：M02（录制/干跑宿主）、M06（StructuredRunner）、M08（参数化）、M09（golden 回归）。
- 主标识全链路统一 `trace_ref`；`manifest.format_version` 为格式主版本，**Recorder/Replayer 拒绝不兼容主版本**（`is_compatible`）。
- **任何格式变更走版本化流程并触发四方适配评审**：破坏性变更走主版本，兼容性增强走次版本（M07 §4 + T-doc.4 对齐裁定）。复核记录：`docs/09-MS1B执行计划.md` 附录 A。

## 表达细节裁定（C1-C7）

M07 §4 未钉死的字段命名与表达细节（manifest 字段名、快照命名 `{seq:06d}.html`、network.json 结构等）钉死在 `docs/09-MS1B执行计划.md` §3，变更同样走上述流程。

## 复跑

```bash
# Python 侧（仓库根；venv 含 PyYAML>=6.0）
spikes/.venv/Scripts/python -m pytest packages/proto/tests -q

# TS 类型门
cd packages/proto/ts && npm install && npx tsc --noEmit -p tsconfig.json
```

依赖登记：D-M1B.1（`docs/09-MS1B执行计划.md` §1）——PyYAML>=6.0（运行时）、typescript>=5（dev-only）。工具链：node v24.6.0 / npm 11.5.1。
