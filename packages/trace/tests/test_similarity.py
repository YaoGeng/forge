"""golden_similarity 断言与 TestRunner 正反用例（docs/11 §5 T1.24 矩阵 + C7）。"""
import pytest
from forge_trace.similarity import (
    FieldVerdict,
    SimilarityVerdict,
    TestRunner,
    cosine,
    embed,
    fieldwise,
    golden_similarity,
    structural_similarity,
)

PAGE_10 = (
    "<html><body><main>"
    + "".join(
        f"<section><h{i+2}>标题{i}</h{i+2}><p>段落{i}的正文内容</p></section>"
        for i in range(10)
    )
    + "</main></body></html>"
)
# 删半：仅保留 5 个 section（结构同类）
PAGE_5 = PAGE_10.replace(
    "".join(
        f"<section><h{i+2}>标题{i}</h{i+2}><p>段落{i}的正文内容</p></section>"
        for i in range(5, 10)
    ),
    "",
)
# 同结构、纯文本噪声
PAGE_TEXT_NOISE = PAGE_10.replace("正文内容", "另一段话")
# 换主标签：main → article
PAGE_RETAG = PAGE_10.replace("<main>", "<article>").replace("</main>", "</article>")


def test_cosine_identical():
    assert cosine(embed(PAGE_10), embed(PAGE_10)) == 1.0
    assert structural_similarity(PAGE_10, PAGE_10) == 1.0


def test_similarity_rejects_structural_change():
    # Review Focus 5：删半 / 换主 tag 必须低于阈值（结构嵌入须路径敏感）
    half = golden_similarity(PAGE_10, PAGE_5)
    retag = golden_similarity(PAGE_10, PAGE_RETAG)
    assert half.score < 0.85 and not half.passed
    assert retag.score < 0.85 and not retag.passed


def test_similarity_ignores_text_noise():
    v = golden_similarity(PAGE_10, PAGE_TEXT_NOISE)
    assert v.score >= 0.85 and v.passed


def test_fieldwise_numeric_tolerance():
    ok = fieldwise({"price": 98}, {"price": 100})
    assert ok.ok and not ok.failures
    # 绝对容差救回：0.4 vs 100（相对 99.6% 超差，绝对 0.4 ≤ 0.5 取宽）
    assert fieldwise({"x": 100.4}, {"x": 100}).ok
    assert not fieldwise({"price": 90}, {"price": 100}).ok


def test_fieldwise_set_jaccard():
    base = {"tags": [f"t{i}" for i in range(10)]}
    assert fieldwise(base, {"tags": [f"t{i}" for i in range(8)]}).ok  # 8/10 ≥ 0.8
    assert not fieldwise(base, {"tags": [f"t{i}" for i in range(5)]}).ok  # 5/10


def test_fieldwise_failures_reported():
    v = fieldwise({"a": 1, "b": "x"}, {"a": 999, "c": "x"})
    assert not v.ok
    assert any("a" in f for f in v.failures) and any("b" in f for f in v.failures)


def test_testrunner_schema_pass_fail(tmp_path):
    test_yaml = tmp_path / "test.yaml"
    test_yaml.write_text(
        "assertion: schema\n"
        "expect:\n"
        "  type: object\n"
        "  required: [title]\n"
        "  properties:\n"
        "    title: {type: string}\n"
        "    count: {type: number}\n",
        encoding="utf-8",
    )
    good = TestRunner.check({"title": "报告", "count": 3}, test_yaml)
    assert good.ok and good.assertion == "schema"
    missing = TestRunner.check({"count": 3}, test_yaml)
    assert not missing.ok and "title" in missing.detail
    wrong_type = TestRunner.check({"title": 5}, test_yaml)
    assert not wrong_type.ok


def test_testrunner_golden_channel(tmp_path):
    test_yaml = tmp_path / "test.yaml"
    test_yaml.write_text("assertion: golden_similarity\nthreshold: 0.85\n", encoding="utf-8")
    v = TestRunner.check({"html_a": PAGE_10, "html_b": PAGE_TEXT_NOISE}, test_yaml)
    assert isinstance(v, type(TestRunner.check({"html_a": PAGE_10, "html_b": PAGE_TEXT_NOISE}, test_yaml)))
    assert v.ok and v.assertion == "golden_similarity"
    bad = TestRunner.check({"html_a": PAGE_10, "html_b": PAGE_5}, test_yaml)
    assert not bad.ok


def test_testrunner_unknown_assertion(tmp_path):
    test_yaml = tmp_path / "test.yaml"
    test_yaml.write_text("assertion: magic\n", encoding="utf-8")
    with pytest.raises(ValueError):
        TestRunner.check({}, test_yaml)
