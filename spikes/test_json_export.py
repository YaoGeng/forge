"""T1.75 json_export 单测：分号行集 → JSON 文件（csv_export 同款目录/分号惯例）。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_main():
    d = Path(__file__).resolve().parent / "seed_blocks" / "json_export"
    spec = importlib.util.spec_from_file_location("json_export_main", d / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _target(out: str) -> Path:
    return Path(tempfile.gettempdir()) / "forge-blocks" / out


def test_rows_to_json_file():
    mod = _load_main()
    out = mod.run({"rows": "条目甲;条目乙;条目丙", "out": "t175_report.json"})
    assert out == {"ok": True, "file": "t175_report.json", "rows": 3}
    p = _target("t175_report.json")
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == {"rows": ["条目甲", "条目乙", "条目丙"]}


def test_empty_rows_still_writes_file():
    mod = _load_main()
    out = mod.run({"rows": "", "out": "t175_empty.json"})
    assert out == {"ok": True, "file": "t175_empty.json", "rows": 0}
    p = _target("t175_empty.json")
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == {"rows": []}


def test_default_out_name():
    mod = _load_main()
    out = mod.run({"rows": "a"})
    assert out["file"] == "report.json" and out["ok"] is True and out["rows"] == 1
    assert _target("report.json").exists()
