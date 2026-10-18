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

## 整分支终审（独立评审员，全新上下文，2026-10-16）

复跑验收 199 passed（修复后）；Review Focus 五失败面确认被真实测试钉住；G10 唯一入口、裁定 C1-R2/C7-R1/C8-R1 落地核验、适配器派发零 CDP 铁律、脱敏端到端、proto 冻结基线全部通过。**0 Critical / 2 Important / 8 Minor**，初裁「需修改后合入」。Important 2 条已修复（各 RED→GREEN）：①assert_consistent similarity 通道按跑逐比对（原固定取首两跑 html，第 3..N 跑借用判定放行）——test_similarity_channel_checks_each_run/…_per_run_pass；②零标签纯文本页空向量互判 1.0 的漏报——structural_similarity 空侧即 0.0（digest 相同的空页走 exact），test_similarity_rejects_two_distinct_text_only_pages。修复后回归 **199/199**。Minor 8 条全部登记缓办（见下）。裁决改判可合并。

### 终审缓办 Minor 清单（M09/M05/docs-12 消费时处理）

1. validate_golden_no_raw 不查 netloc userinfo（C8-R1 剥离只在 collect 侧）——docs/12 T1.33 服务端同规则落地时一并补
2. tolerance_ms 全豁免（声明步任何差异判 tolerant）——已有 ledger ruling，数值强制随 M07-c golden 模式细化
3. patchright _pending_nav 单槽（快速连续导航少记 nav 步）——v1 边界
4. forge_selector 对 id 无 CSS 转义（非法 selector 误标 fragile）——selectors.py 后续卡
5. RecordingsStore 无 close()（Windows 长驻句柄）——随端口 close 面一并收口
6. _snapshots_at_finalize O(n²)——已有 ledger ruling（T1.21b），超长会话 stop 变慢
7. proto test_trace_types.py:349 死代码行——**已处理**（2026-10-17 等钟清理轮）
8. golden_similarity docstring 措辞 + gate 运行器死 finally——**已处理**（2026-10-17 等钟清理轮；docstring 改广义 Jaccard、run_ms1d_gate 空 finally:pass 移除；session 一项经查在用非死代码，decline）

## MS-1F 种子积木库+自制应用（docs/13，2026-10-16 开工；进行中）

- **T1.60 选站备案**：10 场景 / 10 站点 / 22 块清单（manifest `spikes/seed_blocks/manifest.yaml`，正本 docs/05 附录 A.9）；探活 10/10 全可达（`t1.60_probe.json`）；C4 高变更例外恰 1 块（baidu_home_watch，high 档 best-effort）。
- **T1.61 产线**：`spikes/seedline.py`（manifest 校验/脚手架过 SDK 门/录制幂等+3 次重试/输出快照 golden）——5/5。
- **T1.62 驱动器**：`router_hook`（按 run_id 分发，两 run 两块不串）+ `AdapterRunner`（python 块 local 真执行/golden 输出对拍）+ `cert_batch`（submit 幂等/drive 逐块汇总缺计划 reattach/单块故障不阻塞/register）——apps/server 48/48 + spikes 4/4。
- **T1.62 前置修复（T1.30 遗留缺陷）**：调度计划仅存内存，gate seg2 换进程将空转超时——`plan_json` 落行 + `reattach`（旧行 started_at+n 确定性回退）+ create_app 旧库补列（RED→GREEN；gate 脚本已接 reattach）。
- **T1.63 批次一 seg1 PASS**：6 新块（bing_search/books_list/book_detail/quotes_list/quotes_paged/baidu_home_watch）n=10 pass=10 live=1.0（`t1.63_drive_seg1_batch1.json`）。quotes_paged 首录「点 Next」被推导为文本锚回放全败——换双 goto 重录，旧 run7 台账弃用。
- **T1.63 批次二**：9 本地 python 块（excel/csv/markdown_export、text_digest/clean/stats、price_calc/stats_summary/unit_convert）真实实现+golden 快照；5 公开 API 块经浏览器 trace（裁定：runtime 网络后端为 MS-1C 桩且 lint R1 禁直连——浏览器是阶段 1 唯一合规网络路径）。
- **T1.64a 最小 Registry + chain**：blocks/block_versions/apps/app_versions/block_refs + /apps*（M10 §5 逐字）+ C0 拦截（版本层 422）+ reliability 快照带 N/窗口/C1 标注 + chain N=1 非统计（含 C1 应用拒同步整链）+ ChainRunner 上下文绑定——7/7。
- **T1.64b Creator Center 最小版**：九步会话（自动保存/恢复 ?session=）、副作用规则与 C0 拦截服务端强制、G12 全口径读侧、单文件零依赖 UI（双色系）——7/7 + 冒烟截图 `t1.64b_ui_step1/step7_report.png`。
- **待真实时钟**：批次一 seg2 窗口 2026-10-18T14:25Z 后；批次二 seg1 驱动完成后其 seg2 ≈10-18T15:00Z 后；MS-1E seg2 2026-10-18T05:31Z 后（先行）。seg2 全出 verdict → register 全库 → T1.64c 3-5 应用组装/整链/提审 → 库汇总 gate。

