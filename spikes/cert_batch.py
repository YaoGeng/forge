"""MS-1F 认证批次驱动器（docs/13 §5 T1.62；触网驱动，单测离线注入假件）。

CLI（幂等，可重复至成功）：
  submit [--batch N]                 # 为新块创建认证 run（exists 块跳过；state 记 run_ids）
  drive --segment N                  # tick 驱动至全块 n=10*N（reattach 跨进程重建；逐块汇总）
  status                             # 全库状态（含 MS-1E 遗留两块）

G8：seed 库单一 SQLite = spikes/evidence/ms1e_store（与 MS-1E gate 同库同 state.json）。
裁定（台账）：唯一 C1 块 login_demo_probe 即 MS-1E 遗留，由 run_ms1e_gate.py 驱动；
本驱动器只管 C2。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in (
    "packages/trace/python",
    "packages/proto/python",
    "packages/block-sdk/python",
    "packages/certifier/python",
    "apps/server",
    "spikes",
):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_server.etiquette import SEGMENT_RUNS  # noqa: E402
from forge_server.models import CertificationRun  # noqa: E402
from forge_server.sandbox import AdapterRunner, TraceRunner, router_hook  # noqa: E402
from forge_server.scheduler import WallClock  # noqa: E402

from seedline import load_manifest  # noqa: E402

EVIDENCE = _ROOT / "spikes" / "evidence"
STORE = EVIDENCE / "ms1e_store"
SEEDS = _ROOT / "spikes" / "seed_blocks"
DRIVE_TIMEOUT_S = 60 * 90  # 单段驱动上限（20 块 × 真实运行 + 限频余量）


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state(store_dir: Path) -> dict:
    p = Path(store_dir) / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_state(store_dir: Path, state: dict) -> None:
    Path(store_dir).mkdir(parents=True, exist_ok=True)
    (Path(store_dir) / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def c2_new_blocks(manifest, *, batch: int | None = None):
    return [b for b in manifest.blocks
            if b.level == "C2" and not b.exists
            and (batch is None or b.batch == batch)]


def tier_of(manifest, entry) -> str:
    return manifest.sites[entry.site].tier if entry.site else "standard"


def submit(store_dir: Path, manifest, *, batch: int | None, client) -> dict:
    """幂等提交：state 已有 run_id 的块跳过；exists 块不提交（遗留认证计入）。"""
    state = load_state(store_dir)
    run_ids = state.setdefault("run_ids", {})
    changed = False
    for b in c2_new_blocks(manifest, batch=batch):
        if b.name in run_ids:
            continue
        r = client.post(
            "/api/v1/certifications",
            json={"subject_type": "block", "subject_id": b.name,
                  "version": "1.0.0", "level": "C2", "site_tier": tier_of(manifest, b)},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"提交失败 {b.name}: {r.status_code} {r.text}")
        run_ids[b.name] = r.json()["run_id"]
        changed = True
        print(f"  [submit] {b.name} → run_id={run_ids[b.name]}", flush=True)
    if changed:
        save_state(store_dir, state)
    return {b.name: run_ids[b.name] for b in c2_new_blocks(manifest, batch=batch)}


def build_routes(store_dir: Path, manifest, *, batch: int | None = None,
                 browser_factory=None):
    """真实路由：trace 块共用 TraceRunner（state trace_refs → 积木目录），python 块 AdapterRunner。"""
    from forge_trace import RecordingsStore
    from forge_trace.patchright_browser import PatchrightBrowser

    store = RecordingsStore(Path(store_dir))
    factory = browser_factory or PatchrightBrowser
    trace_dirs, routes = {}, {}
    state = load_state(store_dir)
    run_ids = state.get("run_ids", {})
    refs = state.get("trace_refs", {})
    py_dirs = {}
    for b in c2_new_blocks(manifest, batch=batch):
        rid = run_ids.get(b.name)
        if rid is None:
            continue
        if b.adapter == "trace":
            ref = refs.get(b.name)
            trace_dirs[ref] = SEEDS / b.name
            routes[rid] = ("trace", ref, dict(b.params))
        else:
            py_dirs[b.name] = SEEDS / b.name
            routes[rid] = ("python", b.name, dict(b.params))
    trace_runner = TraceRunner(store, factory, block_dirs=trace_dirs) if trace_dirs else None
    adapter_runner = AdapterRunner(py_dirs) if py_dirs else None
    resolved = {}
    for rid, (kind, ref, params) in routes.items():
        runner = trace_runner if kind == "trace" else adapter_runner
        resolved[rid] = (runner, ref, params)
    return resolved


def drive(store_dir: Path, manifest, segment: int, *, app, routes: dict,
          poll_s: float = 2.0, timeout_s: float = DRIVE_TIMEOUT_S) -> dict:
    """tick 驱动至全块 n=SEGMENT_RUNS*segment；缺计划先 reattach；逐块汇总。"""
    sched = app.state.scheduler
    state = load_state(store_dir)
    run_ids = state.get("run_ids", {})
    targets = {name: SEGMENT_RUNS * segment
               for name, rid in run_ids.items()
               if name in {b.name for b in c2_new_blocks(manifest)}}
    for name, rid in run_ids.items():
        if name in targets and sched.plan_for(rid) is None:
            if not sched.reattach(rid):
                raise RuntimeError(f"reattach 失败：{name} run_id={rid}")
    sched.executor_hook = router_hook(routes)

    t0 = time.monotonic()
    blocks: dict[str, dict] = {}
    while time.monotonic() - t0 < timeout_s:
        sched.tick()
        with sched.session_factory() as s:
            for name, target in targets.items():
                row = s.get(CertificationRun, run_ids[name])
                blocks[name] = {
                    "n": row.n, "pass": row.pass_count,
                    "live_pass_rate": row.live_pass_rate,
                    "regression_pass_rate": row.regression_pass_rate,
                    "verdict": row.verdict,
                    "reached": row.n >= target,
                }
        if all(v["reached"] for v in blocks.values()) and len(blocks) == len(targets):
            break
        time.sleep(poll_s)
    for name in blocks:
        blocks[name]["reached"] = blocks[name]["n"] >= targets[name]
    return {"segment": segment, "driven_at": now_iso(), "blocks": blocks,
            "reached_all": all(v["reached"] for v in blocks.values()) or not blocks}


def status(store_dir: Path, manifest, *, app) -> list[dict]:
    """全库状态：manifest 新块 + 遗留两块（legacy_state_key 映射 ms1e 键）。"""
    state = load_state(store_dir)
    run_ids = dict(state.get("run_ids", {}))
    for b in manifest.blocks:
        if b.exists and b.legacy_state_key and b.legacy_state_key in run_ids:
            run_ids[b.name] = run_ids[b.legacy_state_key]
    out = []
    with app.state.session_factory() as s:
        for name, rid in sorted(run_ids.items()):
            row = s.get(CertificationRun, rid)
            out.append({
                "name": name, "run_id": rid, "n": row.n, "pass": row.pass_count,
                "live_pass_rate": row.live_pass_rate,
                "regression_pass_rate": row.regression_pass_rate,
                "verdict": row.verdict,
                "window": [row.started_at.isoformat() if row.started_at else None,
                           row.finished_at.isoformat() if row.finished_at else None],
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["submit", "drive", "status"])
    parser.add_argument("--batch", type=int, choices=[1, 2], default=None)
    parser.add_argument("--segment", type=int, choices=[1, 2])
    args = parser.parse_args()
    manifest = load_manifest(SEEDS / "manifest.yaml")

    from fastapi.testclient import TestClient

    from forge_server.app import create_app

    STORE.mkdir(parents=True, exist_ok=True)
    app = create_app(f"sqlite:///{(STORE / 'server.db').as_posix()}", clock=WallClock())
    client = TestClient(app)

    if args.command == "submit":
        ids = submit(STORE, manifest, batch=args.batch, client=client)
        print(json.dumps(ids, ensure_ascii=False, indent=2))
        return 0
    if args.command == "drive":
        if not args.segment:
            parser.error("drive 需要 --segment {1,2}")
        routes = build_routes(STORE, manifest, batch=args.batch)
        result = drive(STORE, manifest, args.segment, app=app, routes=routes)
        suffix = f"_batch{args.batch}" if args.batch else ""
        out = EVIDENCE / f"t1.63_drive_seg{args.segment}{suffix}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"drive: {'PASS' if result['reached_all'] else 'INCOMPLETE'} → {out}")
        return 0 if result["reached_all"] else 1
    rows = status(STORE, manifest, app=app)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
