"""price_calc：单价×数量（s10 数值计算；本地计算块）。"""


def run(params: dict) -> dict:
    price = float(params.get("price", "0"))
    qty = int(str(params.get("qty", "1")))
    return {"ok": True, "qty": qty, "total": round(price * qty, 2)}