### MS-1F 整分支终审（code-reviewer 子代理，2026-10-16 提前轮）

子代理通道恢复（上会话 reasoning-level-missing），评审范围 463ba81..2767302：**1 Critical + 9 Important + 7 Minor**。修复轮 fea90b3（各 RED→GREEN，291/291）：drive 批次过滤三处贯通（否则 seg2 窗口重叠时错路由 env_error 污染他批真实通过率）、同站点跨 run 5s 限频（site_host 归组）、reattach 旧行 tier 显式传入（medium 不再静默降档 0.90）、副作用自确认拒绝+M02 后置语义、certify 重试复用 App、注册校验 run 归属、版本号唯一、交互步三层一致、book_detail 重录（golden 回归 0.0→1.0，run5 弃用登记）、快照字段收敛 C13。decline 1 项（reliability 端点自 MS-1E 已存在）；minor 6 项缓办（台账）。修复后待 seg2 的 21 run 全部 live=1.0 且 regression=1.0。

## MS-1G 准备段（T1.65a-d，2026-10-16，与 48h 时钟窗口并行）

- **规程**：docs/05 附录 A.10 备案（域内锚定采样框、机械选样零自由度、恰一次整链判定、预期形状预登记、人工可否决）；docs/14 计划（T1.65 拆 5 卡）先于池采集 commit（f0ebbd1）。
- **池**：HN Algolia 12 预登记检索式 556 命中（原始响应归档 raw/）→ 去重 546 → 需求标记机械框出 120 → 逐条裁定 + 第二来源（Zapier/n8n 社区 WebSearch 发现、WebFetch/pullpush 逐条核验 URL/日期/原文）= **136 条（域内 55 / 域外 56 / 排除 25，6 社区）**；快照 pool_snapshot.json。
- **样本**：机械选样 30（posted_at 倒序，选样可复算已钉测试）；两阶段写入（选样+域映射 f 先 commit，预期形状+尝试后 commit）；**1 条链式尝试 + 29 条不可组合归因（站点未覆盖 17 / 能力缺失 7 / 需通用化 5）**。样本构成披露：供给帖 18 / 求助帖 12（R1 登记，人工可否决）。
- **结构性事实（归因依据，评审员独立核验）**：全部站点块 `run()` 仅返回 `{"ok": True}`（导航可复现性探针，TraceRunner 无数据输出通道——「HN 每日摘要」类需求无法把站点内容接入链上下文）；本地 python 块仅 excel/csv/markdown 导出与基础转换（无 JSON/XML、无拆行/结构化块）。该事实主导不可组合归因，T1.65e 报告将按分类呈报。
- **执行器**：coverage_runner TDD 27/27（不触网）——单次运行不重试、未注册块拒绝执行只走产品路径、形状核对严格判定、判定记录携带预登记形状摘要、报告只呈报数据。
- **评审**：code-reviewer 子代理独立复算选样/实跑块代码/比对落盘产物与 git 时序——1C+3I+8M；修复轮 R1（C1 链式尝试改直连接线 + I1 真实选样断言 + I2 构成披露登记 + I3 fetched_at 全量补齐 + pool_ref 全量哈希加强；1 Minor decline 登记）；产物再生成选样 id 逐条不变。

### 时钟日彩排（2026-10-17，ms1e_store 副本，离线）

副本内 block run 强制 verdict=pass 模拟 seg2 完成，真 state/真积木目录/真 trace_refs 预演全链：register 22/22 新块通过（遗留 c1/c2 两键按手册走手动 POST，注册名≠subject 的 422 符合预期）；五应用 5/5 published（C1 登录态报表走 C8-R1：certify 422 证据 + 本机整链恰一次 + 链行设备签名）；覆盖实验 1/30 covered（hn-44955461 rows=5 过形状核对）、未覆盖分类 17/7/5 与样本裁定逐条一致——D-4 呈报预测值（3.3%）就位。彩排产物仅存本地（含 store 副本，golden 边界不进 git）；`spikes/rehearse_clock_day.py` 可重跑。

### 等钟清理轮（2026-10-17，时钟窗口前）

- MS-1F 缓办清理：#11 router_hook 未登记 run 的 env_error 补 `captcha_shortfall` partial flag（verdict 落 partial 不落 below_threshold，与 scheduler_hook 异常路径一致）；#12 reattach 旧回退 reg_ok 改半进位确定性 + partials 从 fail_rows 归因重建——各 RED→GREEN（test_router_unregistered_run_marks_partial_flag / test_reattach_legacy_rounding_is_half_up / test_reattach_legacy_reconstructs_partials_from_fail_rows）。
- #15 Creator UI 全部动态插值加 esc() 转义（需求文本/标题等用户输入面 13 处；onclick 内块名经 dir-safe 校验无引号维持直排）。
- 维持缓办（理由更新）：#14 python⇒site 空是 seedline 有意保留的过渡裁定（「可空或 API 域」，随 M05 网络后端定稿）；#17 chain 失败 verdict 枚举属 M09 API 契约（M10-c 状态机细化时区分）；manifest rows:"[]" golden 改参数会打脱 seg1 golden 对拍，时钟日前不可动。
- 全仓 356/356。

