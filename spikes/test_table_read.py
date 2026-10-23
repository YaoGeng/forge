"""T1.74 table_read 单测：首表/索引表解析 + 无表如实失败（离线 monkeypatch httpx）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402


def _load_main():
    d = Path(__file__).resolve().parent / "seed_blocks" / "table_read"
    spec = importlib.util.spec_from_file_location("table_read_main", d / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")


PAGE_ONE_TABLE = """<html><head><title>Price List</title></head><body>
<p>intro paragraph</p>
<table>
  <tr><th>Name</th><th>Price</th></tr>
  <tr><td>A Light</td><td>51.77</td></tr>
  <tr><td>Tipping</td><td>20.00</td></tr>
</table>
</body></html>"""

PAGE_TWO_TABLES = """<html><head><title>Two</title></head><body>
<table><tr><th>T1H</th></tr><tr><td>t1r1</td></tr></table>
<table><tr><th>T2H</th></tr><tr><td>t2r1</td></tr></table>
</body></html>"""

NO_TABLE = "<html><head><title>NoTable</title></head><body><p>text only page</p></body></html>"


def test_first_table_headers_rows(monkeypatch):
    mod = _load_main()
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=PAGE_ONE_TABLE))
    out = mod.run({"url": "https://example.com/prices"})
    assert out["ok"] is True
    assert set(out) == {"ok", "headers", "rows"}
    assert out["headers"] == ["Name", "Price"]
    assert out["rows"] == [["A Light", "51.77"], ["Tipping", "20.00"]]


def test_index_selects_second_table(monkeypatch):
    mod = _load_main()
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=PAGE_TWO_TABLES))
    out = mod.run({"url": "https://example.com/x", "index": 1})
    assert out["ok"] is True
    assert out["headers"] == ["T2H"]
    assert out["rows"] == [["t2r1"]]


def test_index_out_of_range_no_table(monkeypatch):
    mod = _load_main()
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=PAGE_ONE_TABLE))
    out = mod.run({"url": "https://example.com/x", "index": 5})
    assert out["ok"] is False and out["failure_class"] == "no_table"


def test_page_without_table_no_table(monkeypatch):
    mod = _load_main()
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=NO_TABLE))
    out = mod.run({"url": "https://example.com/none"})
    assert out["ok"] is False and out["failure_class"] == "no_table"


def test_http_error(monkeypatch):
    mod = _load_main()
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(status=500, text="boom"))
    out = mod.run({"url": "https://example.com/err"})
    assert out["ok"] is False and out["failure_class"] == "http_error"
