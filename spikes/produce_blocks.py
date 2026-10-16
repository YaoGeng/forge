"""T1.63 产线 CLI（docs/13 §5 T1.63；触网）。

produce --batch N：trace 块 = 脚手架 → 真实录制（3 次重试）→ golden 采集脱敏 → SDK 门复核；
python 块 = 脚手架（占位 main.py 随批次手写替换后 snapshot）。
"""
from __future__ import annotations

import argparse
import importlib
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
    "spikes",
):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_block_sdk import lint, validate_block_dir  # noqa: E402
from forge_trace import Recorder, RecordingsStore, collect_golden, validate_golden_no_raw  # noqa: E402
from forge_trace.patchright_browser import PatchrightBrowser  # noqa: E402

from cert_batch import STORE, load_state, save_state  # noqa: E402
from seedline import load_manifest, scaffold_block  # noqa: E402
from seedline import ensure_block as _ensure_block  # noqa: E402

SEEDS = _ROOT / "spikes" / "seed_blocks"


def load_browse(script_ref: str):
    module, _, fn = script_ref.partition(":")
    mod = importlib.import_module(module)
    return getattr(mod, fn)


def record_once(store, entry):
    """单块真实录制 + golden 采集脱敏（gate ensure_trace 同款语义）。"""
    browse = load_browse(entry.script)
    browser = PatchrightBrowser()
    try:
        rec = Recorder(store, lambda: browser)
        session = rec.record.start(entry.site)
        browse(session.port)
        ref = rec.record.stop()
    finally:
        browser.close()
    golden = collect_golden(ref, store=store, environment_fingerprint="ms1f-seed")
    errors = validate_golden_no_raw(golden)
    if errors:
        raise RuntimeError(f"golden 脱敏泄漏 {entry.name}: {errors}")
    return ref


def produce(batch: int | None) -> int:
    manifest = load_manifest(SEEDS / "manifest.yaml")
    store = RecordingsStore(STORE)
    state = load_state(STORE)
    failures = []
    for entry in manifest.blocks:
        if entry.exists or (batch is not None and entry.batch != batch):
            continue
        print(f"=== produce {entry.name}（adapter={entry.adapter}）===", flush=True)
        try:
            d = scaffold_block(entry, seeds_dir=SEEDS, sites=manifest.sites)
            if entry.adapter == "trace":
                ref = _ensure_block(entry, store, state, record_once, sleep=time.sleep)
                save_state(STORE, state)
                print(f"  trace_ref={ref}", flush=True)
            else:
                if (d / "main.py").exists() and "NotImplementedError" not in (
                        d / "main.py").read_text(encoding="utf-8"):
                    golden = d / "tests" / "golden" / "expected_output.json"
                    if not golden.exists():
                        from seedline import snapshot_output
                        gp = snapshot_output(d, dict(entry.params))
                        print(f"  golden 快照 → {gp.name}", flush=True)
                else:
                    print("  python 块：main.py 待手写（T1.63 批次二），先落占位", flush=True)
            spec = validate_block_dir(d)
            if not lint(d).ok:
                raise RuntimeError("lint 未通过")
            print(f"  SDK 门 OK（{spec.name}）", flush=True)
        except Exception as exc:
            import traceback

            traceback.print_exc()
            failures.append(f"{entry.name}: {type(exc).__name__}: {exc}")
    if failures:
        print(json.dumps({"failed": failures}, ensure_ascii=False, indent=2), flush=True)
        return 1
    print(f"produce batch={batch} 全部完成 @ "
          f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, choices=[1, 2], default=None)
    args = parser.parse_args()
    return produce(args.batch)


if __name__ == "__main__":
    raise SystemExit(main())
