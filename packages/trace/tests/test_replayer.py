"""Replayer local 模式正反用例（docs/11 §5 T1.22 矩阵 + C9/C11）。"""
import pytest
from forge_trace import Recorder, RecordingsStore, replay
from fake_browser import FakeBrowser


def _record(root, script):
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    script(browser)
    ref = rec.record.stop()
    return ref, store


def _script_standard(browser):
    browser.emit_nav("https://example.com/?q=old")
    browser.emit_click("#a", "a||/a")
    browser.emit_input("#q", "input||/q", "hello")
    browser.emit_click("#go", "b||/g")


def _replay(root, ref, store, browser=None, **kw):
    browser = browser or FakeBrowser()
    result = replay.run(ref, store=store, browser_factory=lambda: browser, **kw)
    return result, browser


def test_replay_local_drives_all_steps(root):
    ref, store = _record(root, _script_standard)
    result, _ = _replay(root, ref, store)
    assert len(result.step_results) == 4
    assert all(r["ok"] for r in result.step_results)
    assert all(r["anchor_matched"] for r in result.step_results)
    assert [r["seq"] for r in result.step_results] == [1, 2, 3, 4]
    assert result.mode == "local" and result.trace_ref == ref


def test_replay_uses_recorded_selector(root):
    ref, store = _record(root, _script_standard)
    _, browser = _replay(root, ref, store)
    # 点击走录制 selector，不经 anchor 重算
    assert browser.clicks == ["#a", "#go"]
    assert browser.gotos == ["https://example.com/?q=old"]
    assert browser.fills == [("#q", "hello")]


def test_params_override_input_and_query(root):
    ref, store = _record(root, _script_standard)
    _, browser = _replay(root, ref, store, params={"3": "新值", "q:q": "py"})
    # input 步（seq=3）value 覆盖；nav 步 q 参数覆盖
    assert browser.fills == [("#q", "新值")]
    assert "q=py" in browser.gotos[0]
    assert "q=old" not in browser.gotos[0]


def test_anchor_missing_flags_fragile(root):
    ref, store = _record(root, _script_standard)
    browser = FakeBrowser()
    browser.hidden.add("#a")  # 步 2 目标元素缺失
    result, _ = _replay(root, ref, store, browser=browser)
    step2 = result.step_results[1]
    assert step2["anchor_matched"] is False
    assert step2["ok"] is False
    assert 2 in store.get(ref).fragile_steps


def test_mode_unknown_rejected(root):
    ref, store = _record(root, _script_standard)
    with pytest.raises(ValueError):
        replay.run(ref, mode="magic", store=store, browser_factory=FakeBrowser)


def test_mode_structured_not_implemented(root):
    ref, store = _record(root, _script_standard)
    with pytest.raises(NotImplementedError):
        replay.run(ref, mode="structured", store=store, browser_factory=FakeBrowser)
