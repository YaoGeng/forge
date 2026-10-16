"""T1.65b 池策展步 1——去重 + 预登记需求标记框出待审清单（机械，零挑选）。

输入：spikes/evidence/coverage/raw/hn_*.json（collect_pool_hn.py 产物）
输出：spikes/evidence/coverage/review_worklist.json（待人工域分类的候选清单）
规则（预登记）：objectID 去重后，title 或 story_text 命中需求标记正则即入待审清单；
# 注： (^ask hn) 分支区分大小写，对 "Ask HN" 标题永不命中（评审 Minor 登记的死分支）；
# 生效标记为下方 (?i:...) 组——已生成的工作清单不受影响，此处仅留档知悉。
             清单按 created_at 倒序。未入清单条目计数留痕（不入池不判域）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

RAW_DIR = pathlib.Path(__file__).resolve().parent / "evidence" / "coverage" / "raw"
OUT = RAW_DIR.parent / "review_worklist.json"

NEED_MARKERS = re.compile(
    r"(^ask hn)|(?i:how do (?:i|you|we)|how can i|how to|best way to|"
    r"is there a (?:tool|way|service)|looking for|any (?:tool|way)|which tool|"
    r"tool (?:for|to)|recommend\w*\s+(?:a |any |the )?(?:tool|way|service)|"
    r"i (?:want|need|would like) to|want to (?:track|scrape|monitor|export|pull|get|build|automate|receive|collect)|"
    r"\bautomat(?:e|ic|ically)\w*)"
)


def main() -> int:
    seen: dict[str, dict] = {}
    queries: dict[str, list[str]] = {}
    for raw in sorted(RAW_DIR.glob("hn_*.json")):
        data = json.loads(raw.read_text(encoding="utf-8"))
        q = data["query"]
        for h in data["hits"]:
            oid = h["objectID"]
            if oid not in seen:
                seen[oid] = {
                    "objectID": oid,
                    "title": h.get("title") or "",
                    "url": h.get("url"),
                    "author": h.get("author"),
                    "created_at": h.get("created_at"),
                    "points": h.get("points"),
                    "num_comments": h.get("num_comments"),
                    "story_text": h.get("story_text") or "",
                    "queries": [],
                }
            seen[oid]["queries"].append(q)
            if q not in queries:
                queries[q] = []
            if oid not in queries[q]:
                queries[q].append(oid)

    unique = list(seen.values())
    worklist = [e for e in unique if NEED_MARKERS.search(e["title"] or "") or NEED_MARKERS.search(e["story_text"] or "")]
    worklist.sort(key=lambda e: e["created_at"] or "", reverse=True)
    out = {
        "raw_unique": len(unique),
        "raw_total": sum(len(v) for v in queries.values()),
        "worklist_size": len(worklist),
        "need_markers": NEED_MARKERS.pattern,
        "entries": worklist,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"unique={len(unique)} worklist={len(worklist)} -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
