"""T1.72 契约测试：11 站点脚本结构化返回（输出键 pin，Review Focus 2）。

假 port 模式统一：goto/wait_selector 只记账；snapshot_html/inner_text 返回固定
HTML/JSON 片段。断言每脚本 browse 返回 dict 且键集合与 docs/15 T1.72 表一致。
login_demo_probe 为遗留 C1 块不改造（browse 返回 None）。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


class FakePort:
    def __init__(self, html: str = "", text: str = ""):
        self.html = html
        self.text = text
        self.gotos: list[str] = []
        self.fills: list[tuple[str, str]] = []
        self.presses: list[str] = []
        self.snapshots = 0

    def goto(self, url):
        self.gotos.append(url)

    def wait_selector(self, selector, timeout_ms=5000):
        return True

    def fill(self, selector, value):
        self.fills.append((selector, value))

    def press(self, key):
        self.presses.append(key)

    def inner_text(self, selector):
        return self.text

    def snapshot_html(self):
        self.snapshots += 1
        return self.html


def _mod(name):
    return importlib.import_module(f"site_scripts.{name}")


def _browse(name, html="", text=""):
    port = FakePort(html, text)
    out = _mod(name).browse(port)
    assert isinstance(out, dict), f"{name}.browse 须返回 dict，现 {type(out)}"
    return out, port


# ── 固定片段（真实站点类名）──

BING = """
<html><body><ol id="b_results">
<li class="b_algo"><h2><a href="https://a.example.com/x">First Result</a></h2></li>
<li class="b_algo"><h2><a href="https://b.example.com/y">Second Result</a></h2></li>
</ol></body></html>
"""
HN = """
<html><body><div class="search-results">
<span class="story_title"><a href="https://news.y.example/1">Py Story</a></span>
<span class="story_title"><a href="https://news.y.example/2">Node Story</a></span>
</div></body></html>
"""
BOOKS = """
<html><body>
<article class="product_pod"><h3><a title="A Light in the Attic">A Light in the Attic</a></h3>
<p class="price_color">£51.77</p></article>
<article class="product_pod"><h3><a title="Tipping the Lamp">Tipping the Lamp</a></h3>
<p class="price_color">£20.00</p></article>
</body></html>
"""
BOOK_DETAIL_HTML = ""
BOOK_DETAIL_TEXT = "A Light in the Attic\n£51.77\nIn stock (22 available)"
QUOTES = """
<html><body>
<div class="quote"><span class="text">“The quote one.”</span><small class="author">Author One</small></div>
<div class="quote"><span class="text">“The quote two.”</span><small class="author">Author Two</small></div>
</body></html>
"""
BAIDU = "<html><head><title>百度一下</title></head><body><div id='kw'></div>热搜甲</body></html>"
GH_REPO = '{"full_name": "microsoft/vscode", "stargazers_count": 150000, "description": "Visual Studio Code"}'
GH_SEARCH = ('{"items": [{"full_name": "microsoft/playwright", "stargazers_count": 60000},'
             '{"full_name": "other/rp", "stargazers_count": 12000}]}')
NPM = '{"name": "pytest", "version": "8.0.0", "description": "pytest framework"}'
HTTPBIN = '{"args": {"echo": "hello-forge"}, "headers": {"User-Agent": "x"}, "url": "https://httpbin.org/get"}'
POSTS = '{"userId": 1, "id": 1, "title": "sunt aut", "body": "quia et exercitationem"}'


def test_bing_search_contract():
    out, port = _browse("bing_search", BING)
    assert set(out) == {"results"}
    assert len(out["results"]) >= 2
    for item in out["results"]:
        assert set(item) == {"title", "url"}
    assert out["results"][0]["url"].startswith("https://")
    assert port.gotos  # 脚本自身导航仍在（录制/回放同路径）


def test_hn_search_probe_contract():
    out, _ = _browse("hn_search_probe", HN)
    assert set(out) == {"hits"}
    assert len(out["hits"]) >= 1
    for item in out["hits"]:
        assert set(item) == {"title", "url"}


def test_books_list_contract():
    out, _ = _browse("books_list", BOOKS)
    assert set(out) == {"books"}
    assert len(out["books"]) >= 2
    for item in out["books"]:
        assert set(item) == {"title", "price"}
    assert out["books"][0]["price"].startswith("£")


def test_book_detail_contract():
    out, _ = _browse("book_detail", text=BOOK_DETAIL_TEXT)
    assert set(out) == {"title", "price", "stock"}
    assert out["title"] == "A Light in the Attic"
    assert out["price"].startswith("£")


@pytest.mark.parametrize("name", ["quotes_list", "quotes_paged"])
def test_quotes_contract(name):
    out, _ = _browse(name, QUOTES)
    assert set(out) == {"quotes"}
    assert len(out["quotes"]) >= 2
    for item in out["quotes"]:
        assert set(item) == {"text", "author"}


def test_baidu_home_watch_contract(tmp_path, monkeypatch):
    mod = _mod("baidu_home_watch")
    monkeypatch.setattr(mod, "BASELINE", tmp_path / "baseline.json")
    out1, _ = _browse("baidu_home_watch", BAIDU)
    assert set(out1) == {"snapshot_changed", "headline"}
    assert out1["snapshot_changed"] is False  # 首跑建基线
    assert mod.BASELINE.exists()
    out2, _ = _browse("baidu_home_watch", BAIDU)
    assert out2["snapshot_changed"] is False  # 同内容不变
    mod2 = _mod("baidu_home_watch")
    out3, _ = _browse("baidu_home_watch", BAIDU.replace("热搜甲", "热搜乙"))
    assert out3["snapshot_changed"] is True  # 内容漂移如实上报


def test_github_repo_read_contract():
    out, _ = _browse("github_repo_read", GH_REPO)
    assert set(out) == {"repo", "stars", "description"}
    assert out["repo"] == "microsoft/vscode" and out["stars"] == 150000


def test_github_search_contract():
    out, _ = _browse("github_search", GH_SEARCH)
    assert set(out) == {"items"}
    assert len(out["items"]) == 2
    assert out["items"][0] == {"full_name": "microsoft/playwright", "stars": 60000}


def test_npm_pkg_meta_contract():
    out, _ = _browse("npm_pkg_meta", NPM)
    assert set(out) == {"name", "version", "description"}
    assert out["name"] == "pytest" and out["version"] == "8.0.0"


@pytest.mark.parametrize("name,fixture", [
    ("httpbin_echo", HTTPBIN), ("jsonplaceholder_posts", POSTS),
])
def test_api_payload_contract(name, fixture):
    out, _ = _browse(name, fixture)
    assert set(out) == {"payload_keys", "body_head"}
    assert isinstance(out["payload_keys"], list) and out["payload_keys"]
    assert out["body_head"]


def test_login_demo_probe_legacy_untouched():
    """遗留 C1 块不改造：无站点脚本文件（输出通道对其不生效，认证/注册零影响）。"""
    import importlib.util

    assert importlib.util.find_spec("site_scripts.login_demo_probe") is None
