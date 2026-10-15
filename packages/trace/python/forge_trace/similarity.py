"""结构嵌入与相似度原语（docs/11 §3 C7 v1：确定性结构嵌入，无 AI 调用）。

T1.22 先交付本模块的嵌入/余弦/阈值原语（比较器 similarity 通道依赖）；
T1.24 在其上补字段级容差、golden_similarity 与 TestRunner（计划卡面裁定，
ledger 登记）。阈值 0.85 为 v1 初值（M07 §3.2「初值 TBD」→ docs/11 §3 C7 钉死）。
"""
from __future__ import annotations

from html.parser import HTMLParser

SIMILARITY_THRESHOLD = 0.85


class _TagCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.counts: dict[str, int] = {}

    def handle_starttag(self, tag, attrs) -> None:
        key = tag.lower()
        self.counts[key] = self.counts.get(key, 0) + 1


def embed(html: str) -> dict[str, float]:
    """html → 标签计数向量（小写化；解析失败按空文档处理，不抛）。"""
    counter = _TagCounter()
    try:
        counter.feed(html)
        counter.close()
    except Exception:
        return {}
    return {k: float(v) for k, v in counter.counts.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in common)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def structural_similarity(html_a: str, html_b: str) -> float:
    """结构嵌入余弦（C7）；非负截断（余弦理论域 [-1,1]，计数向量非负故恒 ≥0）。"""
    return max(0.0, cosine(embed(html_a), embed(html_b)))
