"""golden 采集与值脱敏正反用例（docs/11 §5 T1.23 矩阵 + C8 占位符规范）。"""
import json
import re
import pytest
from forge_proto.golden import load_run_meta, validate_golden_dir
from forge_proto.trace import NetworkEntry
from forge_trace import Recorder, RecordingsStore, collect_golden, replay
from forge_trace.golden import (
    RedactionMap,
    redact_body,
    redact_url,
    stub_matcher,
    validate_golden_no_raw,
)
from fake_browser import FakeBrowser


def _record_sensitive(root):
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/search?q=张三&lang=zh&page=2")
    browser.emit_input("#q", "input||/q", "张三的搜索词")
    browser.feed_network(NetworkEntry(
        url="https://example.com/api", method="POST", status=200, mime_type="application/json",
        request_body=json.dumps({"user": "张三", "count": 3, "ok": True}),
        response_body=json.dumps({"items": ["张三", 1, False], "next": None}),
    ))
    browser.emit_click("#go", "b||/g")
    ref = rec.record.stop()
    return ref, store


def test_collect_golden_layout(root):
    ref, store = _record_sensitive(root)
    golden = collect_golden(ref, store=store, environment_fingerprint="fp-1")
    assert golden.is_dir()
    assert validate_golden_dir(golden) == []
    meta = load_run_meta(golden / "run_meta.json")
    assert meta.environment_fingerprint == "fp-1"
    assert meta.source_cert_run_id is None
    golden2 = collect_golden(ref, store=store, environment_fingerprint="fp-2", source_cert_run_id="cr-9")
    assert load_run_meta(golden2 / "run_meta.json").source_cert_run_id == "cr-9"


def test_redact_steps_value(root):
    ref, store = _record_sensitive(root)
    golden = collect_golden(ref, store=store, environment_fingerprint="fp")
    rows = [json.loads(l) for l in (golden / "expected_steps.ndjson").read_text(encoding="utf-8").splitlines() if l.strip()]
    input_row = next(r for r in rows if r["action"] == "input")
    assert re.fullmatch(r"⟦R:\d+⟧", input_row["value"])
    nav_row = next(r for r in rows if r["action"] == "nav")
    # nav 的 query 值占位符化，键与路径保留
    assert "q=" in nav_row["value"] and "⟦R:" in nav_row["value"]
    assert nav_row["value"].startswith("https://example.com/search?")
    assert "张三" not in nav_row["value"]


def test_redact_url_query():
    m = RedactionMap()
    out = redact_url("https://x.com/p?aa=1&bb=&cc=3", m)
    assert out.startswith("https://x.com/p?")
    parts = dict(p.split("=", 1) for p in out.split("?", 1)[1].split("&"))
    assert parts["bb"] == ""
    assert re.fullmatch(r"⟦R:\d+⟧", parts["aa"]) and re.fullmatch(r"⟦R:\d+⟧", parts["cc"])
    assert parts["aa"] != parts["cc"]


def test_redact_nested_json():
    m = RedactionMap()
    out = redact_body('{"a": {"b": ["x", 1, true, null]}}', m)
    doc = json.loads(out)
    assert re.fullmatch(r"⟦R:\d+⟧", doc["a"]["b"][0])
    assert doc["a"]["b"][1:] == [1, True, None]
    assert list(doc.keys()) == ["a"] and list(doc["a"].keys()) == ["b"]


def test_redact_nonjson_body():
    m = RedactionMap()
    out = redact_body("<html><body>整段非 JSON</body></html>", m)
    assert re.fullmatch(r"⟦R:\d+⟧", out)


def test_same_value_same_index(root):
    ref, store = _record_sensitive(root)
    golden = collect_golden(ref, store=store, environment_fingerprint="fp")
    stubs = json.loads((golden / "network_stubs.json").read_text(encoding="utf-8"))
    api_entry = next(e for e in stubs["entries"] if e["url"].endswith("/api"))
    body_user = json.loads(api_entry["request_body"])["user"]
    search_entry = next(e for e in stubs["entries"] if "/search" in e["url"])
    q_value = dict(p.split("=", 1) for p in search_entry["url"].split("?", 1)[1].split("&"))["q"]
    # 「张三」在 URL query 与 JSON body 中同值 → 同占位符
    assert body_user == q_value
    # 不同值不同占位符
    lang_value = dict(p.split("=", 1) for p in search_entry["url"].split("?", 1)[1].split("&"))["lang"]
    assert lang_value != q_value


def test_map_not_in_golden(root):
    ref, store = _record_sensitive(root)
    golden = collect_golden(ref, store=store, environment_fingerprint="fp")
    assert sorted(p.name for p in golden.iterdir()) == [
        "expected_steps.ndjson", "network_stubs.json", "run_meta.json",
    ]
    assert (store.root / "redaction_maps" / f"{ref}.json").exists()


def test_validate_no_raw_catches_leak(root):
    ref, store = _record_sensitive(root)
    golden = collect_golden(ref, store=store, environment_fingerprint="fp")
    assert validate_golden_no_raw(golden) == []

    # 篡改 steps value 为明文 → 指出位置
    steps_path = golden / "expected_steps.ndjson"
    rows = [json.loads(l) for l in steps_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        if r["action"] == "input":
            r["value"] = "张三的搜索词明文"
    steps_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    errors = validate_golden_no_raw(golden)
    assert errors and "expected_steps.ndjson" in errors[0]

    # 篡改 body 字符串标量为明文 → 指出位置
    stubs_path = golden / "network_stubs.json"
    doc = json.loads(stubs_path.read_text(encoding="utf-8"))
    doc["entries"][-1]["request_body"] = json.dumps({"user": "张三明文"})
    stubs_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    errors = validate_golden_no_raw(golden)
    assert any("network_stubs.json" in e for e in errors)


def test_stub_match_key_excludes_values(root):
    ref, store = _record_sensitive(root)
    golden = collect_golden(ref, store=store, environment_fingerprint="fp")
    from forge_trace.golden import load_stubs
    matcher = stub_matcher(load_stubs(golden))
    entry = NetworkEntry(url="x", method="GET", status=0, mime_type=None,
                         request_body=None, response_body=None)
    hit = matcher(entry, "GET", "https://example.com/search?q=别的词&lang=en&page=9")
    assert hit is not None and hit["method"] == "GET"
    assert matcher(entry, "GET", "https://example.com/other?x=1") is None


def test_replay_golden_uses_routes(root):
    ref, store = _record_sensitive(root)
    collect_golden(ref, store=store, environment_fingerprint="fp")
    browser = FakeBrowser()
    result = replay.run(ref, mode="golden", store=store, browser_factory=lambda: browser)
    assert all(r["ok"] for r in result.step_results)
    # 模拟页面网络：同键不同值的 query 也命中 stub（匹配键不含值）
    assert browser.route_hit("GET", "https://example.com/search?q=别的词&lang=en&page=9") is not None
    assert browser.route_hit("POST", "https://example.com/api") is not None
    assert browser.route_hits
    assert browser.direct_requests == []
