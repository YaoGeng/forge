"""T1.65e 驱动器：覆盖实验执行（Registry → Creator dryrun 产品路径 → 判定记录 → 报告）。

- 每条样本恰一次：runs/<id>.json 落盘即判定冻结——重跑本 CLI 只补缺失记录，绝不重执行
  已判定样本（C9 恰一次语义；重启实验纪元须整目录删除并登记）。
- 链式尝试经产品路径执行：Creator 会话 → 画布 → dryrun（app.state.chain_runner 同一执行器）。
- uncoverable 样本不运行（归因已预登记）。
- 产出：spikes/evidence/coverage/runs/<id>.json × N + report.md（C12 只呈报数据）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/server", "spikes", "packages/trace/python",
            "packages/proto/python", "packages/block-sdk/python",
            "packages/certifier/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from coverage_runner import load_pool, load_sample, run_one, tally, write_report  # noqa: E402

EVIDENCE = _ROOT / "spikes" / "evidence"
COV = _ROOT / "spikes" / "coverage"
RUNS_DIR = EVIDENCE / "coverage" / "runs"
REPORT = EVIDENCE / "coverage" / "report.md"
STORE = EVIDENCE / "ms1e_store"

SUPPLY_PREFIXES = ("Show HN:", "Launch HN:")


def registry_names(client) -> set[str]:
    r = client.get("/api/v1/creator/blocks")
    r.raise_for_status()
    return {b["name"] for b in r.json()}


def execute_chain_via_dryrun(client):
    """链式尝试的产品路径可调用：Creator 会话 → 画布 → dryrun。"""

    def exec_chain(steps: list[dict]) -> dict:
        r = client.post("/api/v1/creator/sessions",
                        json={"requirement_text": "MS-1G 覆盖实验（T1.65e）"})
        sid = r.json()["session_id"]
        rc = client.put(f"/api/v1/creator/sessions/{sid}/canvas",
                        json={"composition": steps})
        if rc.status_code != 200:
            return {"ok": False, "steps": [{"index": 0, "ok": False,
                                            "error": f"canvas {rc.status_code}: {rc.text}"}],
                    "context": {}}
        rd = client.post(f"/api/v1/creator/sessions/{sid}/dryrun")
        if rd.status_code != 200:
            return {"ok": False, "steps": [{"index": 0, "ok": False,
                                            "error": f"dryrun {rd.status_code}: {rd.text}"}],
                    "context": {}}
        return rd.json()

    return exec_chain


def out_of_domain_stats(pool_entries: list[dict]) -> dict:
    reasons = Counter(e.get("reason") or e.get("note") or "未分类"
                      for e in pool_entries if e["verdict"] == "out_of_domain")
    return {"total": sum(1 for e in pool_entries if e["verdict"] in ("out_of_domain", "excluded")),
            "top": reasons.most_common(5)}


def run_experiment(app, client, *, pool_path: Path, sample_path: Path,
                   runs_dir: Path = RUNS_DIR, report_path: Path = REPORT) -> dict:
    runs_dir.mkdir(parents=True, exist_ok=True)
    pool = load_pool(str(pool_path))
    entries = load_sample(str(sample_path), str(pool_path))
    names = registry_names(client)
    exec_chain = execute_chain_via_dryrun(client)

    records: list[dict] = []
    executed = resumed = 0
    for e in entries:
        rec_path = runs_dir / f"{e['id']}.json"
        if rec_path.exists():  # 判定冻结：绝不重执行
            records.append(json.loads(rec_path.read_text(encoding="utf-8")))
            resumed += 1
            continue
        rec = run_one(e, exec_chain, registry=names)
        rec["judged_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        records.append(rec)
        executed += 1
        print(f"  [{e['id']}] {rec['verdict']}"
              + (f" ({rec['category']})" if rec.get("category") else ""), flush=True)

    t = tally(records)
    supply = sum(1 for e in entries if e["title"].startswith(SUPPLY_PREFIXES))
    meta = json.loads(sample_path.read_text(encoding="utf-8"))["meta"]
    write_report(report_path, records, t, out_of_domain=out_of_domain_stats(pool),
                 sample_meta={"pool_ref": meta.get("pool_ref") or "n/a",
                              "supply_side": supply,
                              "demand_side": len(entries) - supply})
    return {"executed": executed, "resumed": resumed, **t, "report": str(report_path)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="覆盖实验执行（前置：全库已 register）。R2 复判（T1.79）：--r2 指向 R2 池/样本")
    parser.add_argument("--store", default=str(STORE))
    parser.add_argument("--r2", action="store_true",
                        help="R2 复判：pool_r2/sample_r2 + 产物落 evidence/coverage_r2/（A.10 R2⑤）")
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from product_path import build_server, wire_chain_runner

    store_dir = Path(args.store)
    app = build_server(store_dir)
    with app.state.session_factory() as s:
        from forge_server.models import Block
        names = [b.name for b in s.query(Block).all()]
    wire_chain_runner(app, store_dir, names)
    client = TestClient(app)
    if args.r2:
        cov_dir = EVIDENCE / "coverage_r2"
        out = run_experiment(app, client,
                             pool_path=COV / "pool_r2.json",
                             sample_path=COV / "sample_r2.json",
                             runs_dir=cov_dir / "runs", report_path=cov_dir / "report.md")
    else:
        out = run_experiment(app, client, pool_path=COV / "pool.json",
                             sample_path=COV / "sample.json")
    print(json.dumps({k: v for k, v in out.items() if k != "categories"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
