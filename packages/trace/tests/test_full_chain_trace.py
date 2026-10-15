"""MS-1D 全链单测缩影：录制→回放×2→一致性→golden→脱敏校验→TestRunner（不触网）。"""
from forge_proto.golden import validate_golden_dir
from forge_proto.trace import load_manifest
from forge_trace import (
    RecordingsStore,
    Recorder,
    TestRunner,
    assert_consistent,
    collect_golden,
    replay,
    validate_golden_no_raw,
)
from fake_browser import FakeBrowser


def test_full_chain_record_replay_golden_assert(root, tmp_path):
    # 1. 录制
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    browser.emit_nav("https://example.com/search?q=hello")
    browser.emit_click("#a", "a||/a")
    browser.emit_input("#q", "input||/q", "hello world")
    browser.emit_click("#go", "b||/g")
    ref = rec.record.stop()

    # 2. 回放 ×2 + 一致性（同 html 演变 → exact）
    b1, b2 = FakeBrowser(), FakeBrowser()
    r1 = replay.run(ref, store=store, browser_factory=lambda: b1)
    r2 = replay.run(ref, store=store, browser_factory=lambda: b2)
    manifest = load_manifest(root / "traces" / ref / "manifest.yaml")
    report = assert_consistent([r1, r2], manifest)
    assert report.kind == "exact"

    # 3. golden 采集 + 脱敏校验
    golden = collect_golden(ref, store=store, environment_fingerprint="fp-fullchain")
    assert validate_golden_dir(golden) == []
    assert validate_golden_no_raw(golden) == []

    # 4. TestRunner：schema 通道（正/反）
    schema_yaml = tmp_path / "test_schema.yaml"
    schema_yaml.write_text(
        "assertion: schema\n"
        "expect:\n"
        "  type: object\n"
        "  required: [html]\n"
        "  properties:\n"
        "    html: {type: string}\n",
        encoding="utf-8",
    )
    assert TestRunner.check({"html": b1.html}, schema_yaml).ok
    assert not TestRunner.check({}, schema_yaml).ok

    # 5. TestRunner：golden_similarity 通道（同构 html → passed）
    golden_yaml = tmp_path / "test_golden.yaml"
    golden_yaml.write_text("assertion: golden_similarity\nthreshold: 0.85\n", encoding="utf-8")
    verdict = TestRunner.check({"html_a": b1.html, "html_b": b2.html}, golden_yaml)
    assert verdict.ok and verdict.assertion == "golden_similarity"

    # 6. fragile 未污染
    assert store.get(ref).fragile_steps == ()
