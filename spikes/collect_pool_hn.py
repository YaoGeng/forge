"""T1.65b 需求池采集——HN Algolia 直连（预登记检索式，原始响应归档）。

用法：spikes/.venv/Scripts/python spikes/collect_pool_hn.py
产物：spikes/evidence/coverage/raw/hn_<slug>.json（逐检索式原始响应，含 fetched_at）
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

import httpx

HERE = pathlib.Path(__file__).resolve().parent
RAW_DIR = HERE / "evidence" / "coverage" / "raw"

# 预登记检索式（A.10 备案口径：形状导向，覆盖 10 场景主要族；Tags 固定 Ask HN/故事）
# 数值窗：近 5 年（created_at_i > 2021-01-01），hitsPerPage 50，按相关度（Algolia 默认）
SINCE = 1609459200  # 2021-01-01T00:00:00Z
QUERIES: list[tuple[str, str]] = [
    ("hn_scrape", "scrape"),
    ("hn_scrape_how", "how do you scrape"),
    ("hn_track_changes", "track website changes"),
    ("hn_monitor", "monitor website"),
    ("hn_excel", "export to excel"),
    ("hn_spreadsheet", "spreadsheet automatically"),
    ("hn_digest", "daily digest"),
    ("hn_search_api", "search api"),
    ("hn_github_repo", "github repo"),
    ("hn_pull_data", "pull data from api"),
    ("hn_login", "scrape behind login"),
    ("hn_summarize", "summarize articles"),
]


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = 0
    with httpx.Client(timeout=30) as client:
        for slug, q in QUERIES:
            params = {
                "query": q,
                "tags": "(story,ask_hn)",
                "numericFilters": f"created_at_i>{SINCE}",
                "hitsPerPage": 50,
            }
            r = client.get("https://hn.algolia.com/api/v1/search", params=params)
            r.raise_for_status()
            data = r.json()
            hits = data.get("hits", [])
            total += len(hits)
            out = {
                "query": q,
                "params": params,
                "fetched_at": fetched_at,
                "nbHits": data.get("nbHits"),
                "hits": [
                    {
                        "objectID": h.get("objectID"),
                        "title": h.get("title"),
                        "url": h.get("url"),
                        "author": h.get("author"),
                        "created_at": h.get("created_at"),
                        "points": h.get("points"),
                        "num_comments": h.get("num_comments"),
                        "story_text": (h.get("story_text") or "")[:600],
                    }
                    for h in hits
                ],
            }
            path = RAW_DIR / f"{slug}.json"
            path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{slug}: {len(hits)} hits -> {path.name}")
    print(f"TOTAL {total} raw hits; fetched_at={fetched_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
