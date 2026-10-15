# forge_trace — 录制回放包（MS-1D）

M07 §4/§5 的类型化实现：演示录制（Recorder）、确定性回放（`replay.run` 唯一入口）、golden 采集与值脱敏、golden_similarity 断言（TestRunner）。

## 公开面（`forge_trace`）

| 面 | 入口 | 说明 |
|---|---|---|
| 录制 | `Recorder(store, browser_factory).record.start(host) / stop() → trace_ref / annotate(trace_ref, step_seq, element_ref, hint)` | M07 §5 签名逐字；产物过 `validate_trace_dir` 零错误才发 trace_ref |
| 登记 | `RecordingsStore(root)` | sqlite（recordings/annotations）+ `traces/<ref>/` 四件套 + `redaction_maps/` |
| 回放 | `replay.run(trace_ref, params, mode, *, store, browser_factory)` | mode ∈ {local, golden, structured}；structured 显式 NotImplementedError（M06 后续卡） |
| 一致性 | `assert_consistent(runs, manifest, htmls=None) → ConsistencyReport` | exact / tolerant（声明时间敏感步）/ similarity（≥0.85）/ mismatch；duration 永不进判据 |
| golden | `collect_golden(trace_ref, *, store, environment_fingerprint)`、`validate_golden_no_raw(dir)` | 占位符 `⟦R:n⟧`（C8）；mock 匹配键不含值；golden 三件套不随包分发 |
| 断言 | `TestRunner.check(run_output, test_yaml)`、`golden_similarity(a, b)` | assertion ∈ {schema, golden_similarity}；路径计数广义 Jaccard（C7-R1） |
| 参数 | params dict | `str(seq)` 覆盖 input 步值；`q:<name>` 覆盖 nav URL 同名 query 值（仅替换既有键） |

## 消费方

- M02 RecordStudio/DryRunPanel（record.* / replay.run(mode=local)）
- M09 认证（replay.run(mode=golden) 回归唯一入口；docs/12 T1.31 起消费 C8 占位符）
- M06 StructuredRunner（mode=structured 宿主，后续卡）

## 浏览器端口（D-M1D.1 边界）

`BrowserPort`（port.py，三面：录制/回放/golden）是唯一浏览器抽象；patchright 只出现在
`patchright_browser.py`（真实适配器）与 spikes 运行器，单测走 `tests/fake_browser.py`（不触网）。

真实适配器要点（gate 实证，勿回退）：
- patchright 屏蔽 `add_init_script`（反检测）→ 注入脚本在每次主框架 load 后经 evaluate 重注入；
- **任何派发处理器（binding/framenavigated/response）内零 playwright 调用**——commit 时点调
  `page.content()` 会阻塞到浏览器关闭、binding 内 `wait_for_load_state` 会死锁（导航完成事件
  无法进入正在派发的循环）；click/input/scroll 由 JS 随事件自带 outerHTML，nav 由主线程
  `_flush_nav` 泵出（framenavigated 只登记 pending）；
- SPA pushState 导航不产生 load/framenavigated 语义变化 → 不记 nav 步（v1 已知边界）。

## 复跑

```bash
spikes/.venv/Scripts/python -m pytest packages/trace/tests -q          # 76+，不触网
spikes/.venv/Scripts/python spikes/run_ms1d_gate.py --site A|B|C|all   # 三站点触网 gate
```

gate 种子站（docs/11 §3 C1，修订 R2 换站登记）：A=example.com（standard，exact 通道）、
B=hn.algolia.com（medium，similarity 通道）、C=cn.bing.com（high，similarity 通道；
原 baidu.com 改版 AI 首页 fill 不可用，按计划预授权换站）。

## 裁定与缓办

- 表达细节裁定与修订（C1-C11、C7-R1、C8-R1）：`docs/11-MS1D执行计划.md` §3；
- 缓办：response body 采集（golden stub 匹配只用键，不影响）、response body 脱敏上传、
  mode=structured（M06）、端口 close() 面（T1.25 适配器由调用方 close）、
  selector/anchor 文本通道脱敏（C8-R1，随 docs/12 T1.33 协同）。
