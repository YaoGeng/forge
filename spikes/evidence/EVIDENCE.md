# MS-0 验收证据索引（EVIDENCE）

> 计划：`docs/07-MS0执行计划.md`；执行日期：2026-10-14；环境：Windows 11 / Python 3.12.10 / Patchright 1.63.0（Chromium 1243）/ browser-use 0.13.11 / pytest 9.1.1 / openpyxl 3.1.5。

## 验收命令与结果

| 卡 | 验收命令 | 结果 | 证据文件 |
|---|---|---|---|
| T0.0 | `pip install -r requirements.txt` + `patchright install chromium` + imports 自检 | exit 0；`imports ok` | `versions.txt` |
| T0.1a | `python -m pytest spikes/test_browser_link.py -v -s` | **2 passed**，截图 112,420 bytes | `t0.1_patchright.log`（截图不入库） |
| T0.1b | `python spikes/agent_smoke.py spikes/evidence/t0.1_agent_smoke.json` | **exit 0；done=true；置顶标题 "Stephen Hawking has died"；截图 112,385 bytes——结论 A（2026-10-15 补跑）** | `t0.1_agent_smoke.log`、`t0.1_agent_smoke.json`（截图不入库） |
| T0.2a | `python -m pytest spikes/test_site_inspect.py -v` | **6 passed**（含 2 个 live 报告） | `t0.2_site_inspect.log` |
| T0.2b | `python spikes/run_t02_evidence.py` | 双报告落盘，候选齐全 | `t0.2_evidence.log`、`t0.2_front.json`、`t0.2_search.json` |
| T0.3a | `python -m pytest spikes/test_manual_block.py -v` | **1 passed**（Excel 回读校验） | `t0.3_test.log` |
| T0.3b | `python spikes/run_t03_evidence.py` | rows=10，xlsx 5,718 bytes | `t0.3_evidence.log`、`t0.3_report.xlsx`、`t0.3_rows.json` |
| 回归 | `python -m pytest spikes/ -v` | **9 passed / 32.65s** | `full_run.log` |

## MS-0 Gate 判定

**标准（06-里程碑 §1）**：标准站点手工应用产出报告。

**判定：通过（建议）**——T0.1a / T0.2 / T0.3 全部验收命令 PASS 且证据归档；T0.3 产出 10 行 × 5 字段（position/title/url/points/num_comments）的 Excel 报告（hn.algolia.com 搜索 "python"）。T0.1b 未执行（无 LLM Key），属计划内记录型检查，**不阻塞 gate**（结论 C，见下）。

**gate 确认（2026-10-15）：产品负责人已接受 hn.algolia.com 承载「标准站点」的裁定，MS-0 正式关闭**；同日以 OpenCode Zen（step-5-preview-free）补跑 T0.1b，**结论 A 达成**——选型全链（Browser-Use Agent ⇅ Patchright Chromium）成立。

## 结论 C 与发现（对 MS-1 的输入）

1. **结论 A（T0.1b，2026-10-15 补跑达成）**：Browser-Use 0.13.11 Agent（LLM=OpenCode Zen `step-5-preview-free`，OpenAI 兼容协议）驱动 Patchright Chromium 打开 hn.algolia.com 并读出置顶标题，2 步完成。补跑过程沉淀三项工程事实：① OpenCode Go 端点要求每会话稳定头 `x-opencode-session`（缺省 400 MissingSessionID）——**M08/M05 的 ModelRouter/网关适配需支持该头**；② Agent 的文件动作写入 browser-use 虚拟 FS，落不到真实路径——产物一律由脚本侧经 CDP/Patchright 直存；③ Agent 任务收尾即销毁浏览器会话（CDP client 随之失效）——会话内产物要在任务完成时点抓取，或走脚本侧兜底。
2. **live 目标切换**：本机网络（无代理）直连 `news.ycombinator.com` 不可达（curl 000×2），`hn.algolia.com` 可达。全部 live 验收以 hn.algolia.com（HN 官方搜索域、标准站点范畴、无 robots 限制）承载。**M09/M06 阶段 1 若需 HN 主站积木，需具备代理的认证环境**。
3. **选择器资产**：`article.Story` / `.Story_title a` / `.Story_link` / `.Story_meta`，已按结构报告归档并回填 `SELECTORS`；搜索页查询往返慢于首屏水合（观测一次 1.5s 窗扑空），采集需有界等待候选出现（已在 `site_inspect` 落地）。
4. **查询词数据点**：`patchright` 全站仅 5 条结果；`python` 30 条。种子积木选站时注意低频词结果量不足 limit 的风险（T1.60 输入）。
5. **Patchright 组合可用性**：Chromium 1243 直驱 hn.algolia.com 全程无验证码、无风控页（10+ 次访问）；T0.1a 截图正常。Agent 层组合留待结论 A/B 补验。
6. **机器人礼仪实测**：robots.txt 404（无文件）→ 按允许处理；频次上限 5/host/小时在 site_inspect 入口强制。

