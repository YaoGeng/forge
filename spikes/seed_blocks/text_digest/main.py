"""text_digest：多行文本汇总（s9 文本汇总整理；本地计算块）。"""


def run(params: dict) -> dict:
    items = [c.strip() for c in str(params.get("lines", "")).split(";") if c.strip()]
    return {"ok": True, "items": len(items), "digest": " | ".join(items)}
