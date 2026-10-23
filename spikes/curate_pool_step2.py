"""池策展步 2——分类裁定落盘（HN 120 条全分类 + 第二来源）。

分类为逐条判定（本文件即判定记录，可审计）；入池/排除理由随条目存档。
规程：docs/05 附录 A.10；域定义：docs/14 C8。
R2（T1.78，A.10 R2②/A.9 R2）：排除域改判 excluded、s2/s10 域清理（裁撤场景），
产物 → pool_r2.json + evidence/coverage/pool_snapshot_r2.json；R1 产物作废留档不删除。
"""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
COV = HERE / "coverage"
RAW = HERE / "evidence" / "coverage" / "raw"
FETCHED_HN = "2026-10-16T16:09:51+00:00"  # collect_pool_hn.py 归档时间
SESSION_FETCHED_AT = "2026-10-16T16:30:00+00:00"  # 第二来源采集会话（WebSearch 发现 + WebFetch/pullpush 核验）

# —— HN 120 条逐条裁定（objectID -> (verdict, domains|None, reason/note)）——
# verdict ∈ in_domain | out_of_domain | excluded
HN_RULINGS: dict[str, tuple[str, list[str] | None, str]] = {
    # in_domain（形状落在 10 场景 ≥1；note 为中文一句话归纳）
    "47306942": ("in_domain", ["s1", "s9"], "arXiv 每日论文筛选摘要"),
    "48848819": ("in_domain", ["s6"], "GitHub 仓库洞见/元数据聚合"),
    "48774008": ("in_domain", ["s7"], "监控网页变更（Visualping 替代）"),
    "48345189": ("excluded", None, "R2 排除域：社媒（YouTube 订阅源）"),
    "47389369": ("in_domain", ["s7"], "网站+API 合成监控"),
    "47299551": ("in_domain", ["s7"], "竞品网站变更自动监控"),
    "47110844": ("in_domain", ["s7"], "追踪 LLM 供应商价格页变动"),
    "47072913": ("in_domain", ["s7"], "可用性监控与状态页"),
    "46968889": ("in_domain", ["s9"], "研究论文消化/汇总助手"),
    "46935908": ("in_domain", ["s5"], "税率表数据获取（s10 裁撤，A.9 R2）"),
    "46934190": ("in_domain", ["s3", "s5"], "音乐节阵容对曲库匹配"),
    "46436419": ("in_domain", ["s1", "s9"], "HN 每日摘要（原工具失效）"),
    "46034257": ("excluded", None, "R2 排除域：社媒（TikTok）"),
    "45935825": ("excluded", None, "R2 排除域：金融（银行/账单邮件数据源）"),
    "45491255": ("in_domain", ["s1", "s9"], "营销内容周报摘要"),
    "44955461": ("in_domain", ["s9", "s8"], "杂乱输入整理成报告/文档"),
    "44951198": ("in_domain", ["s7"], "sitemap 变更监控"),
    "44668970": ("in_domain", ["s5", "s7"], "公开披露交易数据自动追踪"),
    "43933727": ("in_domain", ["s1", "s7"], "追踪 AI 模型对品牌的回答"),
    "43852771": ("in_domain", ["s8"], "CSV/XLSX 转 JSON/XML"),
    "43787586": ("excluded", None, "R2 排除域：OAuth 深凭据（GSC）"),
    "43158425": ("in_domain", ["s3", "s7"], "Steam 数据月度抓取"),
    "42768754": ("excluded", None, "R2 排除域：社媒（竞品社媒动态）"),
    "42700687": ("in_domain", ["s3"], "硬件价格对比（s10 裁撤余 s3）"),
    "42400979": ("in_domain", ["s1", "s3", "s8"], "网络信息自动整理进表格"),
    "41428635": ("in_domain", ["s1", "s9"], "每周新闻主旨识别"),
    "41057815": ("in_domain", ["s5"], "REST API 数据自动抽取"),
    "41057356": ("in_domain", ["s9"], "网页文章摘要"),
    "40524772": ("in_domain", ["s7"], "网站可用性监控"),
    "40512113": ("in_domain", ["s5"], "按 OpenAPI 自动抽 API 数据"),
    "40233096": ("in_domain", ["s3", "s8"], "HN 月度招聘帖进表格"),
    "40046670": ("in_domain", ["s7"], "网站/邮件文案变更追踪"),
    "38828739": ("in_domain", ["s6"], "论文关联 GitHub 仓库数据集"),
    "38635695": ("in_domain", ["s3"], "商品目录抓取建搜索"),
    "38191609": ("in_domain", ["s7"], "可用性监控"),
    "37421818": ("in_domain", ["s7"], "竞品自动追踪"),
    "37418853": ("in_domain", ["s7"], "竞品自动追踪（同人重发）"),
    "37064152": ("in_domain", ["s7"], "服务条款变更通知"),
    "35197795": ("in_domain", ["s7"], "网站监控"),
    "34461064": ("excluded", None, "R2 排除域：OAuth 深凭据（GSC API——终审 I-2，证据在 excerpt）"),
    "33622363": ("in_domain", ["s7"], "网页变更监控+全站爬取"),
    "32090795": ("in_domain", ["s8"], "数据库数据定时进表格邮件"),
    "30699237": ("out_of_domain", None, "登录域读取——s2 裁撤（A.9 R2①：登录类域内命中 0）"),
    "27945573": ("in_domain", ["s3"], "电视订阅价格聚合（s10 裁撤余 s3）"),
    "26740888": ("in_domain", ["s7"], "网站监控服务"),
    # out_of_domain（有表达但形状不在 10 场景 / 供给侧产品无需求表达）
    "49785956": ("out_of_domain", None, "管理工具（1-on-1 会议）"),
    "49460258": ("out_of_domain", None, "站点防护（反爬）"),
    "49242140": ("out_of_domain", None, "健身计算器产品"),
    "47996123": ("out_of_domain", None, "建站工具"),
    "47863906": ("out_of_domain", None, "搜索 API 基础设施（供给侧）"),
    "46959655": ("out_of_domain", None, "开发工具（MCP 替代协议）"),
    "47702476": ("out_of_domain", None, "Excel 内 JS 开发工具"),
    "47561819": ("out_of_domain", None, "站点防护（反爬陷阱）"),
    "47218707": ("out_of_domain", None, "PDF 表单填充（形状外）"),
    "47207790": ("out_of_domain", None, "浏览器会话开发工具"),
    "46780122": ("out_of_domain", None, "选题调研工具"),
    "46649223": ("out_of_domain", None, "编程语言项目"),
    "46322924": ("out_of_domain", None, "营销外联工具"),
    "46088109": ("out_of_domain", None, "自建查询语言（造软件非数据任务）"),
    "45704171": ("out_of_domain", None, "邮件/支付通用自动化产品"),
    "45534790": ("out_of_domain", None, "记账报税产品（表单填充为主）"),
    "45168186": ("out_of_domain", None, "跨工具通用助理产品"),
    "44497573": ("out_of_domain", None, "招聘板产品"),
    "44457069": ("out_of_domain", None, "浏览器游戏"),
    "44445222": ("out_of_domain", None, "PDF 解析（形状外）"),
    "44178202": ("out_of_domain", None, "PDF 批注导出（形状外）"),
    "44160055": ("out_of_domain", None, "BI 平台"),
    "43887439": ("out_of_domain", None, "安全网关产品"),
    "43803786": ("out_of_domain", None, "音乐服务修复工具"),
    "43705065": ("out_of_domain", None, "行业合规产品"),
    "43573539": ("out_of_domain", None, "开发工具（MCP 服务器）"),
    "42814930": ("out_of_domain", None, "日志产品"),
    "42750917": ("out_of_domain", None, "电子表格引擎技术演示"),
    "42498550": ("out_of_domain", None, "健康工具（化验单图像/解析）"),
    "42480173": ("out_of_domain", None, "消费类膳食规划产品"),
    "42319315": ("out_of_domain", None, "政府事务行业产品"),
    "42300085": ("out_of_domain", None, "文本转信息图（可视化形状外）"),
    "41876083": ("out_of_domain", None, "内容展示（USDT 排行）"),
    "41590682": ("out_of_domain", None, "AI 表格产品"),
    "41514823": ("out_of_domain", None, "开发工具（分析埋点文档）"),
    "41503251": ("out_of_domain", None, "数据库前端"),
    "41433486": ("out_of_domain", None, "邮件解析（形状外）"),
    "41183666": ("out_of_domain", None, "静态站生成器"),
    "40295445": ("out_of_domain", None, "无代码应用平台"),
    "39821192": ("out_of_domain", None, "BI 产品"),
    "39666865": ("out_of_domain", None, "数据库产品"),
    "38866739": ("out_of_domain", None, "电商代理产品"),
    "37238648": ("out_of_domain", None, "LLM 评估产品"),
    "37048910": ("out_of_domain", None, "知识管理产品"),
    "37045493": ("out_of_domain", None, "知识管理产品（重发）"),
    "36449206": ("out_of_domain", None, "系统搭建咨询"),
    "33359870": ("out_of_domain", None, "数据集成产品（供给侧）"),
    "32778311": ("out_of_domain", None, "付费墙检测工具"),
    "32661398": ("out_of_domain", None, "硬件设计咨询"),
    "32136715": ("out_of_domain", None, "定价本地化商业咨询"),
    "32003215": ("out_of_domain", None, "搜索引擎产品"),
    "31540557": ("out_of_domain", None, "个人记录管理（非网页数据获取）"),
    "30675357": ("out_of_domain", None, "CI 截图模板（截图产物形状外）"),
    "30514190": ("out_of_domain", None, "客户 onboarding 产品"),
    "33491446": ("out_of_domain", None, "自建 Copilot 开发讨论"),
    "26037816": ("out_of_domain", None, "文本片段效率工具"),
    # excluded（C3 排除类：法务/原生载体/纯咨询/无具体需求/非需求帖）
    "49930872": ("excluded", None, "资讯报道非需求帖"),
    "47651305": ("excluded", None, "讨论帖无具体需求"),
    "46851238": ("excluded", None, "无具体需求（未指明数据任务）"),
    "46517126": ("excluded", None, "需求不具体（无目标数据源）"),
    "46076878": ("excluded", None, "经营分享非需求帖"),
    "46070908": ("excluded", None, "需原生 App（macOS WiFi）"),
    "45949988": ("excluded", None, "营销内容"),
    "45608356": ("excluded", None, "需原生 App（iOS）"),
    "45519796": ("excluded", None, "讨论帖"),
    "42242263": ("excluded", None, "讨论帖"),
    "40776324": ("excluded", None, "讨论帖（法务文本信任）"),
    "40176738": ("excluded", None, "教程非需求"),
    "37939983": ("excluded", None, "营销内容"),
    "37514280": ("excluded", None, "讨论帖"),
    "37021301": ("excluded", None, "需求绑死 iOS 原生载体"),
    "36860974": ("excluded", None, "纯咨询/教学无具体需求"),
    "35053214": ("excluded", None, "求推广建议非数据需求"),
    "29430520": ("excluded", None, "营销内容"),
    "29060272": ("excluded", None, "绕过反爬（法务排除）"),
}

