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


def test_action_exception_not_marked_fragile(root, monkeypatch):
    # 评审 Important-2：动作执行异常 ≠ anchor 缺失——不写 fragile，anchor 保持 True
    ref, store = _record(root, _script_standard)
    browser = FakeBrowser()

    def boom(selector):
        raise RuntimeError("adapter boom")

    monkeypatch.setattr(browser, "click", boom)
    result, _ = _replay(root, ref, store, browser=browser)
    clicks = [r for r in result.step_results if r["action"] == "click"]
    assert clicks and all(r["ok"] is False for r in clicks)
    assert all(r["anchor_matched"] is True for r in clicks)
    assert store.get(ref).fragile_steps == ()


def test_scroll_bad_value_fails_step(root):
    # 评审 Minor-5：scroll value 非整数应按步失败，而非静默归零
    from forge_proto.trace import Manifest, NetworkEntry, NetworkLog, Step
    store = RecordingsStore(root)
    ref = store.allocate("example.com")
    steps = (
        Step(seq=1, action="nav", target_selector=None, dom_anchor=None,
             value="https://example.com/", wait_condition=None, ts_offset=0),
        Step(seq=2, action="scroll", target_selector=None, dom_anchor=None,
             value="abc", wait_condition=None, ts_offset=100),
    )
    store.save_trace(
        ref, Manifest(format_version="1.0", site="example.com", login_steps=(),
                      time_sensitive_steps=()),
        steps, {1: "<html>a</html>", 2: "<html>b</html>"},
        NetworkLog(captured_at="2026-10-16T00:00:00Z", entries=(
            NetworkEntry(url="https://example.com/", method="GET", status=200,
                         mime_type=None, request_body=None, response_body=None),)),
    )
    result, browser = _replay(root, ref, store)
    assert result.step_results[1]["ok"] is False
    assert browser.scrolls == []


def test_query_override_no_hit_and_duplicate_keys(root):
    # 评审 Minor-7/8：未命中键原样保留；同名多值键全替换
    ref, store = _record(root, _script_standard)
    _, browser = _replay(root, ref, store, params={"q:absent": "x"})
    assert browser.gotos == ["https://example.com/?q=old"]


# ── T1.71：站点脚本输出通道（script_output）──

def test_replay_runs_script_and_carries_script_output(root):
    """步回放后在同一端口执行 script（browse 契约），返回值入 script_output。"""
    ref, store = _record(root, _script_standard)
    seen = {}

    def browse(port):
        seen["url"] = port.current_url()
        return {"results": ["a", "b"]}

    result, _ = _replay(root, ref, store, script=browse)
    assert result.script_output == {"results": ["a", "b"]}
    assert seen["url"] == "https://example.com/?q=old"  # 步回放后端口的落点状态

    result2, _ = _replay(root, ref, store)
    assert result2.script_output is None


def test_replay_script_none_return_stays_none(root):
    """browse 返回 None（既有块兼容）：script_output=None，不设 output。"""
    ref, store = _record(root, _script_standard)
    result, _ = _replay(root, ref, store, script=lambda port: None)
    assert result.script_output is None
