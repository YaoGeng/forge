"""json_export：行集导出 JSON（s8 数据导出；本地计算块；csv_export 同款惯例改造）。"""
import json
import tempfile
from pathlib import Path


def run(params: dict) -> dict:
    rows = [c for c in str(params.get("rows", "")).split(";") if c]
    out = str(params.get("out", "report.json"))
    target = Path(tempfile.gettempdir()) / "forge-blocks"
    target.mkdir(parents=True, exist_ok=True)
    (target / out).write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "file": out, "rows": len(rows)}
