"""T0.3b 证据生成：手工积木原型产出报告文件到 spikes/evidence/。

用法：python spikes/run_t03_evidence.py
stdout 打印行数与首行标题（gate 演示口径：标准站点搜索 → Excel 报告）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from manual_block.hn_search_block import run_search

EVIDENCE = Path(__file__).resolve().parent / "evidence"


def main() -> int:
    rows = run_search(
        "python",
        out_xlsx=EVIDENCE / "t0.3_report.xlsx",
        out_json=EVIDENCE / "t0.3_rows.json",
    )
    print(f"rows={len(rows)} first_title={rows[0]['title']!r}")
    print(f"xlsx={EVIDENCE / 't0.3_report.xlsx'} bytes={(EVIDENCE / 't0.3_report.xlsx').stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
