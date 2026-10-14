# MS-0 验收证据索引（EVIDENCE）

> 计划：`docs/07-MS0执行计划.md`；执行日期：2026-10-14；环境：Windows 11 / Python 3.12.10 / Patchright 1.63.0（Chromium 1243）/ browser-use 0.13.11 / pytest 9.1.1 / openpyxl 3.1.5。

## 验收命令与结果

| 卡 | 验收命令 | 结果 | 证据文件 |
|---|---|---|---|
| T0.0 | `pip install -r requirements.txt` + `patchright install chromium` + imports 自检 | exit 0；`imports ok` | `versions.txt` |
| T0.1a | `python -m pytest spikes/test_browser_link.py -v -s` | **2 passed**，截图 112,420 bytes | `t0.1_patchright.log`（截图不入库） |
| T0.1b | `python spikes/agent_smoke.py spikes/evidence/t0.1_agent_smoke.json` | exit 3（**SKIP：无 OPENAI_API_KEY**，计划预期路径） | `t0.1_agent_smoke.log` |
| T0.2a | `python -m pytest spikes/test_site_inspect.py -v` | **6 passed**（含 2 个 live 报告） | `t0.2_site_inspect.log` |
| T0.2b | `python spikes/run_t02_evidence.py` | 双报告落盘，候选齐全 | `t0.2_evidence.log`、`t0.2_front.json`、`t0.2_search.json` |
| T0.3a | `python -m pytest spikes/test_manual_block.py -v` | **1 passed**（Excel 回读校验） | `t0.3_test.log` |
| T0.3b | `python spikes/run_t03_evidence.py` | rows=10，xlsx 5,718 bytes | `t0.3_evidence.log`、`t0.3_report.xlsx`、`t0.3_rows.json` |
| 回归 | `python -m pytest spikes/ -v` | **9 passed / 32.65s** | `full_run.log` |

## MS-0 Gate 判定

**标准（06-里程碑 §1）**：标准站点手工应用产出报告。

**判定：通过（建议）**——T0.1a / T0.2 / T0.3 全部验收命令 PASS 且证据归档；T0.3 产出 10 行 × 5 字段（position/title/url/points/num_comments）的 Excel 报告（hn.algolia.com 搜索 "python"）。T0.1b 未执行（无 LLM Key），属计划内记录型检查，**不阻塞 gate**（结论 C，见下）。

待产品负责人对本页确认后，MS-0 正式关闭。

## 结论 C 与发现（对 MS-1 的输入）

1. **结论 C（T0.1b）**：本机无任何云端 LLM Key、无本地 Ollama，Agent 冒烟未执行。带 Key 分支已按 browser-use 0.13.11 API 落码（`browser_use.Agent` + `llm.openai.ChatOpenAI` + `BrowserProfile(executable_path=...)`），首次具备 Key 时验证；登记为 **M06-a 前置验证项**。
2. **live 目标切换**：本机网络（无代理）直连 `news.ycombinator.com` 不可达（curl 000×2），`hn.algolia.com` 可达。全部 live 验收以 hn.algolia.com（HN 官方搜索域、标准站点范畴、无 robots 限制）承载。**M09/M06 阶段 1 若需 HN 主站积木，需具备代理的认证环境**。
3. **选择器资产**：`article.Story` / `.Story_title a` / `.Story_link` / `.Story_meta`，已按结构报告归档并回填 `SELECTORS`；搜索页查询往返慢于首屏水合（观测一次 1.5s 窗扑空），采集需有界等待候选出现（已在 `site_inspect` 落地）。
4. **查询词数据点**：`patchright` 全站仅 5 条结果；`python` 30 条。种子积木选站时注意低频词结果量不足 limit 的风险（T1.60 输入）。
5. **Patchright 组合可用性**：Chromium 1243 直驱 hn.algolia.com 全程无验证码、无风控页（10+ 次访问）；T0.1a 截图正常。Agent 层组合留待结论 A/B 补验。
6. **机器人礼仪实测**：robots.txt 404（无文件）→ 按允许处理；频次上限 5/host/小时在 site_inspect 入口强制。

## Spike 裁剪备案

- 「变更频率」稳定性信号未实现（需多点快照，阶段 1 M06-b 范围）；
- robots 匹配取 `User-Agent: *` 组；dom_digest 为整页原文哈希（身份标识，非稳定性度量）；
- 验证码启发式仅三标记（文案/iframe/cf-输入），正式版随 M06 细化。