## 执行裁定与计划偏差清单（gate 确认前必读；详情见执行台账，其要点已并入本节）

1. **live 目标切换**：计划钉死的 `news.ycombinator.com` 在本机网络不可达（无代理，curl 000×2），全部 live 验收由 `hn.algolia.com` 承载（T0.1a/T0.2/T0.3）。后续执行者勿照计划原文的 URL/选择器（`.titleline > a`）重放——现状以本仓库代码为准。
2. **查询词**：T0.3 由 `patchright`（全站 5 条 < limit 10）改 `python`（30 条）。
3. **测试语义等价改写**：`test_hn_front_report` → `test_live_front_report`（断言结构不变）；证据文件名 `t0.2_hn_*.json` → `t0.2_*.json`。
4. **依赖安装事实**：Chromium 经 npmmirror 镜像下载（直连 CDN 挂起）；Python 3.12.10 经 winget 安装，Git Bash 的 `python` 为 WindowsApps 存根需用绝对路径（README 已记）。
5. **最终评审（独立评审员，全新上下文）**：0 Critical / 1 Important / 8 Minor，结论**可合并**。Important（证据脚本可静默归档空候选报告）已修复：`run_t02_evidence.ensure_candidates` 归档门，回归测试 `test_empty_candidates_rejected` RED→GREEN，修复后全量 **11/11 passed**。
6. **缓办 Minor（8 项中 5 项待清理，随 MS-1 处理）**：test_browser_link 重复 `_goto_with_retry` 语义弱化版（应改 import site_inspect 版）；G9 措辞残留两处（browser.py 注释"指纹定制"、本文件历史版"风控页"）及 docs/07 G9 锚应为 01 §16.4；run_t02 逐目标 reset 使频次守卫在证据路径失效；关键校验裸 assert（`python -O` 下失效）；robots 禁止分支无测试。其余 3 项已落实：计划偏差清单与台账要点随本节归档；agent_smoke 失败时误打印"结论 A/B"（T0.1b 补跑首轮即应验）已改为失败打印"结论 X"。

## Spike 裁剪备案

- 「变更频率」稳定性信号未实现（需多点快照，阶段 1 M06-b 范围）；
- robots 匹配取 `User-Agent: *` 组；dom_digest 为整页原文哈希（身份标识，非稳定性度量）；
- 验证码启发式仅三标记（文案/iframe/cf-输入），正式版随 M06 细化。

---

# MS-1A 验收证据索引（Windows 半边）

> 计划：`docs/08-MS1A执行计划.md`；执行日期：2026-10-15；环境：Windows 11 build 26200 / Python 3.12.10 / 零新增依赖。
> 报告：`t1.01_report.md`（M05 §2.3 属性表 L2 行 Windows 列逐项实测）。

## 验收命令与结果

| 卡 | 验收命令 | 结果 | 证据文件 |
|---|---|---|---|
| T1.01-a | `python -m pytest spikes/test_egress_fw.py -v` | 7 passed | `t1.01a_unit.log` |
| T1.01-b | 同上（累计） | 14 passed | `t1.01b_unit.log` |
| T1.01-c | `python spikes/run_t101_windows.py`（管理员） | **exit 0：VP1/VP2/VP4 全部成立，VP3 逐项成立，restored=true，窗口 117s** | `t1.01_windows.log`、`t1.01_restore_check.log` |
| T1.01-c 诊断 | `diag_t101_allow.py` / `diag_t101_allow2.py`（管理员） | 定位 R8（程序放行规则对 venv launcher 镜像不匹配） | `t1.01_diag_allow.log`、`t1.01_diag_allow2.log` |
| T1.01-d | `python -m pytest spikes/ -q` | **29 passed**（MS-0 11 + MS-1A 18） | `t1.01_full.log` |
| T1.02 | macOS PF 规程交付 | **未实测（待 macOS 硬件）**：anchor 规则 + setup/teardown/verify 脚本就绪 | `egress_pf/`（README 有未实测横幅与 runbook） |
| T1.03 | 复核记录写入 05 附录 A.8 | 已写入 | `docs/05-开发计划.md` 附录 A.8 |

