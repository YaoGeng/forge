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
    from forge_trace.similarity import AssertVerdict
    test_yaml = tmp_path / "test.yaml"
    test_yaml.write_text("assertion: golden_similarity\nthreshold: 0.85\n", encoding="utf-8")
    v = TestRunner.check({"html_a": PAGE_10, "html_b": PAGE_TEXT_NOISE}, test_yaml)
    assert isinstance(v, AssertVerdict)
    assert v.ok and v.assertion == "golden_similarity"
    bad = TestRunner.check({"html_a": PAGE_10, "html_b": PAGE_5}, test_yaml)
    assert not bad.ok


def test_testrunner_unknown_assertion(tmp_path):
    test_yaml = tmp_path / "test.yaml"
    test_yaml.write_text("assertion: magic\n", encoding="utf-8")
    with pytest.raises(ValueError):
        TestRunner.check({}, test_yaml)


def test_similarity_rejects_identical_dup_half_deletion():
    # 评审 Critical：同构重复节点删半（presence/计数余弦均盲）必须被拒绝
    unit = "<section><h2>标题</h2><p>段落正文内容完全相同</p></section>"
    page10 = "<html><body><main>" + unit * 10 + "</main></body></html>"
    page5 = "<html><body><main>" + unit * 5 + "</main></body></html>"
    v = golden_similarity(page10, page5)
    assert v.score < 0.85 and not v.passed


def test_similarity_accepts_minor_count_drift():
    # 动态内容：10 → 9 同构项（比例 0.9）应放行，拒绝线只砍结构性缺失
    unit = "<section><h2>标题</h2><p>段落正文内容完全相同</p></section>"
    page10 = "<html><body><main>" + unit * 10 + "</main></body></html>"
    page9 = "<html><body><main>" + unit * 9 + "</main></body></html>"
    assert golden_similarity(page10, page9).passed


def test_similarity_tolerates_void_tag_flip():
    # 评审 Important：void 标签不入栈——单侧 <br> 不得污染子树路径；
    # 真实页规模下（数十路径）单节点差异应在阈上（小页粒度见 C7-R1 说明）
    body = "".join(f"<section><h2>标题{i}</h2><p>段落{i}的正文内容</p></section>" for i in range(10))
    a = f"<html><body><form><input>{body}<button>go</button></form></body></html>"
    b = f"<html><body><form><input><br>{body}<button>go</button></form></body></html>"
    v = golden_similarity(a, b)
    assert v.passed and v.score >= 0.95


def test_fieldwise_unhashable_set_items():
    # 评审 Important：列表元素为 dict（JSON 常态）不得 TypeError 崩溃
    same = fieldwise({"items": [{"a": 1}]}, {"items": [{"a": 1}]})
    assert same.ok
    diff = fieldwise({"items": [{"a": 1}]}, {"items": [{"a": 2}]})
    assert not diff.ok and diff.failures


def test_golden_similarity_combined_verdict():
    # 评审 Important：结构过 ∧ 字段超差 → 不得通过（组合判定覆盖）
    fields_bad = golden_similarity(
        PAGE_10, PAGE_TEXT_NOISE, fields_a={"count": 10}, fields_b={"count": 999}
    )
    assert fields_bad.fields_ok is False and not fields_bad.passed
    fields_ok = golden_similarity(
        PAGE_10, PAGE_TEXT_NOISE, fields_a={"count": 98}, fields_b={"count": 100}
    )
    assert fields_ok.passed


def test_fieldwise_bool_vs_number_distinct():
    # 评审 Minor：True 与 1 不得混同（bool/int 类型混淆）
    assert not fieldwise({"flag": True}, {"flag": 1}).ok
    assert fieldwise({"flag": True}, {"flag": True}).ok
