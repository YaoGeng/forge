"""unit_convert：厘米→米/英尺（s10 数值计算；本地计算块）。"""


def run(params: dict) -> dict:
    cm = float(params.get("cm", "0"))
    return {"ok": True, "m": round(cm / 100, 3), "feet": round(cm / 30.48, 2)}
