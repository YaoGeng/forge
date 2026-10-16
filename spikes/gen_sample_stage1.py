"""T1.65c 阶段一——机械选样落盘（选样记录 + 域映射冻结；不含尝试方案）。

阶段一产物 commit 后，阶段二（预期形状 + 覆盖尝试）才可写入；两阶段分离是
Review Focus 4（域判定先于尝试，时间序可查）的时间戳证据。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from spikes.coverage_runner import SAMPLE_SIZE, load_pool, pool_digest, select_sample  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
POOL = HERE / "coverage" / "pool.json"
OUT = HERE / "coverage" / "sample.json"


def main() -> int:
    pool = load_pool(str(POOL))
    sel = select_sample(pool, SAMPLE_SIZE)
    sample = {
        "meta": {
            "stage": 1,
            "protocol": "docs/05 附录 A.10；docs/14 T1.65c",
            "pool_ref": pool_digest(pool),  # R1 加强：全量条目哈希（内容被改即失配）
            "selection_rule": "in_domain 按 posted_at 字符串降序取前 30；同刻按池序（零自由度）",
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
        "entries": [
            {
                "id": e["id"], "domains": e["domains"], "community": e["community"],
                "title": e["title"], "url": e["url"], "excerpt": e["excerpt"],
                "posted_at": e["posted_at"], "note": e.get("note"),
            }
            for e in sel
        ],
    }
    OUT.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    snap = HERE / "evidence" / "coverage" / "sample_stage1.json"
    snap.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"stage1: {len(sel)} entries; pool_ref={sample['meta']['pool_ref'][:20]}…")
    for e in sel:
        print(f"  {e['id']:16} {e['domains']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
