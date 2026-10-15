"""事件流聚合正反用例（docs/11 §3 C4）。"""
from forge_proto.format import write_ndjson
from forge_proto.trace import load_steps
from forge_trace.events import BrowserEvent, aggregate


def test_input_keystrokes_merge():
    evs = [
        BrowserEvent(kind="keystroke", selector="#q", anchor="input||/f/q", value="h", ts_ms=0),
        BrowserEvent(kind="keystroke", selector="#q", anchor="input||/f/q", value="e", ts_ms=100),
        BrowserEvent(kind="keystroke", selector="#q", anchor="input||/f/q", value="l", ts_ms=200),
        BrowserEvent(kind="keystroke", selector="#q", anchor="input||/f/q", value="l", ts_ms=300),
        BrowserEvent(kind="keystroke", selector="#q", anchor="input||/f/q", value="o", ts_ms=400),
        BrowserEvent(kind="blur", selector="#q", ts_ms=500),
    ]
    steps = aggregate(evs)
    assert len(steps) == 1
    s = steps[0]
    assert (s.action, s.target_selector, s.value, s.ts_offset) == ("input", "#q", "hello", 0)
    assert s.dom_anchor == "input||/f/q"


def test_input_flush_on_next_element():
    evs = [
        BrowserEvent(kind="keystroke", selector="#a", anchor="a|x|/p", value="x", ts_ms=0),
        BrowserEvent(kind="click", selector="#b", anchor="b||/q", ts_ms=100),
    ]
    steps = aggregate(evs)
    assert [(s.action, s.target_selector) for s in steps] == [("input", "#a"), ("click", "#b")]
    assert steps[0].dom_anchor == "a|x|/p"
    assert steps[1].dom_anchor == "b||/q"


def test_scroll_merges_until_idle():
    evs = [
        BrowserEvent(kind="scroll", selector="body", delta=100, ts_ms=0),
        BrowserEvent(kind="scroll", selector="body", delta=150, ts_ms=200),
        BrowserEvent(kind="scroll", selector="body", delta=50, ts_ms=1100),
    ]
    steps = aggregate(evs)
    assert len(steps) == 2
    assert steps[0].action == "scroll"
    assert steps[0].value == "250"
    assert steps[1].value == "50"


def test_idle_gap_becomes_wait():
    evs = [
        BrowserEvent(kind="click", selector="#a", anchor="a||/p", ts_ms=0),
        BrowserEvent(kind="click", selector="#b", anchor="b||/q", ts_ms=2500),
    ]
    steps = aggregate(evs)
    assert [s.action for s in steps] == ["click", "wait", "click"]
    assert steps[1].wait_condition == "anchor:#a"
    assert steps[1].target_selector is None
    assert [s.seq for s in steps] == [1, 2, 3]


def test_seq_and_ts_invariants(tmp_path):
    evs = [
        BrowserEvent(kind="nav", url="https://example.com/", ts_ms=0),
        BrowserEvent(kind="click", selector="#s", anchor="a||/s", ts_ms=300),
        BrowserEvent(kind="keystroke", selector="#q", value="py", ts_ms=350),
        BrowserEvent(kind="click", selector="#go", ts_ms=1200),
        BrowserEvent(kind="scroll", selector=None, delta=-40, ts_ms=4000),
    ]
    steps = aggregate(evs)
    assert steps[0].action == "nav" and steps[0].value == "https://example.com/"
    p = tmp_path / "steps.ndjson"
    write_ndjson(
        p,
        [
            {
                "seq": s.seq,
                "action": s.action,
                "target_selector": s.target_selector,
                "dom_anchor": s.dom_anchor,
                "value": s.value,
                "wait_condition": s.wait_condition,
                "ts_offset": s.ts_offset,
            }
            for s in steps
        ],
    )
    loaded = load_steps(p)
    assert [s.seq for s in loaded] == list(range(1, len(loaded) + 1))
    ts = [s.ts_offset for s in loaded]
    assert ts == sorted(ts)


def test_pending_flush_keeps_chronological_order():
    # 同元素 scroll 不冲刷 input 缓冲；scroll 间隙先行关闭 scroll 原子，
    # blur 再冲刷 input——原子须按时间重排，否则 ts_offset 递减违反冻结约束
    evs = [
        BrowserEvent(kind="keystroke", selector="#q", value="x", ts_ms=0),
        BrowserEvent(kind="scroll", selector="#q", delta=10, ts_ms=100),
        BrowserEvent(kind="scroll", selector="#q", delta=20, ts_ms=1000),
        BrowserEvent(kind="blur", selector="#q", ts_ms=1100),
    ]
    steps = aggregate(evs)
    ts = [s.ts_offset for s in steps]
    assert ts == sorted(ts)
    assert [s.action for s in steps] == ["input", "scroll", "scroll"]
