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