# —— 第二来源（WebSearch 发现 + WebFetch/pullpush 核验；日期来源随条目注明）——
SECOND_SOURCE: list[dict] = [
    {"id": "zapier-47915", "source": "websearch", "community": "Zapier Community",
     "url": "https://community.zapier.com/how-do-i-3/scraping-data-from-a-website-and-writing-them-down-47915",
     "title": "Scraping data from a website and writing them down",
     "excerpt": "I simply need to read (get) the data and write them down into Spreadsheet.",
     "posted_at": "2025-02", "posted_at_precision": "month（WebFetch 页面核实）",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebFetch 核验）",
     "verdict": "excluded", "domains": None, "note": "R2 排除域：博彩（R1 审计：目标站博彩类法务审慎）"},
    {"id": "zapier-38394", "source": "websearch", "community": "Zapier Community",
     "url": "https://community.zapier.com/troubleshooting-99/how-do-i-import-data-from-a-web-table-into-google-sheets-38394",
     "title": "How do I import data from a web table into Google Sheets?",
     "excerpt": "User troubleshooting scraping an HTML table and populating a Google Sheet using line items.",
     "posted_at": "2024-05", "posted_at_precision": "month（搜索快照）",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebSearch 快照）",
     "verdict": "in_domain", "domains": ["s3", "s8"], "note": "网页表格导入 Google Sheets"},
    {"id": "zapier-25931", "source": "websearch", "community": "Zapier Community",
     "url": "https://community.zapier.com/how-do-i-3/how-to-create-a-zap-that-extracts-data-from-google-sheets-and-uses-browse-ai-to-scrape-the-data-weekly-25931",
     "title": "How to create a Zap that extracts data from Google Sheets and uses Browse AI to scrape the data weekly",
     "excerpt": "Using Browse.ai with URLs stored in a spreadsheet, run on a weekly schedule.",
     "posted_at": "2023-07", "posted_at_precision": "month（搜索快照）",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebSearch 快照）",
     "verdict": "in_domain", "domains": ["s7", "s3"], "note": "URL 清单每周定时抓取"},
    {"id": "zapier-152", "source": "websearch", "community": "Zapier Community",
     "url": "https://community.zapier.com/how-do-i-3/does-anyone-know-of-any-other-smart-ways-to-scrape-data-from-websites-152",
     "title": "Does anyone know of any other smart ways to scrape data from websites",
     "excerpt": "Community thread discussing tools like Apify, ParseHub, and Import.io.",
     "posted_at": None, "posted_at_precision": "未核实",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebSearch 快照）",
     "verdict": "excluded", "domains": None, "note": "纯咨询无具体任务"},
    {"id": "n8n-16881", "source": "websearch", "community": "n8n community",
     "url": "https://community.n8n.io/t/how-to-format-web-scraped-data-to-google-sheets/16881",
     "title": "How to format web scraped data to google sheets?",
     "excerpt": "Go to that program's page · Extract the HTML of the program's information · Create a sheet for the program...",
     "posted_at": "2022-08", "posted_at_precision": "month（搜索快照）",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebSearch 快照）",
     "verdict": "in_domain", "domains": ["s3", "s8"], "note": "节目页信息抽取建表"},
    {"id": "n8n-216043", "source": "websearch", "community": "n8n community",
     "url": "https://community.n8n.io/t/build-smarter-workflows-write-and-read-data-from-google-sheets-in-n8n/216043",
     "title": "Write and Read Data from Google Sheets in n8n",
     "excerpt": "Community tutorial on using Google Sheets as a database in workflows (Nov 2025).",
     "posted_at": "2025-11", "posted_at_precision": "month（搜索快照）",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebSearch 快照）",
     "verdict": "excluded", "domains": None, "note": "教程非需求"},
    {"id": "n8n-312871", "source": "websearch", "community": "n8n community",
     "url": "https://community.n8n.io/t/for-hire-python-n8n-automation-apis-excel-google-sheets-web-scraping-workflow-fixes/312871",
     "title": "For Hire: Python + n8n Automation (APIs, Excel/Google Sheets, Web Scraping)",
     "excerpt": "Freelancer offering workflow creation, scraping, and Excel/Google Sheets help.",
     "posted_at": None, "posted_at_precision": "未核实",
     "fetched_at": SESSION_FETCHED_AT, "fetched_at_precision": "采集会话（WebSearch 快照）",
     "verdict": "excluded", "domains": None, "note": "招聘广告"},
]
# Reddit 条目从 pullpush 归档生成（日期+selftext 已核验）
REDDIT_RULINGS: dict[str, tuple[str, list[str] | None, str]] = {
    "1tehwy4": ("in_domain", ["s3", "s8"], "大量网站数据复制进 Excel"),
    "1lpaq5i": ("excluded", None, "R2 排除域：金融（DEX 链上）"),
    "1jcncvx": ("in_domain", ["s3", "s8"], "URL 清单逐页抽取建 Google Sheet"),
    "1bkqbp2": ("in_domain", ["s3", "s8"], "公司内网通讯录抽进 Excel"),
    "isiu8b": ("in_domain", ["s3", "s8"], "书目评分多站更新进表格"),
    "al7mbr": ("in_domain", ["s1", "s3", "s8"], "名单进站点搜索取结果进 Excel"),
}


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:240]