## MS-1A Gate 状态

**gate = 双平台报告。Windows 半边完整达成（四验证点实测 + §2.3 L2 行逐项结论 + 不触发回退链）；macOS 半边规程就绪、执行 blocked-on-hardware。** 状态已如实上报产品负责人；MS-1B（组 B/C：SDK 与轨迹）按里程碑图不被 MS-1A 阻塞，可并行开工。

## 执行裁定（R2-R8；R1 编号未使用）

- **R2**：计划 T1.01-b 测试计数笔误（8→7 新增 / 15→14 总数），已随卡内注记更正；
- **R3**：`policy_matches` 测试夹具改用 `snapshot_profiles(CANNED)` 生成完整快照（快照全等语义要求完整 profile 集），计划正文已留注记；
- **R4**：提权进程无管道——驱动自归档 transcript 至 evidence 日志，验收命令不再 `tee`；
- **R5**：`NetSecurity.Action` 枚举被 ConvertTo-Json 序列化为数字（0/2/4）——`snapshot_profiles` 源头 `ToString()` 归一；失败轮留档 `t1.01_windows_run1_serbug.log`；
- **R6**：PowerShell cmdlet 错误默认不置退出码——`_ps` 前置 `$ErrorActionPreference='Stop'` + 放行规则在场校验；生成代码片段内路径一律 posix 斜杠（`\U` unicode 转义事故）；失败轮留档 `t1.01_windows_run2_norule.log`；
- **R7**：本机防火墙阻断签名 = connect() 即时 WSAEACCES(10013)——判定口径「非 connected 即阻断」（对照组策略前实测必为 connected）；窗口加 600s 硬预算看门狗 + 逐样本容错 + 连续 3 采样失败快速失败（第 3 轮窗口曾失控 26 分钟的整改）；
- **R8**：venv launcher 镜像的程序放行规则在 WFP 不匹配（诊断矩阵 v2/v3 定位；同形态规则对基础安装镜像/curl 即时生效，端口-only 放行则放行一切）——sidecar 角色改用基础安装 `pythonw.exe`；**生产部署前提：sidecar 必须运行在平台私有解释器安装的镜像上**（详见 `t1.01_report.md` §4）；
- **R9**：终审 M3 采纳——exit 门加入 `proxy_saw_targets`（M05 §2.1② 的「代理收到原始目标」原仅展示）；计划 Step 8 公式已同步。

## 最终整分支评审（独立评审员，全新上下文，2026-10-15）

复跑验收 29 passed；抽查确认报告 §2 数据与判定 JSON 逐项吻合、恢复核验一致、R5/R6 失败轮与诊断链自洽、无夸大声明。**0 Critical / 4 Important / 7 Minor**，初裁「不可合并」；Important 4 条已全部修复：①生产 runner 加 30s 超时（防 PowerShell 挂起卡死看门狗与恢复路径）；②`_is_blocked` 收紧为三类网络阻断签名（基础设施故障不判阻断）+ VP1 对照组显式校验 `control_ok`；③DNS/UDP-53「实测优于预期」降级为「推定（未设 UDP 探针）」（报告 §3 与 05 附录 A.8 同步），run3 留档补 git 指针；④PF anchor 收窄到代理端口（conf 模板 + setup 注入实际端口）+ PF 启用态回退。Minor 已修 5 项（计划计数 15→18、exit 门 R9、worker 资源 finally 兜底、verify_pf 真实 bind 尝试与 `host@ip` 防呆、setup_pf 端口注入）；缓办 2 项（verify_pf docstring 措辞随 macOS 实测一并校正、proxy stop 在途 task 噪声——spike 可接受）。修复后回归 **29/29 passed**，裁决改判**可合并**。

---

# MS-1C 验收证据索引（SDK+lint）

