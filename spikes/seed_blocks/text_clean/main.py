"""text_clean：空白清洗（s9 文本汇总整理；本地计算块）。"""


def run(params: dict) -> dict:
    text = " ".join(str(params.get("text", "")).split())
    return {"ok": True, "text": text, "length": len(text)}
