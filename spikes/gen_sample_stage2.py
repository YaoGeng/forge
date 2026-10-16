"""T1.65c 阶段二——预期形状预登记 + 覆盖尝试裁定（不动阶段一任何字段）。

裁定原则（A.10/C6/C14 计划）：
- expected_shape 从**需求语义**登记（不迁就库能力）；仅链式尝试的形状参与执行期结构核对。
- attempt ∈ {chain, uncoverable}：chain = 已注册认证积木可参数化组合（数据必须经
  bindings 派生——需求方给定输入用字面量 params，站点内容不得现场填充）；
  uncoverable = 无法组合，归因 {site_not_covered | capability_missing | needs_genericization}。
- 归因背景（块能力现状，docs/11/13 落地）：站点块为导航可复现性探针（TraceRunner
  无数据输出通道，ChainRunner 上下文不收站点内容）；本地 python 块经 bindings 传数据。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

HERE = pathlib.Path(__file__).resolve().parent
SAMPLE = HERE / "coverage" / "sample.json"

SHAPE_NOTE = "预期形状从需求语义登记，不迁就库能力；执行期结构核对如实判定"

# —— 30 条裁定表（id -> {expected_shape, attempt}）——
ATTEMPTS: dict[str, dict] = {
    # —— 唯一链式尝试：需求方给定输入（杂乱文本），数据经 bindings 派生 ——
    "hn-44955461": {
        "expected_shape": {
            "format": "markdown", "checked": True,
            "must": {"title_row": True, "min_point_rows": 3},
            "note": "杂乱输入整理为结构化文档：标题行 + ≥3 要点行",
        },
        "attempt": {
            "kind": "chain",
            "steps": [
                {"block": "text_clean", "params": {"text": "产品周会备忘; 发布排期  待确认 ; 用户反馈 三类 已归档; 后续 补数据核对; 遗留问题 未定"}},
                {"block": "markdown_export", "bindings": {"rows": "text_clean.text"}, "params": {"out": "messy-report.md"}},
            ],
            "note": "R1 修订：直连接线（text_clean 仅空白归一、保留 ';' 分隔；markdown_export 按 ';' 拆行）——"
                    "标题行=首段、要点=其余行；经 text_digest 的接法会以 ' | ' 合并破坏分隔符契约，弃用",
        },
    },
    # —— uncoverable：归因三类 ——
    "hn-48848819": {"expected_shape": {"format": "report", "checked": False, "note": "仓库活动洞见（PR/贡献者维度）", "want": "PR/贡献者数据聚合报告"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "仓库活动/贡献者深度数据无积木（github 块仅元数据探针且无数据输出）"}},
    "hn-48774008": {"expected_shape": {"format": "alert", "checked": False, "note": "页面变更通知", "want": "目标页变更告警"},
                    "attempt": {"kind": "uncoverable", "category": "needs_genericization", "reason": "目标站点未指明；无通用页面监控块（仅 baidu.com 绑定块）"}},
    "hn-48345189": {"expected_shape": {"format": "digest", "checked": False, "note": "订阅源每日摘要", "want": "订阅内容每日摘要文档"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：YouTube 无积木"}},
    "reddit-1tehwy4": {"expected_shape": {"format": "excel", "checked": False, "note": "网站数据进 Excel", "want": "目标站数据表"},
                       "attempt": {"kind": "uncoverable", "category": "needs_genericization", "reason": "目标站点未指明；无通用目录/表格读取块"}},
    "hn-47389369": {"expected_shape": {"format": "metrics", "checked": False, "note": "监控指标与告警", "want": "站点/API 指标时序+告警"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "指标聚合/告警/存储后端能力无积木（目标站点亦未指明）"}},
    "hn-47306942": {"expected_shape": {"format": "digest", "checked": False, "note": "每日论文筛选摘要", "want": "cs.RO 新文筛选摘要"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：arXiv 无积木"}},
    "hn-47299551": {"expected_shape": {"format": "alert", "checked": False, "note": "竞品页变更通知", "want": "竞品页差异告警"},
                    "attempt": {"kind": "uncoverable", "category": "needs_genericization", "reason": "竞品站点未指明；无通用页面监控块"}},
    "hn-47110844": {"expected_shape": {"format": "table", "checked": False, "note": "供应商价格表（多站点）", "want": "数十个定价页价格聚合"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：数十个 LLM 供应商定价页，无一有积木"}},
    "hn-47072913": {"expected_shape": {"format": "status", "checked": False, "note": "可用性状态页", "want": "宕机告警+状态页"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "可用性探测/告警/状态页能力无积木"}},
    "hn-46968889": {"expected_shape": {"format": "digest", "checked": False, "note": "论文消化助手输出", "want": "论文库整理与摘要"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：arXiv/出版商无积木（另需知识库集成）"}},
    "hn-46935908": {"expected_shape": {"format": "table", "checked": False, "note": "税率表+计算", "want": "各级税率数据与税额计算"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：CRA 税率表数据源无积木"}},
    "hn-46934190": {"expected_shape": {"format": "report", "checked": False, "note": "阵容×曲库匹配清单", "want": "匹配结果列表"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：音乐节阵容站与 Spotify API 无积木"}},
    "hn-46436419": {"expected_shape": {"format": "digest", "checked": False, "note": "HN 每日摘要", "want": "含 ≥3 条帖子标题+链接的摘要文档"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "站点块无数据输出通道（探针仅导航验证，HN 内容无法进入链上下文）——旗舰缺口登记"}},
    "hn-46034257": {"expected_shape": {"format": "excel", "checked": False, "note": "评论导出表", "want": "TikTok 评论结构化表"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：TikTok 无积木"}},
    "hn-45935825": {"expected_shape": {"format": "spreadsheet", "checked": False, "note": "消费/发票表格", "want": "自动记账表"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "数据源能力缺失：邮件/银行接入无积木"}},
    "hn-45491255": {"expected_shape": {"format": "digest", "checked": False, "note": "营销周报", "want": "营销内容每周摘要"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：营销内容源无积木"}},
    "hn-44951198": {"expected_shape": {"format": "alert", "checked": False, "note": "sitemap 变更通知", "want": "sitemap 增删页告警"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "sitemap 解析/站点遍历能力无积木"}},
    "hn-44668970": {"expected_shape": {"format": "table", "checked": False, "note": "交易披露表", "want": "披露交易自动更新表"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：公开披露数据源无积木"}},
    "reddit-1lpaq5i": {"expected_shape": {"format": "excel", "checked": False, "note": "TVL 值进单元格", "want": "DEX TVL 数值进表"},
                       "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：DEX 链上数据源无积木"}},
    "hn-43933727": {"expected_shape": {"format": "alert", "checked": False, "note": "品牌提及告警", "want": "AI 回答中的品牌提及追踪"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：LLM API 多模型查询无积木"}},
    "hn-43852771": {"expected_shape": {"format": "json", "checked": False, "note": "JSON/XML 输出", "want": "表格数据转 JSON/XML 文件"},
                    "attempt": {"kind": "uncoverable", "category": "capability_missing", "reason": "输出格式能力缺失：无 JSON/XML 写出块（仅 excel/csv/markdown）"}},
    "hn-43787586": {"expected_shape": {"format": "report", "checked": False, "note": "SEO 机会报告", "want": "GSC 数据分析报告"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：Google Search Console API（OAuth）无积木"}},
    "reddit-1jcncvx": {"expected_shape": {"format": "spreadsheet", "checked": False, "note": "逐 URL 抽取进表", "want": "24 个 URL 页面数据行"},
                       "attempt": {"kind": "uncoverable", "category": "needs_genericization", "reason": "无通用 URL 读取块（清单逐站抽取需通用化能力）"}},
    "hn-43158425": {"expected_shape": {"format": "dataset", "checked": False, "note": "月度数据集", "want": "Steam 目录月度数据"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：Steam 无积木"}},
    "zapier-47915": {"expected_shape": {"format": "spreadsheet", "checked": False, "note": "博彩数据表", "want": "每日更新的赔率/赛果表"},
                     "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "目标数据站未披露且博彩类法务审慎；无对应积木"}},
    "hn-42768754": {"expected_shape": {"format": "alert", "checked": False, "note": "竞品社媒动态", "want": "竞品帖文变更追踪"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：社媒平台无积木"}},
    "hn-42700687": {"expected_shape": {"format": "table", "checked": False, "note": "比价表", "want": "多店价格对比表"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：电商数据源无积木（计算块有）"}},
    "hn-42400979": {"expected_shape": {"format": "spreadsheet", "checked": False, "note": "网络信息进表格", "want": "检索结果结构化表"},
                    "attempt": {"kind": "uncoverable", "category": "needs_genericization", "reason": "无通用网络信息抓取块（目标站点未指明）"}},
    "hn-41428635": {"expected_shape": {"format": "digest", "checked": False, "note": "每周新闻主旨", "want": "周度新闻要点摘要"},
                    "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖：新闻源（阿拉伯语周报）无积木"}},
}


def main() -> int:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert sample["meta"]["stage"] == 1, "阶段二必须基于已 commit 的阶段一产物"
    ids = [e["id"] for e in sample["entries"]]
    assert set(ATTEMPTS) == set(ids), f"裁定表与样本不一致：缺 {set(ids) - set(ATTEMPTS)} 多 {set(ATTEMPTS) - set(ids)}"
    for e in sample["entries"]:
        a = ATTEMPTS[e["id"]]
        e["expected_shape"] = a["expected_shape"]
        e["attempt"] = a["attempt"]
    sample["meta"]["stage"] = 2
    sample["meta"]["shape_note"] = SHAPE_NOTE
    SAMPLE.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "evidence" / "coverage" / "sample_stage2.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {}
    for e in sample["entries"]:
        k = e["attempt"]["kind"] if e["attempt"]["kind"] == "chain" else f"uncoverable:{e['attempt']['category']}"
        kinds[k] = kinds.get(k, 0) + 1
    print("stage2 written:", kinds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
