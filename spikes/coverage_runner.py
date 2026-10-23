"""T1.65 覆盖率实验产线（docs/14 / docs/05 附录 A.10）。

- load_pool / select_sample / load_sample：池加载校验、机械选样（A.10 零自由度）、
  样本加载校验（防挑样/防域漂移；样本条目必须逐字段来自已存档池快照）。
- run_one / tally / report：T1.65d 执行器（见下卡追加）。

posted_at 排序约定：字符串降序（ISO 前缀一致时月精度条目排在同月具体日之前，
即视为该月最早——确定性优先，规则已登记于 A.10 选样规则）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

# A.9 R2①：域内锚定场景集 10→8（砍 s2_login_inventory/s10_numeric_calc）
KNOWN_DOMAINS = ["s1", "s3", "s4", "s5", "s6", "s7", "s8", "s9"]
SAMPLE_SIZE = 30

# A.10 R2②：入样排除域（硬校验）——in_domain 条目命中即拒绝入池（策展侧须改判 excluded）。
# 三域口径见 A.9 R2②：社媒平台 / 金融（银行、DEX 链上、博彩）/ OAuth 深凭据（GSC/Spotify/邮箱）。
EXCLUSION_DOMAIN_PATTERNS = {
    "social_media": re.compile(
        r"(?i)youtube|tiktok|instagram|facebook|twitter|社媒|social\s*media"),
    "finance": re.compile(
        r"(?i)\bbanks?\b|银行|\bdex\b|链上|on-chain|博彩|casino|gambling|betting|赌"),
    "oauth_deep_credential": re.compile(
        r"(?i)\bgsc\b|search\s+console|spotify|oauth|深凭据"),
}

_REQUIRED_FIELDS = ("id", "source", "community", "url", "title", "excerpt",
                    "posted_at", "verdict", "fetched_at")


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_of(obj) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def pool_digest(pool_entries: list[dict]) -> str:
    """池快照摘要：全量条目（含裁定字段）规范化哈希——条目内容被改即失配（R1 加强）。"""
    return sha256_of(pool_entries)


def load_pool(path: str) -> list[dict]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    entries = data["entries"]
    seen: set[str] = set()
    for e in entries:
        for f in _REQUIRED_FIELDS:
            if f not in e:
                raise ValueError(f"池条目 {e.get('id')} 缺字段 {f}")
        if not e.get("fetched_at"):
            raise ValueError(f"池条目 {e['id']} fetched_at 为空（A.10 可溯源性：抓取时间必填）")
        if e["id"] in seen:
            raise ValueError(f"池 id 重复：{e['id']}")
        seen.add(e["id"])
        if e["verdict"] == "in_domain":
            if not e["domains"]:
                raise ValueError(f"in_domain 条目 {e['id']} 缺 domains")
            bad = [d for d in e["domains"] if d not in KNOWN_DOMAINS]
            if bad:
                raise ValueError(f"条目 {e['id']} 含未知/已裁撤场景域 {bad}（A.9 R2 场景集恰 8）")
            text = " ".join(str(e.get(k) or "") for k in ("title", "note", "excerpt", "url"))
            for dom, pat in EXCLUSION_DOMAIN_PATTERNS.items():
                if pat.search(text):
                    raise ValueError(
                        f"in_domain 条目 {e['id']} 命中 R2 排除域 {dom}"
                        f"（A.10 R2② 硬校验：排除域条目不得入样，策展侧须改判 excluded）")
            if not e.get("posted_at"):
                raise ValueError(f"in_domain 条目 {e['id']} 缺 posted_at（无法定序入样）")
            if not (e.get("url") and e.get("excerpt")):
                raise ValueError(f"in_domain 条目 {e['id']} 缺 url/excerpt（可溯源性）")
    return entries


def select_sample(pool_entries: list[dict], k: int = SAMPLE_SIZE) -> list[dict]:
    """机械选样（A.10）：in_domain 按 posted_at 字符串降序取前 k；同刻按池序（稳定排序）。"""
    frame = [e for e in pool_entries if e["verdict"] == "in_domain"]
    ordered = sorted(frame, key=lambda e: e["posted_at"], reverse=True)
    return ordered[:k]


def load_sample(sample_path: str, pool_path: str) -> list[dict]:
    """样本校验：条目必须来自池快照且 domains 与池一致；expected_shape 必填并生成摘要。

    meta.pool_ref 必须等于池快照全量摘要（R1 加强：条目内容被改即失配）。
    """
    data = json.loads(pathlib.Path(sample_path).read_text(encoding="utf-8"))
    pool_entries = load_pool(pool_path)
    ref = data.get("meta", {}).get("pool_ref")
    want = pool_digest(pool_entries)
    if ref != want:
        raise ValueError(f"样本 pool_ref {ref} 与池快照摘要 {want} 不一致（池内容或样本引用被改动）")
    pool_by_id = {e["id"]: e for e in pool_entries}
    out: list[dict] = []
    for s in data["entries"]:
        pid = s.get("id")
        if pid not in pool_by_id:
            raise ValueError(f"样本含池外条目：{pid}（选样只能来自已存档池快照）")
        pool_entry = pool_by_id[pid]
        if s.get("domains") != pool_entry["domains"]:
            raise ValueError(
                f"样本 {pid} 的 domains {s.get('domains')} 与池登记 {pool_entry['domains']} 不一致（域判定不可事后改）")
        if "expected_shape" not in s or not s["expected_shape"]:
            raise ValueError(f"样本 {pid} 缺 expected_shape（预期形状必须入样时预登记）")
        att = s.get("attempt")
        if att and att.get("kind") == "uncoverable" and att.get("category") not in UNCOVERABLE_CATEGORIES:
            raise ValueError(f"样本 {pid} uncoverable 归因 {att.get('category')!r} 不在登记分类内")
        entry = dict(pool_entry)
        entry.update({
            "domains": s["domains"],
            "expected_shape": s["expected_shape"],
            "shape_digest": sha256_of(s["expected_shape"]),
        })
        if "attempt" in s:
            entry["attempt"] = s["attempt"]
        out.append(entry)
    return out


# ---------- T1.65d 执行器（单次整链经产品路径；判定记录落盘） ----------

UNCOVERABLE_CATEGORIES = ("site_not_covered", "capability_missing", "needs_genericization")


def check_shape(final_output: dict, must: dict) -> bool:
    """结构化形状核对（C10）：markdown 行数核对（title_row 计 1 行）或
    列表型最小条目数（list_key/min_items——终审 I-1：站点块输出列表不得空计覆盖）。
    严格判定。"""
    if not must:
        return True
    if "list_key" in must:
        items = final_output.get(must["list_key"])
        return isinstance(items, list) and len(items) >= int(must.get("min_items", 1))
    rows = final_output.get("rows")
    if not isinstance(rows, int):
        return False
    need = must.get("min_point_rows", 0)
    if must.get("title_row"):
        need += 1
    return rows >= need


def run_one(entry: dict, execute_chain, *, registry: set[str]) -> dict:
    """单样本判定（恰一次执行，不重试）。execute_chain = ChainRunner.execute 同形可调用。

    verdict ∈ covered | uncovered；uncovered 归因 category ∈
    预登记三类 | registry_missing | run_failed | shape_mismatch。
    """
    attempt = entry["attempt"]
    record = {
        "id": entry["id"],
        "shape_digest": entry["shape_digest"],
        "expected_must": entry["expected_shape"].get("must") or {},
    }
    if attempt["kind"] == "uncoverable":
        record.update(verdict="uncovered", category=attempt["category"],
                      reason=attempt["reason"], ran=False)
        return record

    missing = [st["block"] for st in attempt["steps"] if st["block"] not in registry]
    if missing:
        record.update(verdict="uncovered", category="registry_missing",
                      reason=f"块未注册（覆盖运行只走产品路径，不落产线脚本直跑）：{', '.join(missing)}",
                      ran=False)
        return record

    try:
        result = execute_chain(attempt["steps"])  # 恰一次（C9）
    except Exception as exc:  # noqa: BLE001 —— 单步异常如实归因
        record.update(verdict="uncovered", category="run_failed", ran=True,
                      error=f"{type(exc).__name__}: {exc}")
        return record
    record["ran"] = True
    record["steps_view"] = result.get("steps", [])
    if not result.get("ok"):
        record.update(verdict="uncovered", category="run_failed")
        return record
    final_step = attempt["steps"][-1]["block"]
    final_output = (result.get("context") or {}).get(final_step) or {}
    record["final_output"] = final_output
    if entry["expected_shape"].get("checked") and not check_shape(final_output, record["expected_must"]):
        record.update(verdict="uncovered", category="shape_mismatch",
                      reason="产出不符预登记预期形状（结构核对严格判定，不放宽）")
        return record
    record.update(verdict="covered")
    return record


def tally(records: list[dict]) -> dict:
    n = len(records)
    covered = sum(1 for r in records if r["verdict"] == "covered")
    categories: dict[str, int] = {}
    for r in records:
        if r["verdict"] == "uncovered":
            categories[r["category"]] = categories.get(r["category"], 0) + 1
    return {"denominator": n, "covered": covered,
            "rate": (covered / n) if n else 0.0, "categories": categories}


def write_report(path, records: list[dict], t: dict, *, out_of_domain: dict,
                 sample_meta: dict) -> None:
    """C12 报告：只呈报数据（分母/分子/覆盖率/未覆盖分类/域外旁证/记录索引/复核列）。"""
    lines = [
        "# MS-1G 覆盖率实验报告（T1.65e 产出）",
        "",
        f"- 池快照引用：{sample_meta.get('pool_ref', 'n/a')}；样本量 30（A.4 区间下限）",
        f"- 样本构成披露：供给帖（Show HN 产品动机）{sample_meta.get('supply_side', 'n/a')} 条 / "
        f"求助帖 {sample_meta.get('demand_side', 'n/a')} 条（R1 登记：域内判定按形状不区分供需侧，"
        "供给帖的创作动机计为真实需求表达——人工可否决）",
        f"- 分母 {t['denominator']}｜覆盖 {t['covered']}｜覆盖率 **{t['rate'] * 100:.1f}%**（判定口径：A.4/A.10——单次整链运行产出正确结果即计覆盖）",
        "",
        "## 未覆盖分类（D-4 呈报数据）",
        "",
        "| 归因 | 条数 |",
        "| --- | --- |",
    ]
    for cat, cnt in sorted(t["categories"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {cnt} |")
    lines += [
        "",
        "## 域外旁证（池快照内不入分母的需求分布）",
        "",
        f"- 域外/排除条目总数：{out_of_domain.get('total', 'n/a')}",
    ]
    for label, cnt in out_of_domain.get("top", []):
        lines.append(f"- {label}：{cnt}")
    lines += [
        "",
        "## 判定记录（索引；运行证据见 runs/ 同名文件）",
        "",
        "| id | 判定 | 归因 | 人工复核 |",
        "| --- | --- | --- | --- |",
    ]
    for r in records:
        lines.append(f"| {r['id']} | {r['verdict']} | {r.get('category', '—')} | （留空） |")
    lines += [
        "",
        "> 报告只呈报数据，不写结论行；D-4 判定为人工决策点（A.10 可否决性条款适用于本规程整体）。",
        "",
    ]
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")
