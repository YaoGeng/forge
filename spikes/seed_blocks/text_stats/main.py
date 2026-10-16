"""text_stats：词数统计（s9 文本汇总整理；本地计算块）。"""


def run(params: dict) -> dict:
    words = str(params.get("text", "")).lower().split()
    return {"ok": True, "words": len(words), "unique": len(set(words)),
            "chars": len(str(params.get("text", "")))}
