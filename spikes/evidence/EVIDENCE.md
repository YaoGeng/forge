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
