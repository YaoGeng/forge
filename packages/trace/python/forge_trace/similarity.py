"""golden_similarity 断言与 TestRunner（docs/11 §3 C7 v1：确定性结构嵌入，无 AI 调用）。

结构嵌入 = 标签**路径**计数向量（根→节点标签链，深度≤8，小写化）。
修订 R1（T1.24）：全局标签计数对删半/换主标签不敏感（余弦 ≈0.99），
满足不了 Review Focus 5 的结构变更拒绝线；路径计数使结构差异显影，
同模板异文本仍 ≈1.0（文本不进嵌入）。
阈值 0.85 为 v1 初值（M07 §3.2「初值 TBD」→ docs/11 §3 C7 钉死）。
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import yaml

SIMILARITY_THRESHOLD = 0.85
_EMBED_MAX_DEPTH = 8


class _PathCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paths: set[str] = set()
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        t = tag.lower()
        self._stack.append(t)
        self.paths.add("/".join(self._stack[-_EMBED_MAX_DEPTH:]))

    def handle_endtag(self, tag) -> None:
        t = tag.lower()
        if t in self._stack:
            # 容忍错配闭合：弹到最近同名标签
            while self._stack and self._stack.pop() != t:
                pass


def embed(html: str) -> dict[str, float]:
    """html → 标签路径**存在性**向量（path → 1.0；解析失败按空文档处理，不抛）。

    二值存在性而非计数：重复路径的点积会掩盖节点删半（计数余弦 ≈0.97）；
    结构形状由 presence 表达，数量差异归 fieldwise 数值容差通道（C7-R1）。
    """
    collector = _PathCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:
        return {}
    return {k: 1.0 for k in collector.paths}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if a == b:  # 恒等捷径：相同向量浮点点积可能得 0.999…
        return 1.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def structural_similarity(html_a: str, html_b: str) -> float:
    """结构嵌入余弦（C7 修订 R1）；计数向量非负故恒 ≥0。"""
    return max(0.0, cosine(embed(html_a), embed(html_b)))


@dataclass(frozen=True)
class FieldVerdict:
    ok: bool
    failures: tuple[str, ...] = ()


def fieldwise(
    a: dict,
    b: dict,
    *,
    num_tol: float = 0.05,
    abs_tol: float = 0.5,
    set_jaccard_min: float = 0.8,
) -> FieldVerdict:
    """字段级容差（C7）：数值 ±num_tol 相对或 ±abs_tol 绝对（取宽）；集合 Jaccard；字符串须等。"""
    failures: list[str] = []
    for key in sorted(set(a) | set(b)):
        if key not in a or key not in b:
            failures.append(f"{key}: 单侧缺失")
            continue
        x, y = a[key], b[key]
        if isinstance(x, bool) or isinstance(y, bool):
            if x != y:
                failures.append(f"{key}: {x!r} != {y!r}")
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)):
            denom = max(abs(x), abs(y), 1e-9)
            if not (abs(x - y) / denom <= num_tol or abs(x - y) <= abs_tol):
                failures.append(f"{key}: 数值超差 {x} vs {y}")
        elif isinstance(x, (list, set)) and isinstance(y, (list, set)):
            sx, sy = set(x), set(y)
            union = sx | sy
            jaccard = len(sx & sy) / len(union) if union else 1.0
            if jaccard < set_jaccard_min:
                failures.append(f"{key}: 集合 Jaccard {jaccard:.2f} < {set_jaccard_min}")
        elif x != y:
            failures.append(f"{key}: {x!r} != {y!r}")
    return FieldVerdict(ok=not failures, failures=tuple(failures))


@dataclass(frozen=True)
class SimilarityVerdict:
    score: float
    fields_ok: bool
    passed: bool


def golden_similarity(
    html_a: str,
    html_b: str,
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    fields_a: dict | None = None,
    fields_b: dict | None = None,
) -> SimilarityVerdict:
    """结构余弦 ∧ 字段级容差（M07 §3.2；字段缺省时仅结构）。"""
    score = structural_similarity(html_a, html_b)
    if fields_a is None or fields_b is None:
        fields_ok = True
    else:
        fields_ok = fieldwise(fields_a, fields_b).ok
    return SimilarityVerdict(score=score, fields_ok=fields_ok, passed=score >= threshold and fields_ok)


# —— TestRunner ——

_TYPE_MAP = {
    "object": dict,
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "null": type(None),
}


@dataclass(frozen=True)
class AssertVerdict:
    ok: bool
    assertion: str
    detail: str = ""


def _validate_schema(node, spec: dict, path: str, errors: list[str]) -> None:
    t = spec.get("type")
    if t:
        expected = _TYPE_MAP.get(t)
        if expected is None:
            errors.append(f"{path}: 未知 type {t!r}")
            return
        if isinstance(node, bool) and t != "boolean":
            errors.append(f"{path}: 应为 {t}，得到 boolean")
            return
        if not isinstance(node, expected):
            errors.append(f"{path}: 应为 {t}，得到 {type(node).__name__}")
            return
    if isinstance(node, dict):
        for req in spec.get("required", []):
            if req not in node:
                errors.append(f"{path}: 缺 required 字段 {req}")
        props = spec.get("properties", {})
        for key, sub in props.items():
            if key in node:
                _validate_schema(node[key], sub, f"{path}.{key}", errors)
    if isinstance(node, list) and "items" in spec:
        for i, item in enumerate(node):
            _validate_schema(item, spec["items"], f"{path}[{i}]", errors)


class TestRunner:
    """断言执行（M07 §3.3）：schema → interface 子集校验；golden_similarity → 结构+容差。

    check 为静态方法（计划卡面 TestRunner.assert 因 assert 为 Python 关键字更名，
    ledger 登记）。
    """

    @staticmethod
    def check(run_output: dict, test_yaml_path: str | Path) -> AssertVerdict:
        doc = yaml.safe_load(Path(test_yaml_path).read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError(f"{test_yaml_path}: test.yaml 必须是映射")
        assertion = doc.get("assertion")
        if assertion == "schema":
            expect = doc.get("expect", {})
            errors: list[str] = []
            _validate_schema(run_output, expect, "$", errors)
            return AssertVerdict(
                ok=not errors, assertion=assertion, detail="; ".join(errors[:5])
            )
        if assertion == "golden_similarity":
            try:
                html_a = run_output["html_a"]
                html_b = run_output["html_b"]
            except (KeyError, TypeError):
                return AssertVerdict(
                    ok=False, assertion=assertion, detail="run_output 缺 html_a/html_b"
                )
            threshold = float(doc.get("threshold", SIMILARITY_THRESHOLD))
            fields_a = run_output.get("fields_a")
            fields_b = run_output.get("fields_b")
            verdict = golden_similarity(
                html_a, html_b, threshold=threshold, fields_a=fields_a, fields_b=fields_b
            )
            return AssertVerdict(
                ok=verdict.passed,
                assertion=assertion,
                detail=f"score={verdict.score:.3f} fields_ok={verdict.fields_ok}",
            )
        raise ValueError(f"未知断言类型: {assertion!r}（支持 schema | golden_similarity）")