> 计划：`docs/10-MS1C执行计划.md`；执行日期：2026-10-15；环境：Windows 11 build 26200 / Python 3.12.10（spikes/.venv）/ 零新增依赖（PyYAML 为 D-M1B.1 既有）。
> 交付：`packages/block-sdk`（block.yaml v2 + interactions.yaml 校验器、lint 十规则、ComponentError + runtime 外观桩、合规示例积木 corpus/valid/demo_block）。

## 验收命令与结果

| 卡 | 验收命令 | 结果 |
|---|---|---|
| T1.10 | `spikes/.venv/Scripts/python -m pytest packages/block-sdk/tests/test_block_model.py -q` | **34 passed**（含评审修复轮 6 个复现测试） |
| T1.11 | `spikes/.venv/Scripts/python -m pytest packages/block-sdk/tests/test_lint_rules.py -q` | **34 passed**（十规则逐条正反 + 两轮修复复现测试） |
| T1.12 | `spikes/.venv/Scripts/python -m pytest packages/block-sdk/tests/test_runtime_facade.py -q` | **13 passed** |
| T1.13 | `spikes/.venv/Scripts/python -m pytest packages/block-sdk/tests -q` | **82 passed**（含 test_full_chain_validation；终审修复轮后回归） |

## MS-1C Gate 状态

**gate = lint 十规则正反用例全绿 + 合规示例积木通过全链校验。两条件达成**（每规则 ≥1 正 1 反；demo_block 依次过 validate_block_dir → lint(ok=True, 0 violation) → for_block 构造）。

## 评审与裁定

- 三卡 A4 评审各一轮（code-reviewer 子代理，全新上下文）：T1.10 首轮不通过（1C/3I：adapter 非字符串崩溃、未知键类型混淆、entry 相对路径未实现、恒真断言）→ 修复轮通过；T1.11 首轮不通过（C5 %/format 形态缺失、AnnAssign 别名绕过 R8、lint() 两条异常路径）→ 修复轮通过；T1.12 首轮通过（0 阻断，4 建议项随 T1.13 处理）。
- 具体化裁定 C1-C15 见 `docs/10-MS1C执行计划.md` §3（含 T1.10-T1.12 评审登记的 C3 澄清/C13 网络禁区扩围/C14 PermissionDenied/C15 for_block 签名）。
- 已登记静态局限（M05 运行时兜底）：两层以上别名、动态导入/getattr/lambda 间接不做追踪——M07 §6 防意外口径，出口代理 + PermissionBroker 为运行时主防线。

## 整分支终审（独立评审员，全新上下文，2026-10-15）

复跑验收 77 passed（修复后 82）；Review Focus 五条确认被真实测试钉住；三处口径（capability/credential/interaction）同源核验通过；裁定 C1-C15 与代码逐条比对无冲突；工程纪律干净。**0 Critical / 1 Important / 7 Minor**，初裁「不可合并」。Important 1 条已修复：非 UTF-8 声明文件三条读取路径（validate._resolve / R2 requirements / R3 test.yaml）使 lint() 抛 UnicodeDecodeError——全部短路为 ValidationError/对应 violation（GBK 复现测试 RED→GREEN）。Minor 处置：M-1 R6 误报面走 C8 修订（仅 side_effects=true 生效）已修；M-3 ComponentError 补 __reduce__ 已修；M-5 CAPABILITY_RE 收敛到 FAMILIES 单一来源已修；M-6 README golden 过度声明已改；M-7 工程卫生（conftest 死常量、转发包装、死面、公开面漏列、fail-closed 缺钉）已修；M-2 tests/ 全扫误报面与 M-4 facade 开式 __getattr__ 维持登记（M09/M05 落地时处理）。修复后回归 **82/82 passed**，裁决改判可合并。

---

# MS-1D 录制回放（docs/11，2026-10-16）

## 交付物

`packages/trace`（forge_trace）：Recorder（定案时点快照对齐 + annotate）、`replay.run` 唯一入口（local/golden；structured 显式 NotImplementedError）、回放一致性比较器（exact/tolerant/similarity/mismatch）、golden 采集与值脱敏（`⟦R:n⟧` 占位符、route 匹配键不含值、拒收校验）、golden_similarity 断言与 TestRunner（路径计数广义 Jaccard，C7-R1）、BrowserPort 三面端口 + patchright 真实适配器 + FakeBrowser 不触网单测基建。

## 验收命令与输出

