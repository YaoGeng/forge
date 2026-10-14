"""T0.2b 证据生成：对 live 目标产出结构报告并归档到 spikes/evidence/。

用法：python spikes/run_t02_evidence.py
stdout 打印两份报告的 selector_candidates（T0.3a 固化 SELECTORS 的依据）。
空候选报告拒绝归档（评审 Finding 1：防站点改版/拦截页静默覆盖好证据）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from site_inspect.inspect import reset_rate_limiter, site_inspect

EVIDENCE = Path(__file__).resolve().parent / "evidence"

TARGETS = [
    ("front", "https://hn.algolia.com/", "t0.2_front.json"),
    ("search", "https://hn.algolia.com/?q=python", "t0.2_search.json"),
]


def ensure_candidates(report: dict) -> None:
    """证据归档门：候选表为空 = 页面结构与预期不符，拒绝入库。"""
    if not report.get("selector_candidates"):
        raise RuntimeError(
            "evidence rejected: empty selector candidates (site changed or blocked?)"
        )


def main() -> int:
    for name, url, filename in TARGETS:
        reset_rate_limiter()
        report = site_inspect(url, ["hn.algolia.com"])
        ensure_candidates(report)  # 通过后才落盘，坏报告不覆盖归档
        (EVIDENCE / filename).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[{name}] {url}")
        print(f"  http_status={report['http_status']} robots={report['robots_respected']} "
              f"response_ms={report['stability']['response_ms']}")
        print(f"  selector_candidates={json.dumps(report['selector_candidates'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
