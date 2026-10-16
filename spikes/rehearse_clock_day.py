"""时钟日彩排（离线）：ms1e_store 副本上预演 register → 五应用 → 覆盖实验。

- 副本内把全部 block run 强制 verdict=pass（模拟 seg2 完成；只改副本，不动生产库）。
- trace 块用假执行器（不触网）；python 块真执行；真 state.json/真积木目录/真 trace_refs。
- 产出：spikes/evidence/coverage/_rehearsal/ 归档（register/assemble/coverage 三段 JSON）。
彩排通过 = 10-18 当天只剩真实浏览器执行与 UI 走查。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/server", "spikes", "packages/trace/python",
            "packages/proto/python", "packages/block-sdk/python",
            "packages/certifier/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_server.sandbox import RunOutcome  # noqa: E402
from product_path import SEEDS, adapter_kinds, build_server  # noqa: E402
from seedline import load_manifest  # noqa: E402

SRC_STORE = _ROOT / "spikes/evidence/ms1e_store"
REHEARSAL = _ROOT / "spikes/evidence/coverage/_rehearsal"
KINDS = adapter_kinds()


class FakeTraceRunner:
    def run_once(self, ref, params=None, *, mode="local", **kw):
        return RunOutcome(mode=mode, ok=True)


def main() -> int:
    from fastapi.testclient import TestClient

    store = REHEARSAL / "store"
    if store.exists():
        shutil.rmtree(store)
    store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC_STORE, store)

    # ① 模拟 seg2 完成：副本内 block run 全部 verdict=pass
    import sqlite3

    con = sqlite3.connect(store / "server.db")
    cur = con.execute(
        "UPDATE certification_runs SET verdict='pass' WHERE subject_type='block'")
    con.commit()
    print(f"[rehearsal] 副本 block runs → pass：{cur.rowcount} 行")
    con.close()

    manifest = load_manifest(SEEDS / "manifest.yaml")
    state = json.loads((store / "state.json").read_text(encoding="utf-8"))
    run_ids = dict(state.get("run_ids", {}))
    for b in manifest.blocks:
        if b.exists and b.legacy_state_key and b.legacy_state_key in run_ids:
            run_ids[b.name] = run_ids[b.legacy_state_key]
    print(f"[rehearsal] state run_ids 可用块：{len(run_ids)}")

    app = build_server(store)
    client = TestClient(app)

    # ② register 全库（含遗留两块——run_id 走 state 映射）
    registered = {}
    for name, rid in sorted(run_ids.items()):
        r = client.post("/api/v1/registry/blocks", json={
            "name": name, "version": "1.0.0", "certification_run_id": rid,
            "side_effects": False, "domains": []})
        registered[name] = r.status_code
        if r.status_code not in (200, 201):
            print(f"  register FAIL {name}: {r.status_code} {r.text[:120]}")
    ok = [n for n, c in registered.items() if c in (200, 201)]
    print(f"[rehearsal] register：{len(ok)}/{len(registered)}")
    (REHEARSAL / "register.json").write_text(
        json.dumps(registered, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(ok) < 20:
        return 1

    # ③ 五应用（真 state/真积木目录；trace 假执行器）
    from assemble_apps import run_all

    names = [b.name for b in manifest.blocks]
    from product_path import wire_chain_runner

    wire_chain_runner(app, store, names, trace_runner_factory=lambda dirs: FakeTraceRunner())
    signer = (lambda d: b"rehearsal-sig")
    apps_out = run_all(app, client, signer=signer, state_path=REHEARSAL / "t164c_state.json")
    (REHEARSAL / "apps.json").write_text(
        json.dumps(apps_out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[rehearsal] apps published: {apps_out['published']}/5")

    # ④ 覆盖实验（runs 写彩排目录，不污染正式 runs/）
    from run_coverage import run_experiment

    cov = run_experiment(app, client,
                         pool_path=_ROOT / "spikes/coverage/pool.json",
                         sample_path=_ROOT / "spikes/coverage/sample.json",
                         runs_dir=REHEARSAL / "runs",
                         report_path=REHEARSAL / "report.md")
    (REHEARSAL / "coverage_summary.json").write_text(
        json.dumps(cov, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[rehearsal] coverage: covered={cov['covered']}/{cov['denominator']}"
          f" categories={cov['categories']}")
    verdict = "PASS" if (apps_out["published"] == 5 and cov["covered"] >= 1) else "FAIL"
    print(f"[rehearsal] {verdict} → {REHEARSAL}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
