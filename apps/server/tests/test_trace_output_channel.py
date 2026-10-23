"""T1.71 站点块数据输出通道：browse 返回值 → replay.script_output → RunOutcome.output
→ ChainRunner context（trace 块与 python 块同语义，docs/15 T1.71）。

口径（Review Focus 3）：golden 对拍不比较 output——script_output 不进相似度/一致性
判定；既有块（browse 返回 None / 未注册 script）output=None，行为与改造前一致。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fake_browser import FakeBrowser
from forge_trace import Recorder, RecordingsStore, collect_golden

from forge_server.chain import BindingError, ChainRunner
from forge_server.sandbox import RunOutcome, TraceRunner

_ROOT = Path(__file__).resolve().parents[3]
import sys  # noqa: E402

for _p in (_ROOT / "spikes",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from test_sandbox_c2 import make_block_dir  # noqa: E402


class InnerTextBrowser(FakeBrowser):
    """回放面假体 + inner_text 桩（T1.72 契约同款消费面）。"""

    def __init__(self, text: str = "标题一\n标题二"):
        super().__init__()
        self._text = text
        self.inner_texts: list[str] = []

    def inner_text(self, selector: str) -> str:
        self.inner_texts.append(selector)
        return self._text


def _browse(port):
    port.wait_selector("li", 5000)
    lines = [ln.strip() for ln in port.inner_text("li").splitlines() if ln.strip()]
    return {"results": lines}


def _make_recording_with_block(root, tmp_path):
    """两步轨迹录制 + 最小合法块目录 → (ref, store, block_dir)。"""
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/list")
    browser.emit_click("#a", "a||/a")
    ref = rec.record.stop()
    block = make_block_dir(tmp_path, name="probe_out")
    return ref, store, block


# ── 通道贯通：wire_chain_runner 组装 + ChainRunner bindings 消费 ──


def test_output_flows_through_chain_runner_wiring(tmp_path):
    """假 trace 工厂返回带 output 的 RunOutcome：bindings 取 上游.出参键 → context 命中。"""
    from product_path import wire_chain_runner

    data = {"results": [{"title": "t1", "url": "u1"}, {"title": "t2", "url": "u2"}]}

    class FakeTracePort:
        def run_once(self, ref, params=None, *, mode="local", **kw):
            if ref == "ref-up":
                return RunOutcome(mode=mode, ok=True, output=dict(data))
            return RunOutcome(mode=mode, ok=True, output={"echo": params.get("src")})

    app = SimpleNamespace(state=SimpleNamespace(chain_runner=None))
    store = tmp_path / "store"
    store.mkdir()
    routes = wire_chain_runner(app, store, ["up", "down"],
                                adapters={"up": "trace", "down": "trace"},
                                trace_runner_factory=lambda td: FakeTracePort())
    assert set(routes) == {"up", "down"}
    out = app.state.chain_runner([
        {"block": "up", "params": {}},
        {"block": "down", "params": {}, "bindings": {"src": "up.results"}},
    ])
    assert out["ok"] is True
    assert out["context"]["up"]["results"] == data["results"]
    assert out["context"]["down"]["echo"] == data["results"]


def test_binding_missing_output_key_raises(tmp_path):
    """输出键断链（Review Focus 2）：下游绑定的键不在上游 output → BindingError。"""
    from product_path import wire_chain_runner

    class FakeTracePort:
        def run_once(self, ref, params=None, *, mode="local", **kw):
            return RunOutcome(mode=mode, ok=True, output={"results": [1]})

    app = SimpleNamespace(state=SimpleNamespace(chain_runner=None))
    store = tmp_path / "store"
    store.mkdir()
    wire_chain_runner(app, store, ["up", "down"],
                      adapters={"up": "trace", "down": "trace"},
                      trace_runner_factory=lambda td: FakeTracePort())
    with pytest.raises(BindingError):
        app.state.chain_runner([
            {"block": "up", "params": {}},
            {"block": "down", "params": {}, "bindings": {"src": "up.nonexistent"}},
        ])


# ── 真实 TraceRunner 路径：script_output → RunOutcome.output ──


def test_trace_runner_maps_script_output(root, tmp_path):
    """TraceRunner 注册 scripts：local 模式 browse 返回 dict → outcome.output 贯通。"""
    ref, store, block = _make_recording_with_block(root, tmp_path)
    browser = InnerTextBrowser()
    runner = TraceRunner(store, lambda: browser, block_dirs={ref: block},
                         scripts={ref: _browse})
    outcome = runner.run_once(ref, {}, mode="local")
    assert outcome.ok is True
    assert outcome.output == {"results": ["标题一", "标题二"]}
    assert browser.inner_texts == ["li"]


def test_golden_mode_does_not_judge_output(root, tmp_path):
    """golden 对拍不比较 output（Review Focus 3）：判定只看步结果，output 只透传。"""
    ref, store, block = _make_recording_with_block(root, tmp_path)
    collect_golden(ref, store=store, environment_fingerprint="fp-t171")
    browser = InnerTextBrowser()
    runner = TraceRunner(store, lambda: browser, block_dirs={ref: block},
                         scripts={ref: _browse})
    outcome = runner.run_once(ref, {}, mode="golden")
    assert outcome.ok is True
    assert outcome.output == {"results": ["标题一", "标题二"]}


def test_script_absent_or_none_keeps_output_none(root, tmp_path):
    """既有块兼容：未注册 script / browse 返回 None → output=None（改造前行为）。"""
    ref, store, block = _make_recording_with_block(root, tmp_path)
    r1 = TraceRunner(store, FakeBrowser, block_dirs={ref: block})
    assert r1.run_once(ref, {}, mode="local").output is None
    r2 = TraceRunner(store, FakeBrowser, block_dirs={ref: block},
                     scripts={ref: lambda port: None})
    assert r2.run_once(ref, {}, mode="local").output is None


def test_script_exception_fails_run_honestly(root, tmp_path):
    """脚本抽取崩溃如实失败：ChainRunner 归因 env_error，不伪装成功。"""
    ref, store, block = _make_recording_with_block(root, tmp_path)

    def broken(port):
        raise RuntimeError("抽取崩了")

    runner = TraceRunner(store, FakeBrowser, block_dirs={ref: block},
                         scripts={ref: broken})
    chain = ChainRunner({"up": (runner, ref)})
    out = chain.execute([{"block": "up", "params": {}}])
    assert out["ok"] is False
    assert out["steps"][0]["failure_class"] == "env_error"
    assert "抽取崩了" in out["steps"][0]["error"]


def test_wire_loads_scripts_from_manifest(tmp_path):
    """product_path 装载：trace 块的 manifest script 引用 → {ref: callable}。"""
    from product_path import load_trace_scripts

    scripts = load_trace_scripts({"bing_search": "tr_bs", "csv_export": "csv"})
    assert set(scripts) == {"tr_bs"}  # python 块（csv_export）无 script
    assert callable(scripts["tr_bs"])
