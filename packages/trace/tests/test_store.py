"""RecordingsStore 正反用例（docs/11 §3 C2）。"""
from forge_proto.trace import Manifest, NetworkEntry, NetworkLog, Step, validate_trace_dir
from forge_trace.store import RecordingsStore


def _manifest(site="example.com"):
    return Manifest(format_version="1.0", site=site, login_steps=(), time_sensitive_steps=())


def _steps():
    return (
        Step(
            seq=1, action="nav", target_selector=None, dom_anchor=None,
            value="https://example.com/", wait_condition=None, ts_offset=0,
        ),
        Step(
            seq=2, action="click", target_selector="#a", dom_anchor="a||/b/a",
            value=None, wait_condition=None, ts_offset=120,
        ),
    )


def _network():
    return NetworkLog(
        captured_at="2026-10-16T00:00:00Z",
        entries=(
            NetworkEntry(
                url="https://example.com/", method="GET", status=200,
                mime_type="text/html", request_body=None, response_body=None,
            ),
        ),
    )


def test_store_roundtrip(root):
    store = RecordingsStore(root)
    ref = store.allocate("example.com")
    store.save_trace(ref, _manifest(), _steps(), {1: "<html>one</html>", 2: "<html>two</html>"}, _network())

    d = root / "traces" / ref
    assert validate_trace_dir(d) == []
    assert (d / "snapshots" / "000001.html").read_text(encoding="utf-8") == "<html>one</html>"

    rec = store.get(ref)
    assert rec.trace_ref == ref
    assert rec.site == "example.com"
    assert rec.created_at
    assert rec.fragile_steps == ()
    assert rec.trace_dir == d


def test_store_trace_ref_unique(root):
    store = RecordingsStore(root)
    refs = {store.allocate("s") for _ in range(1000)}
    assert len(refs) == 1000
    assert all(r.startswith("tr_") for r in refs)


def test_annotate_persists(root):
    store = RecordingsStore(root)
    ref = store.allocate("example.com")
    store.save_trace(ref, _manifest(), _steps(), {1: "<a>", 2: "<b>"}, _network())

    store.annotate(ref, 2, "#a", "这是搜索框")
    store.annotate(ref, 2, "@snap:2", "点这个")

    rec = store.get(ref)
    assert len(rec.annotations) == 2
    first = rec.annotations[0]
    assert (first.trace_ref, first.step_seq, first.element_ref, first.hint) == (ref, 2, "#a", "这是搜索框")
    assert first.created_at


def test_mark_fragile_accumulates(root):
    store = RecordingsStore(root)
    ref = store.allocate("s")
    store.save_trace(ref, _manifest("s"), _steps(), {1: "<a>", 2: "<b>"}, _network())
    store.mark_fragile(ref, [2])
    store.mark_fragile(ref, [2, 5])
    assert store.get(ref).fragile_steps == (2, 5)


def test_save_trace_failure_leaves_no_directory(root):
    store = RecordingsStore(root)
    ref = store.allocate("example.com")
    # 步数 2 但只给 1 张快照 → proto 校验必失败
    try:
        store.save_trace(ref, _manifest(), _steps(), {1: "<html>one</html>"}, _network())
    except ValueError:
        pass
    else:
        raise AssertionError("save_trace 应当抛出 ValueError")
    assert not (root / "traces" / ref).exists()


def test_store_readable_from_foreign_thread(root):
    """回归（2026-10-18 时钟日）：Store 常由装配线程构造、由 FastAPI 请求线程读——
    sqlite 默认线程绑定会 ProgrammingError；连接须 check_same_thread=False。"""
    import threading

    store = RecordingsStore(root)
    store.save_trace("ref-x", _manifest(), _steps(), {1: "<a>", 2: "<b>"}, _network())
    out = {}

    def work():
        try:
            out["site"] = store.get("ref-x").site
        except Exception as exc:  # pragma: no cover - 失败路径即回归
            out["err"] = repr(exc)

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert out.get("site") == "example.com", out
