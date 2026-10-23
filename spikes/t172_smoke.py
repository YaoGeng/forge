"""T1.72 Step4 真链冒烟：bing_search + text_clean 经 product_path 真跑（真浏览器，本机出口）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from product_path import build_server, wire_chain_runner  # noqa: E402

store = Path(__file__).resolve().parent / "evidence" / "ms1e_store"
app = build_server(store)
wire_chain_runner(app, store, ["bing_search", "text_clean"])
out = app.state.chain_runner([
    {"block": "bing_search", "params": {}},
    {"block": "text_clean", "params": {"text": "  Hello   World  "}},
])
evidence = {
    "ok": out["ok"],
    "steps": out["steps"],
    "bing_results": out["context"].get("bing_search", {}).get("results"),
    "text_clean": out["context"].get("text_clean"),
    "ran_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
              .isoformat(timespec="seconds"),
}
p = Path(__file__).resolve().parent / "evidence" / "t1.71_smoke.json"
p.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: evidence[k] for k in ("ok", "bing_results", "text_clean")},
                 ensure_ascii=False))
assert out["ok"] and evidence["bing_results"], "冒烟失败"
print("SMOKE OK")
