"""T1.73 url_read 单测：三 failure_class 判定 + 最小内容量断言（Review Focus 1 假覆盖防线）。

全部离线（monkeypatch httpx.get）；真网冒烟归档见 evidence/t1.73_smoke.json。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import pytest  # noqa: E402


def _load_main():
    d = Path(__file__).resolve().parent / "seed_blocks" / "url_read"
    spec = importlib.util.spec_from_file_location("url_read_main", d / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")


REAL_PAGE = """<html><head><title>Example Article Page</title></head><body>
<h1>Main Heading</h1>""" + "<p>Paragraph with substantive content. " * 30 + """</p>
<a href="https://example.com/next">next</a>
<a href="https://example.com/about">about</a>
</body></html>"""

JS_SHELL = ('<html><head><meta charset="utf-8"><script>window.__DATA__='
            + "x" * 5000 + ';</script></head><body><div id="root"></div></body></html>')

NO_TITLE_PAGE = "<html><head></head><body>" + "<p>plain text content here. " * 40 + "</p></body></html>"

CHALLENGE = ('<html><head><title>Just a moment...</title></head><body>'
             '<script>window._cf_chl_opt=1;</script>'
             '<p>captcha challenge page</p></body></html>')


@pytest.fixture()
def mod():
    return _load_main()


def test_read_ok(monkeypatch, mod):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=REAL_PAGE))
    out = mod.run({"url": "https://example.com/article"})
    assert out["ok"] is True
    assert set(out) == {"ok", "title", "text", "links", "content_bytes"}
    assert out["title"] == "Example Article Page"
    assert len(out["text"]) >= 200
    assert "https://example.com/next" in out["links"]
    assert out["content_bytes"] == len(REAL_PAGE.encode("utf-8"))


def test_http_error_403(monkeypatch, mod):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(status=403, text="forbidden"))
    out = mod.run({"url": "https://example.com/x"})
    assert out["ok"] is False and out["failure_class"] == "http_error"


def test_http_network_exception(monkeypatch, mod):
    def boom(*a, **kw):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "get", boom)
    out = mod.run({"url": "https://unreachable.invalid/"})
    assert out["ok"] is False and out["failure_class"] == "http_error"


def test_empty_content_js_shell(monkeypatch, mod):
    """Review Focus 1：JS 渲染页空壳（字节大但可读文本稀薄）不得伪装成功。"""
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=JS_SHELL))
    out = mod.run({"url": "https://example.com/app"})
    assert out["ok"] is False and out["failure_class"] == "empty_content"


def test_empty_content_thin_text(monkeypatch, mod):
    thin = "<html><head><title>Thin</title></head><body><p>short</p></body></html>"
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=thin))
    out = mod.run({"url": "https://example.com/thin"})
    assert out["ok"] is False and out["failure_class"] == "empty_content"


def test_empty_content_no_title(monkeypatch, mod):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=NO_TITLE_PAGE))
    out = mod.run({"url": "https://example.com/notitle"})
    assert out["ok"] is False and out["failure_class"] == "empty_content"


def test_blocked_challenge(monkeypatch, mod):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp(text=CHALLENGE))
    out = mod.run({"url": "https://example.com/protected"})
    assert out["ok"] is False and out["failure_class"] == "blocked"
