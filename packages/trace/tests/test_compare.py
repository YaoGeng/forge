"""回放一致性比较器正反用例（docs/11 §5 T1.22 矩阵后 5 条 + C6 判据）。"""
import pytest
from forge_proto.trace import Manifest, TimeSensitiveStep
from forge_trace import Recorder, RecordingsStore
from forge_trace.replayer import ReplayResult, StepResult, assert_consistent
from forge_trace.similarity import structural_similarity
from fake_browser import FakeBrowser


def _step(seq, action, ok=True, anchor=True, digest="d0", duration=100):
    return StepResult(
        seq=seq, action=action, ok=ok, anchor_matched=anchor,
        snapshot_digest=digest, duration_ms=duration,
    )


def _run(step_results, trace_ref="tr_x", mode="local"):
    return ReplayResult(trace_ref=trace_ref, mode=mode, step_results=tuple(step_results))


def _manifest(*time_sensitive):
    return Manifest(
        format_version="1.0",
        site="example.com",
        login_steps=(),
        time_sensitive_steps=tuple(
            TimeSensitiveStep(seq=s, tolerance_ms=None) for s in time_sensitive
        ),
    )


def test_compare_exact():
    report = assert_consistent(
        [_run([_step(1, "nav"), _step(2, "click")]), _run([_step(1, "nav"), _step(2, "click")])],
        _manifest(),
    )
    assert report.kind == "exact"
    assert report.diff == ()


def test_compare_tolerance_channels():
    # Review Focus 3：anchor 迟到在声明的时间敏感步上走 tolerant 而非 mismatch
    report = assert_consistent(
        [
            _run([_step(1, "nav"), _step(2, "click", ok=True, anchor=True)]),
            _run([_step(1, "nav"), _step(2, "click", ok=False, anchor=False)]),
        ],
        _manifest(2),
    )
    assert report.kind == "tolerant"
    assert report.diff[0]["kind"] == "tolerant"


def test_compare_similarity_channel():
    html_a = "<html><body><div id='m'><p>a</p><p>b</p></div></body></html>"
    # 同结构、文本不同（结构嵌入只看标签计数）
    html_b = "<html><body><div id='m'><p>x</p><p>y</p></div></body></html>"
    assert structural_similarity(html_a, html_b) >= 0.85
    report = assert_consistent(
        [
            _run([_step(1, "nav", digest="aa")]),
            _run([_step(1, "nav", digest="bb")]),
        ],
        _manifest(),
        htmls={1: (html_a, html_b)},
    )
    assert report.kind == "similarity"
    assert report.diff[0]["kind"] == "similarity"


def test_compare_mismatch():
    report = assert_consistent(
        [_run([_step(1, "nav"), _step(2, "click")]), _run([_step(1, "nav"), _step(2, "input")])],
        _manifest(),
    )
    assert report.kind == "mismatch"
    first = report.diff[0]
    assert first["seq"] == 2
    assert "action" in first["detail"]


def test_duration_never_compared():
    report = assert_consistent(
        [
            _run([_step(1, "nav", duration=100), _step(2, "click", duration=100)]),
            _run([_step(1, "nav", duration=1000), _step(2, "click", duration=1000)]),
        ],
        _manifest(),
    )
    assert report.kind == "exact"


def test_compare_requires_two_runs():
    with pytest.raises(ValueError):
        assert_consistent([_run([_step(1, "nav")])], _manifest())


def test_compare_step_count_mismatch_is_mismatch_not_crash():
    # 评审 Important-1：步数不齐应产出 mismatch，而非 IndexError / 假 exact
    report = assert_consistent(
        [_run([_step(1, "nav"), _step(2, "click")]), _run([_step(1, "nav")])],
        _manifest(),
    )
    assert report.kind == "mismatch"
    assert report.diff


def test_compare_requires_same_trace_ref():
    with pytest.raises(ValueError):
        assert_consistent(
            [_run([_step(1, "nav")], trace_ref="tr_a"), _run([_step(1, "nav")], trace_ref="tr_b")],
            _manifest(),
        )


def test_similarity_channel_checks_each_run(root):
    # 终审 Important-1：第 3..N 跑的 digest 差异必须各自过相似度，
    # 不得借用首两跑的判定放行（第 3 跑结构迥异 → mismatch）
    from forge_proto.trace import Manifest
    good_a = "<html><body><main><p>x</p><p>y</p></main></body></html>"
    good_b = "<html><body><main><p>1</p><p>2</p></main></body></html>"
    alien = "<html><body><table><tr><td>z</td></tr></table></body></html>"
    r1 = _run([_step(1, "nav", digest="aa")])
    r2 = _run([_step(1, "nav", digest="bb")])
    r3 = _run([_step(1, "nav", digest="cc")])
    report = assert_consistent([r1, r2, r3], _manifest(), htmls={1: (good_a, good_b, alien)})
    assert report.kind == "mismatch"


def test_similarity_channel_per_run_pass():
    from forge_proto.trace import Manifest
    good_a = "<html><body><main><p>x</p><p>y</p></main></body></html>"
    good_b = "<html><body><main><p>1</p><p>2</p></main></body></html>"
    good_c = "<html><body><main><p>3</p><p>4</p></main></body></html>"
    r1 = _run([_step(1, "nav", digest="aa")])
    r2 = _run([_step(1, "nav", digest="bb")])
    r3 = _run([_step(1, "nav", digest="cc")])
    report = assert_consistent([r1, r2, r3], _manifest(), htmls={1: (good_a, good_b, good_c)})
    assert report.kind == "similarity"
