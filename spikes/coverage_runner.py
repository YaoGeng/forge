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

KNOWN_DOMAINS = [f"s{i}" for i in range(1, 11)]
SAMPLE_SIZE = 30

_REQUIRED_FIELDS = ("id", "source", "community", "url", "title", "excerpt",
                    "posted_at", "verdict")


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_of(obj) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def load_pool(path: str) -> list[dict]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    entries = data["entries"]
    seen: set[str] = set()
    for e in entries:
        for f in _REQUIRED_FIELDS:
            if f not in e:
                raise ValueError(f"池条目 {e.get('id')} 缺字段 {f}")
        if e["id"] in seen:
            raise ValueError(f"池 id 重复：{e['id']}")
        seen.add(e["id"])
        if e["verdict"] == "in_domain":
            if not e["domains"]:
                raise ValueError(f"in_domain 条目 {e['id']} 缺 domains")
            bad = [d for d in e["domains"] if d not in KNOWN_DOMAINS]
            if bad:
                raise ValueError(f"条目 {e['id']} 含未知场景域 {bad}")
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
    """样本校验：条目必须来自池快照且 domains 与池一致；expected_shape 必填并生成摘要。"""
    data = json.loads(pathlib.Path(sample_path).read_text(encoding="utf-8"))
    pool_by_id = {e["id"]: e for e in load_pool(pool_path)}
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
