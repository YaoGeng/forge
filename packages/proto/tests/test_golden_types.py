"""golden 三件套类型与校验器测试（M07 §4 冻结编码）。"""
import json
from pathlib import Path

import pytest

from forge_proto import FormatError, load_run_meta, validate_golden_dir
from test_trace_types import CORPUS, _build_trace_dir, _step_line  # noqa: F401


def test_load_run_meta_ok():
    meta = load_run_meta_text({
        "environment_fingerprint": "win11-chrome1243",
        "captured_at": "2026-10-15T01:00:00+00:00",
        "source_cert_run_id": "run_123",
    })
    assert meta.environment_fingerprint == "win11-chrome1243"
    assert meta.source_cert_run_id == "run_123"


def load_run_meta_text(doc: dict):
    import tempfile
    from pathlib import Path as _P
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(doc, f)
    finally:
        f.close()  # 先落盘再读（Windows 缓冲）
    return load_run_meta(_P(f.name))


def test_run_meta_missing_field():
    with pytest.raises(FormatError):
        load_run_meta_text({"environment_fingerprint": "fp"})


def test_validate_golden_dir_ok(tmp_path):
    g = _build_golden_dir(tmp_path)
    assert validate_golden_dir(g) == []


def _build_golden_dir(root: Path) -> Path:
    g = root / "golden"
    g.mkdir(parents=True)
    (g / "run_meta.json").write_text(json.dumps({
        "environment_fingerprint": "fp",
        "captured_at": "2026-10-15T01:00:00+00:00",
        "source_cert_run_id": None,
    }), encoding="utf-8")
    (g / "expected_steps.ndjson").write_text(_step_line(seq=1) + "\n", encoding="utf-8")
    (g / "network_stubs.json").write_text(json.dumps({
        "captured_at": "2026-10-15T01:00:00+00:00", "entries": []}), encoding="utf-8")
    return g


def test_validate_golden_dir_missing_stubs(tmp_path):
    g = _build_golden_dir(tmp_path)
    (g / "network_stubs.json").unlink()
    errors = validate_golden_dir(g)
    assert any("network_stubs" in e for e in errors)


def test_golden_expected_steps_invalid(tmp_path):
    g = _build_golden_dir(tmp_path)
    (g / "expected_steps.ndjson").write_text("{broken\n", encoding="utf-8")
    errors = validate_golden_dir(g)
    assert any("expected_steps" in e for e in errors)


def test_corpus_fixtures_exist():
    # 语料目录为 Schema 对齐测试的稳定输入，缺失即测试基建损坏
    assert (CORPUS / "valid" / "trace" / "manifest.yaml").exists()
    assert (CORPUS / "valid" / "golden" / "run_meta.json").exists()
