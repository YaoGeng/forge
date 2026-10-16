"""excel_export：行集导出 xlsx（s8 数据导出；本地计算块）。

输出契约只含稳定字段（文件名来自参数而非绝对路径）——golden 对拍确定性。
"""
import tempfile
from pathlib import Path


def run(params: dict) -> dict:
    from openpyxl import Workbook

    rows = [c for c in str(params.get("rows", "")).split(";") if c]
    out = str(params.get("out", "report.xlsx"))
    target = Path(tempfile.gettempdir()) / "forge-blocks"
    target.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["row"])
    for r in rows:
        ws.append([r])
    wb.save(target / out)
    return {"ok": True, "file": out, "rows": len(rows)}