| 卡 | 验收命令 | 结果 |
|---|---|---|
| T1.21a | `spikes/.venv/Scripts/python -m pytest packages/trace/tests/test_selectors.py packages/trace/tests/test_events.py packages/trace/tests/test_store.py -q` | **14 passed**（含自审修复轮 2 个复现测试） |
| T1.21b | `spikes/.venv/Scripts/python -m pytest packages/trace/tests/test_recorder.py -q` | **29 passed**（评审修复轮：快照定案时点、网络尾部收口、假体 keystroke 形态等 5 项 RED→GREEN） |
| T1.22 | `spikes/.venv/Scripts/python -m pytest packages/trace/tests/test_replayer.py packages/trace/tests/test_compare.py -q` | **17 passed**（评审修复轮：比较器前置校验、异常/anchor 分列等 6 项） |
| T1.23 | `spikes/.venv/Scripts/python -m pytest packages/trace/tests/test_golden_redact.py -q` | **14 passed**（评审修复轮：userinfo 剥离、空串放行、first-wins 等多项） |
| T1.24 | `spikes/.venv/Scripts/python -m pytest packages/trace/tests/test_similarity.py packages/trace/tests/test_full_chain_trace.py -q` | **30 passed**（评审两轮：广义 Jaccard、void 即闭、组合判定等） |
| T1.25 全链 | `spikes/.venv/Scripts/python -m pytest packages/trace/tests -q` | **76 passed**（单测全不触网；全仓 196/196） |
| T1.25 gate | `spikes/.venv/Scripts/python spikes/run_ms1d_gate.py --site A|B|C` | **三站点 gate: PASS**（证据：`t1.25_A_example_com.json` / `t1.25_B_hn_algolia_com.json` / `t1.25_C_cn_bing_com.json`） |

## MS-1D Gate 状态

**gate = 3 种子站点（含 1 高变更）录制→回放 10 次一致 + 脱敏后无原始值。两条件达成**：

| 站点 | 等级 | 一致性 | 脆弱步 | 脱敏 |
|---|---|---|---|---|
| A example.com | standard | **exact**（10/10） | 0 | 零泄漏 |
| B hn.algolia.com | medium | **similarity**（10/10） | 0 | 零泄漏 |
| C cn.bing.com | high | **similarity**（10/10，fill+Enter 交互） | 0 | 零泄漏 |

## Gate 实证与裁定登记

- **换站登记（C1 修订 R2，计划预授权）**：baidu.com 改版 AI 对话式首页（经典 #kw/#su 隐藏，fill 不可用；sogou 反爬）→ C 站换 **cn.bing.com**（fill+Enter 交互保留）；B 站亦走 similarity 通道（C6 判据本意：动态内容 digest 必异）。
- **适配器铁律（gate 实证得出，写死在 patchright_browser.py 文档串）**：patchright 屏蔽 add_init_script（每文档 load 后 evaluate 重注入）；**派发处理器内零 playwright 调用**（commit 时点 content() 阻塞到浏览器关闭、binding 内 wait_for_load_state 死锁）；nav 由主线程 _flush_nav 泵出（framenavigated 只登记 pending，重入/同 URL 去重）；SPA pushState 不产生 nav 步（v1 边界）。
- similarity 通道在真实动态站点（B/C）10/10 接住结构相似度 ≥0.85；A 站纯静态 exact。

## 评审与裁定

- 五卡 A4 评审（code-reviewer 子代理，全新上下文）各一轮 + 修复轮：T1.21a 子代理三次派发被平台拦截改自审（2 项修复）；T1.21b（3I+5M+proto 基线缺陷 1，全修）；T1.22（2I+6M，全修）；T1.23（可合入，1 登记项+8M）；T1.24（1C+3I+4M，两轮修复定稿 C7-R1）。
- 基线外修复：packages/proto `_load_login_steps` 重复定义遮蔽 seq≥1 校验（MS-1B 遗留，独立提交 cb58de6）。
- 计划修订：C7-R1（路径计数+广义 Jaccard）、C8-R1（selector/anchor 文本通道豁免登记 + userinfo 剥离 + 空串放行，协同修订随 docs/12 T1.33）、C1-R2（换站 + B 站 similarity 通道）。
- 缓办登记：response body 采集/脱敏上传、mode=structured（M06）、端口 close 面、selector/anchor 文本通道脱敏（C8-R1）、SPA pushState nav。
