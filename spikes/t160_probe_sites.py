"""T1.60 选站探活（docs/13 §5 T1.60 步 5；触网一次，证据归档）。

读 manifest.sites，逐站 GET（浏览器 UA，15s 超时），记录 status/标题/耗时；
可达判据 = 状态码 < 500 且非 404。证据写 spikes/evidence/t1.60_probe.json。
用法：spikes/.venv/Scripts/python spikes/t160_probe_sites.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seedline import load_manifest  # noqa: E402

EVIDENCE = Path(__file__).resolve().parent / "evidence"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def probe(host: str, tier: str) -> dict:
    url = f"https://{host}/"
    t0 = time.monotonic()
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
        title = _TITLE_RE.search(r.text[:20_000])
        return {
            "host": host, "tier": tier, "status": r.status_code,
            "title": (title.group(1).strip()[:80] if title else None),
            "final_url": str(r.url), "ms": int((time.monotonic() - t0) * 1000),
            "reachable": r.status_code < 500 and r.status_code != 404,
            "error": None,
        }
    except Exception as exc:
        return {
            "host": host, "tier": tier, "status": None, "title": None,
            "final_url": None, "ms": int((time.monotonic() - t0) * 1000),
            "reachable": False, "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    manifest = load_manifest(Path(__file__).resolve().parent / "seed_blocks" / "manifest.yaml")
    results = [probe(host, site.tier) for host, site in manifest.sites.items()]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "t1.60_probe.json"
    out.write_text(json.dumps({
        "probed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        mark = "OK " if r["reachable"] else "BAD"
        print(f"[{mark}] {r['host']:<28} tier={r['tier']:<8} status={r['status']} "
              f"ms={r['ms']} title={r['title']!r} err={r['error']}")
    bad = [r["host"] for r in results if not r["reachable"]]
    print(f"{'ALL REACHABLE' if not bad else 'UNREACHABLE: ' + ', '.join(bad)} → {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
