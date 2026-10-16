"""csv_export：行集导出 csv（s8 数据导出；本地计算块）。"""
import csv
import tempfile
from pathlib import Path


def run(params: dict) -> dict:
    rows = [c for c in str(params.get("rows", "")).split(";") if c]
    out = str(params.get("out", "report.csv"))
    target = Path(tempfile.gettempdir()) / "forge-blocks"
    target.mkdir(parents=True, exist_ok=True)
    with open(target / out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["row"])
        for r in rows:
            w.writerow([r])
    return {"ok": True, "file": out, "rows": len(rows)}
