"""Recorder 装配正反用例（docs/11 §5 T1.21b 矩阵 + stop 空守卫）。"""
import pytest
from forge_proto.trace import load_manifest, load_network, load_steps, validate_trace_dir
from forge_trace import Recorder, RecordingsStore
from fake_browser import FakeBrowser


def _recorder(root, browser):
    return Recorder(RecordingsStore(root), lambda: browser)


def test_record_stop_produces_valid_trace(root):
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    session = rec.record.start("example.com")
    assert session.host == "example.com"

    browser.emit_nav("https://example.com/")
    browser.emit_click("#search", "a||/s")
    browser.emit_input("#q", "input||/f/q", "hello")
    browser.emit_click("#go", "b||/g")
    ref = rec.record.stop()

    d = root / "traces" / ref
    assert validate_trace_dir(d) == []
    steps = load_steps(d / "steps.ndjson")
    assert [s.action for s in steps] == ["nav", "click", "input", "click"]
    names = sorted(p.name for p in (d / "snapshots").iterdir())
    assert names == ["000001.html", "000002.html", "000003.html", "000004.html"]


def test_snapshot_taken_at_flush_boundary(root):
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    rec.record.start("example.com")

    browser.emit_nav("https://example.com/")  # 步 1 定案：nav 落地页
    browser.html = "<html>state-1</html>"
    browser.emit_click("#a", "a||/a")  # 步 2 定案时点页面 = state-1
    browser.html = "<html>state-2</html>"
    browser.emit_input("#q", "input||/q", "x")  # 步 3 定案时点页面 = state-2
    browser.html = "<html>final</html>"
    browser.emit_click("#go", "b||/g")  # 步 4 定案时点页面 = final
    ref = rec.record.stop()

    snaps = root / "traces" / ref / "snapshots"
    assert "state-1" in (snaps / "000002.html").read_text(encoding="utf-8")
    assert "state-2" in (snaps / "000003.html").read_text(encoding="utf-8")
    assert "final" in (snaps / "000004.html").read_text(encoding="utf-8")


def test_network_captured(root):
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/a")
    browser.emit_nav("https://example.com/b")
    ref = rec.record.stop()
    log = load_network(root / "traces" / ref / "network.json")
    assert len(log.entries) >= 2


def test_manifest_fields(root):
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    rec.record.start("mysite.example")
    browser.emit_nav("https://mysite.example/")
    ref = rec.record.stop()
    m = load_manifest(root / "traces" / ref / "manifest.yaml")
    assert m.format_version == "1.0"
    assert m.site == "mysite.example"
    assert m.login_steps == ()
    assert m.time_sensitive_steps == ()


def test_recordings_row_written(root):
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/")
    ref = rec.record.stop()
    row = store.get(ref)
    assert row.trace_ref == ref
    assert row.site == "example.com"
    assert row.created_at


def test_annotate_via_recorder(root):
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/")
    browser.emit_click("#a", "a||/a")
    ref = rec.record.stop()
    rec.record.annotate(ref, 2, "#a", "这是搜索按钮")
    ann = store.get(ref).annotations[0]
    assert (ann.trace_ref, ann.step_seq, ann.element_ref, ann.hint) == (ref, 2, "#a", "这是搜索按钮")


def test_double_start_rejected(root):
    rec = _recorder(root, FakeBrowser())
    rec.record.start("example.com")
    with pytest.raises(RuntimeError):
        rec.record.start("other.example")


def test_stop_without_start_rejected(root):
    rec = _recorder(root, FakeBrowser())
    with pytest.raises(RuntimeError):
        rec.record.stop()


def test_stop_with_no_steps_rejected(root):
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    rec.record.start("example.com")
    with pytest.raises(RuntimeError):
        rec.record.stop()


def test_input_snapshot_at_flush_trigger_not_first_keystroke(root):
    # Review Focus 1（评审 Important-1）：keystroke 逐步到达、input 在后续 click 定案；
    # 快照必须取定案事件（click）时点的页面，而非首个 keystroke 时的页面
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/")
    browser.html = "<html>before-typing</html>"
    browser.emit("keystroke", selector="#q", anchor="input||/q", value="h")
    browser.emit("keystroke", selector="#q", anchor="input||/q", value="i")
    browser.html = "<html>flush-moment</html>"
    browser.emit_click("#go", "b||/g")  # 异元素 click 冲刷 input —— 定案时点
    ref = rec.record.stop()
    d = root / "traces" / ref
    steps = load_steps(d / "steps.ndjson")
    input_seq = next(s.seq for s in steps if s.action == "input")
    input_snap = (d / "snapshots" / f"{input_seq:06d}.html").read_text(encoding="utf-8")
    assert "flush-moment" in input_snap
    assert "before-typing" not in input_snap


def test_network_tail_drained_at_stop(root):
    # 评审 Important-3：最后事件之后到达的网络必须经 stop 收口入 network.json
    from forge_proto.trace import NetworkEntry
    browser = FakeBrowser()
    rec = _recorder(root, browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/")
    browser.emit_click("#go", "b||/g")
    browser.feed_network(NetworkEntry(
        url="https://cdn.example.com/late.js", method="GET", status=200,
        mime_type="application/javascript", request_body=None, response_body=None,
    ))
    ref = rec.record.stop()
    log = load_network(root / "traces" / ref / "network.json")
    urls = [e.url for e in log.entries]
    assert "https://cdn.example.com/late.js" in urls


def test_emit_input_delegates_to_keystrokes_and_blur():
    # 评审 Minor-4：假体的 emit_input 应模拟真实注入脚本形态（keystroke* + blur），
    # 使 Recorder 的延迟冲刷路径经门面被走到
    browser = FakeBrowser()
    seen = []
    browser.install_hook(seen.append)
    browser.emit_input("#q", "input||/q", "hi")
    assert [e.kind for e in seen] == ["keystroke", "keystroke", "blur"]
    assert "".join(e.value or "" for e in seen if e.kind == "keystroke") == "hi"


def test_start_rejects_empty_host(root):
    # 评审 Minor-6：空 host 应在 start 即拒绝，而非落盘时才报
    rec = _recorder(root, FakeBrowser())
    with pytest.raises(ValueError):
        rec.record.start("")


def test_hook_firing_during_install(root):
    # 评审 Minor-7：端口在 install_hook 内同步回放队列事件时不应崩溃
    from forge_trace.events import BrowserEvent

    class EagerBrowser(FakeBrowser):
        def install_hook(self, on_event):
            super().install_hook(on_event)
            on_event(BrowserEvent(kind="nav", url="https://example.com/", ts_ms=0))

    browser = EagerBrowser()
    rec = _recorder(root, browser)
    rec.record.start("example.com")
    browser.emit_click("#a", "a||/a")
    ref = rec.record.stop()
    steps = load_steps(root / "traces" / ref / "steps.ndjson")
    assert [s.action for s in steps] == ["nav", "click"]


def test_fake_browser_satisfies_port_protocol():
    # 评审 Minor-8：假体与端口面的漂移应显式失败
    from forge_trace import BrowserPort
    assert isinstance(FakeBrowser(), BrowserPort)
