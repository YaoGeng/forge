"""MS-1D gate 运行器（docs/11 §5 T1.25；触网，仅 spikes 侧）。

对 3 个种子站点（C1：A=example.com standard / B=hn.algolia.com medium /
C=baidu.com high）各执行：脚本化录制（模拟创作者操作）→ trace 自检零错误 →
回放 10 次 → assert_consistent（C 站走 htmls+similarity 通道）→
collect_golden → 脱敏零泄漏。输出 JSON/日志到 spikes/evidence/，
末行打印 `gate: PASS|FAIL`。

用法：python spikes/run_ms1d_gate.py --site A|B|C|all
存储根：spikes/evidence/ms1d_store/（git 忽略，只归档摘要 JSON/日志）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("packages/trace/python", "packages/proto/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_proto.trace import load_manifest, validate_trace_dir
from forge_trace import (
    RecordingsStore,
    Recorder,
    assert_consistent,
    collect_golden,
    replay,
    validate_golden_no_raw,
)
from forge_trace.patchright_browser import PatchrightBrowser

EVIDENCE = _ROOT / "spikes" / "evidence"
STORE_ROOT = EVIDENCE / "ms1d_store"
REPLAYS = 10


# —— 创作者操作脚本（模拟真实操作序列）——

def script_example(port) -> None:
    port.goto("https://example.com/")
    port.wait_selector("a", 10_000)
    time.sleep(0.6)
    port.click("a")  # 页内唯一链接 → 导航
    time.sleep(1.2)


def script_hn_algolia(port) -> None:
    # hn.algolia 为 SPA（pushState 不产生 nav 步）且首页搜索框无稳定属性
    # （首轮 gate 实证：结构路径 selector 跨加载即碎、记入 fragile）。
    # B 站场景改为确定性双查询导航，动态结果列表走 similarity 通道（C6 判据本意）。
    # 等待条件到结果项粒度：首屏骨架/完整列表两态是首轮 seq1/2 mismatch 的根因。
    port.goto("https://hn.algolia.com/?q=python")
    port.wait_selector(".hits li", 15_000)
    time.sleep(1.5)
    port.goto("https://hn.algolia.com/?q=nodejs")
    port.wait_selector(".hits li", 15_000)
    time.sleep(1.5)


def script_baidu(port) -> None:
    # 原计划 C 站 baidu.com 已改版为 AI 对话式首页（经典 #kw/#su 隐藏，fill 不可用；
    # sogou 备选直接反爬）→ 按计划 C1 预授权登记换站 cn.bing.com（fill+Enter 交互，
    # 结果页动态列表走 similarity 通道）。交互形态保留：fill + 键盘提交。
    port.goto("https://cn.bing.com/")
    port.wait_selector("#sb_form_q", 15_000)
    time.sleep(1.0)
    port.fill("#sb_form_q", "python")
    port.press("Enter")
    port.wait_selector("#b_results .b_algo", 15_000)
    time.sleep(1.5)


def _first_present(port, selectors):
    for sel in selectors:
        if port.wait_selector(sel, 1_500):
            return sel
    return None


SITES = {
    "A": {"name": "example.com", "host": "example.com", "tier": "standard",
          "script": script_example, "use_htmls": False},
    "B": {"name": "hn.algolia.com", "host": "hn.algolia.com", "tier": "medium",
          "script": script_hn_algolia, "use_htmls": True},
    "C": {"name": "cn.bing.com", "host": "cn.bing.com", "tier": "high",
          "script": script_baidu, "use_htmls": True},
}


def run_site(key: str) -> dict:
    site = SITES[key]
    store = RecordingsStore(STORE_ROOT)
    result: dict = {
        "site": site["name"], "tier": site["tier"], "replays": REPLAYS,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    # 1. 脚本化录制
    browser = PatchrightBrowser()
    try:
        rec = Recorder(store, lambda: browser)
        session = rec.record.start(site["host"])
        site["script"](session.port)
        trace_ref = rec.record.stop()
    finally:
        browser.close()
    result["trace_ref"] = trace_ref

    # 2. trace 自检
    trace_dir = STORE_ROOT / "traces" / trace_ref
    trace_errors = validate_trace_dir(trace_dir)
    result["trace_errors"] = trace_errors
    manifest = load_manifest(trace_dir / "manifest.yaml")

    # 3. 回放 10 次（独立浏览器；html 捕获供 similarity 通道）
    runs, sinks = [], []
    for _ in range(REPLAYS):
        sink: list[str] = []
        port = PatchrightBrowser(html_sink=sink)
        try:
            runs.append(replay.run(trace_ref, store=store, browser_factory=lambda p=port: p))
        finally:
            port.close()
        sinks.append(sink)
    step_count = len(runs[0].step_results)
    htmls = {
        runs[0].step_results[i]["seq"]: tuple(sink[i] for sink in sinks if len(sink) > i)
        for i in range(step_count)
    }
    htmls = {seq: pair for seq, pair in htmls.items() if len(pair) == REPLAYS}

    # 4. 一致性判定（C 站走 htmls+similarity 通道）
    report = assert_consistent(
        runs, manifest, htmls=htmls if site["use_htmls"] else None
    )
    result["consistency"] = report.kind
    result["diff"] = list(report.diff)
    result["fragile_steps"] = list(store.get(trace_ref).fragile_steps)

    # 5. golden 采集 + 脱敏校验
    golden = collect_golden(trace_ref, store=store, environment_fingerprint="ms1d-gate")
    redaction_errors = validate_golden_no_raw(golden)
    result["redaction_errors"] = redaction_errors
    result["golden_dir"] = str(golden)

    result["gate"] = "PASS" if (
        not trace_errors
        and report.kind != "mismatch"
        and not redaction_errors
    ) else "FAIL"
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="all", choices=["A", "B", "C", "all"])
    args = parser.parse_args()
    keys = list(SITES) if args.site == "all" else [args.site]

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    overall = True
    for key in keys:
        print(f"=== site {key} ({SITES[key]['name']}, {SITES[key]['tier']}) ===", flush=True)
        try:
            result = run_site(key)
        except Exception as exc:
            result = {"site": SITES[key]["name"], "gate": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        out = EVIDENCE / f"t1.25_{key}_{SITES[key]['name'].replace('.', '_')}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        print(f"gate: {result['gate']}", flush=True)
        overall = overall and result["gate"] == "PASS"
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
