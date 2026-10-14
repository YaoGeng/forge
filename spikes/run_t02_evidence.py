"""T0.2b 证据生成：对 live 目标产出结构报告并归档到 spikes/evidence/。

用法：python spikes/run_t02_evidence.py
stdout 打印两份报告的 selector_candidates（T0.3a 固化 SELECTORS 的依据）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from site_inspect.inspect import reset_rate_limiter, site_inspect

EVIDENCE = Path(__file__).resolve().parent / "evidence"

TARGETS = [
    ("front", "https://hn.algolia.com/", "t0.2_front.json"),
    ("search", "https://hn.algolia.com/?q=python", "t0.2_search.json"),
]


def main() -> int:
    for name, url, filename in TARGETS:
        reset_rate_limiter()
        report = site_inspect(url, ["hn.algolia.com"], out_path=EVIDENCE / filename)
        print(f"[{name}] {url}")
        print(f"  http_status={report['http_status']} robots={report['robots_respected']} "
              f"response_ms={report['stability']['response_ms']}")
        print(f"  selector_candidates={json_dumps(report['selector_candidates'])}")
    return 0


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