def main() -> int:
    worklist = json.loads((RAW.parent / "review_worklist.json").read_text(encoding="utf-8"))
    entries: list[dict] = []

    wl_ids = {e["objectID"] for e in worklist["entries"]}
    extra = set(HN_RULINGS) - wl_ids
    if extra:
        raise SystemExit(f"裁定表存在工作清单外的键（objectID 敲错）：{sorted(extra)}")
    for e in worklist["entries"]:
        oid = e["objectID"]
        if oid not in HN_RULINGS:
            raise SystemExit(f"缺裁定：HN {oid}（{e['title'][:50]}）——必须逐条裁定")
        verdict, domains, reason = HN_RULINGS[oid]
        # 标题兜底：原帖无正文（story_text 空）时标题即原文（A.10 R1 登记：excerpt=标题是可溯源自身，非注记）
        excerpt = _clean(e.get("story_text") or "") or e["title"]
        entries.append({
            "id": f"hn-{oid}", "source": "hn_algolia_api", "community": "Hacker News",
            "url": f"https://news.ycombinator.com/item?id={oid}",
            "title": e["title"], "excerpt": excerpt,
            "posted_at": e["created_at"], "posted_at_precision": "second（Algolia API）",
            "fetched_at": FETCHED_HN,
            "verdict": verdict, "domains": domains,
            "reason": reason, "note": reason,
        })

    entries.extend(SECOND_SOURCE)

    reddit = json.loads((RAW / "reddit_pullpush.json").read_text(encoding="utf-8"))
    for e in reddit["entries"]:
        rid = e["id"]
        if rid not in REDDIT_RULINGS:
            raise SystemExit(f"缺裁定：reddit {rid}")
        verdict, domains, note = REDDIT_RULINGS[rid]
        entries.append({
            "id": f"reddit-{rid}", "source": "pullpush_api", "community": f"r/{e['subreddit']}",
            "url": e["permalink"], "title": e["title"],
            "excerpt": _clean(e.get("selftext") or "") or e["title"],
            "posted_at": e["created_iso"], "posted_at_precision": "second（pullpush API）",
            "fetched_at": reddit["fetched_at"],
            "verdict": verdict, "domains": domains, "reason": note, "note": note,
        })

    # 广告楼/教程等搜索副产物（记录在案但不入池）
    for sid, comm, url, title, reason in [
        ("reddit-1w3zpdi", "r/webscraping", "https://www.reddit.com/r/webscraping/comments/1w3zpdi/monthly_selfpromotion_september_2026/", "Monthly Self-Promotion - September 2026", "广告楼"),
        ("reddit-1s98m56", "r/webscraping", "https://www.reddit.com/r/webscraping/comments/1s98m56/monthly_selfpromotion_april_2026/", "Monthly Self-Promotion - April 2026", "广告楼"),
        ("hasdata-blog", "外部博客", "https://hasdata.com/blog/zapier-web-scraper", "How to Build a Zapier Web Scraper Without Code", "教程非需求"),
    ]:
        entries.append({"id": sid, "source": "websearch", "community": comm, "url": url,
                        "title": title, "excerpt": title, "posted_at": None, "posted_at_precision": "未核实",
                        "fetched_at": SESSION_FETCHED_AT, "verdict": "excluded", "domains": None, "reason": reason, "note": reason})

    in_dom = [e for e in entries if e["verdict"] == "in_domain"]
    out_dom = [e for e in entries if e["verdict"] == "out_of_domain"]
    excl = [e for e in entries if e["verdict"] == "excluded"]
    communities = sorted({e["community"] for e in in_dom})
    pool = {
        "meta": {
            "protocol": "docs/05 附录 A.10（R2 修订：A.9 R2 8 场景锚定 + 排除域硬校验）",
            "domain_defs": "docs/14 C8（R2：场景集 8，A.9 R2①）",
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "counts": {"total": len(entries), "in_domain": len(in_dom),
                       "out_of_domain": len(out_dom), "excluded": len(excl)},
            "in_domain_communities": communities,
            "hn_worklist": {"raw_unique": worklist["raw_unique"], "worklist": worklist["worklist_size"],
                            "need_markers": worklist["need_markers"]},
        },
        "entries": entries,
    }
    COV.mkdir(parents=True, exist_ok=True)
    (COV / "pool_r2.json").write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    snap = HERE / "evidence" / "coverage" / "pool_snapshot_r2.json"
    snap.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pool: total={len(entries)} in={len(in_dom)} out={len(out_dom)} excluded={len(excl)}")
    print(f"communities(in_domain): {communities}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