## 时钟日执行（2026-10-18，真实钟）

- **MS-1E seg2 gate PASS（05:31Z 窗开后 08:30Z 执行）**：C2 hn_search_probe N=20（live/regression 双 1.0，verdict pass，窗口 10-16T05:28→10-18T08:32，`t1.35_seg2_c2.json`）；C1 login_demo_probe 第二段签名上传受理（verdict pass、live 1.0、时长下限 60.6s 过、reliability 带 48h+ 窗口与 C1 标注，`t1.35_seg2_c1.json`）。
- **C1 行内 N 口径偏差（如实登记，不回填）**：docs/12 T1.35 期望段二上传后行内 N=20；服务端上传通道实为**替换**语义（`_finalize_report: attached.n = n`），认证行/可靠性视图显示末次受理报告 n=10。N≥20 以两段归档证据计：10-16 段 n=10（53.9s，上传受理 pass）+ 10-18 段 n=10（60.6s，上传受理 pass）= 20 次真实运行跨 ≥51h。seg1 运行明细已被段二报告文件覆盖（服务端仅存末次报告，certify 无本地持久化），不可恢复——任何「补出 n=20」均为伪造，不做。处置：服务端改累加 + 同报告哈希防重（等钟修复卡，见下节），历史行维持 n=10 呈报，人工可否决本读法。
- **等钟修复卡（docs/12 修订 C15，RED→GREEN，358/358）**：`_finalize_report` 受理路径改累计（n/pass_count 累加，通过率与 verdict 按累计重算）+ 新列 `accepted_report_hashes`（旧库幂等补列）防同内容换 nonce 重传重复计数——`test_second_upload_accumulates_n` / `test_replayed_report_hash_with_new_nonce_rejected` 各先 RED 后 GREEN；历史行不回填。

### 时钟日收口（2026-10-18 下午-夜间，编排器 + 人工修复轮）

- **批次 seg2 全绿**：批次一 6 站点块 + 批次二 14 块（5 API trace + 9 python）全部 n=20、live/regression 双 1.0、verdict pass（`t1.63_drive_seg2_batch1/2.json`；b1 首轮 25 分钟预算超时码 124 属编排设计——quotes_paged/book_detail 晚窗由 topup 轮补齐，`clock_day.log` 全程留痕）。register **22/22**（含遗留 hn_search_probe=run1 / login_demo_probe=run2 手动 POST，`t1.63_register.json`）。
- **真实链路径四连缺陷（彩排假执行器未覆盖面，逐一定位+RED/GREEN 修复，登记如下）**：①`real_signer` 传文件路径给 `DeviceKey.load`（收目录）；②`wire_chain_runner` 遗留块 ref 不回退 legacy_state_key（c2/c1）→ KeyError 未知 trace_ref；③wire 缺省分支 `browser_factory=None` 直传 TraceRunner → NoneType 不可调用；④`RecordingsStore` sqlite 连接线程绑定 → FastAPI 请求线程 ProgrammingError（此前所有驱动均主线程）。各挂回归测试（`test_real_signer_loads_key_from_client_keys_dir` / `test_wire_resolves_legacy_trace_ref_keys` / `test_wire_default_branch_uses_real_browser_factory` / `test_store_readable_from_foreign_thread`）。
- **失败尝试孤儿清理（如实登记）**：①②④修复前的三次失败 assemble 在库内留下 draft app/版本/引用与 rejected chain 行（工具 bug 产物、非产品失败）——已删并留库快照 `ms1e_store/server.db.bak-before-junk-cleanup`；全库最终恰 5 应用为真验收口径。
- **T1.64c 五应用 5/5 published**（`t164c_apps.json`）：四 C2 链服务端同步认证 + C1 登录态报表走 C8-R1（certify 422 证据 + 本机整链恰一次 + 链行设备签名 run27）；`GET /apps` 恰 5 条。UI 走查三帧（真实库 22 块、只读导航不新增提审）：`t164c_ui_step1.png` / `step2_catalog.png` / `step7_report.png`——步 7 报告 N/时间窗/非统计值标注齐全（report API 同源核验）。
- **T1.65e 覆盖实验**：30 判定记录恰一次冻结（`coverage/runs/` ×30，重跑 executed=0/resumed=30）；`report.md` 只呈报数据——**覆盖 1/30（3.3%），未覆盖 17/7/5（站点未覆盖/能力缺失/需通用化）**，与彩排预测逐条一致；池快照引用 sha256:d2c0…df964；构成披露供给 18/求助 12。run_coverage 报告回填缺陷（pool_ref 显式 None 压过缺省值）同轮修复。
- **rows-golden 缓办（理由更新）**：manifest `rows:"[]"` golden 改参数将打脱已完成认证的参数口径（N=20 认证绑定录制时参数）——cert 已落库不可再动，该项随种子库重做（D-4 fail 路径）一并处理。
- 全仓 **362/362**。
