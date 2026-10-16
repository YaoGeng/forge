"""markdown_export：行集导出 md 表（s8 数据导出；本地计算块）。"""
import tempfile
from pathlib import Path


def run(params: dict) -> dict:
    rows = [c for c in str(params.get("rows", "")).split(";") if c]
    out = str(params.get("out", "report.md"))
    target = Path(tempfile.gettempdir()) / "forge-blocks"
    target.mkdir(parents=True, exist_ok=True)
    lines = ["| row |", "| --- |"] + [f"| {r} |" for r in rows]
    (target / out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": out, "rows": len(rows)}
