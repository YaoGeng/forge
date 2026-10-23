"""table_read：通用表格读取（s4 文本抽取；python/httpx，best_effort 强制——A.9 R2）。

取页段与 seed_blocks/url_read/main.py 同源复制（python 块互相独立，跨目录 import
不成立——docs/15 T1.74 注记）；表格解析 stdlib html.parser，无表/越界如实 no_table。
"""
import httpx
from html.parser import HTMLParser

# ── 取页段（同源：url_read/main.py，T1.73）──
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _fetch(url: str):
    """同源复制的取页+http/challenge 判定；返回 (body | None, failure_class | None)。"""
    try:
        resp = httpx.get(url, timeout=20.0, follow_redirects=True,
                         headers={"User-Agent": _UA})
    except (httpx.HTTPError, OSError):
        return None, "http_error"
    if resp.status_code >= 400:
        return None, "http_error"
    low = resp.text[:20000].lower()
    if "cf-chl" in low or "captcha" in low:
        return None, "blocked"
    return resp.text, None


class _Tables(HTMLParser):
    """收集全部 <table> 的 headers（首行 th）与数据行（td）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self._cur: dict | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._header_row = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._cur = {"headers": [], "rows": []}
        elif self._cur is not None and tag == "tr":
            self._row = []
            self._header_row = not self._cur["headers"]
        elif self._row is not None and tag in ("th", "td"):
            self._cell = []
            self._header_row = self._header_row and tag == "th"

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data.strip())

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self._cell is not None:
            self._row.append(" ".join(c for c in self._cell if c))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._cur is not None:
            if self._header_row and not self._cur["headers"]:
                self._cur["headers"] = self._row
            elif self._row:
                self._cur["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._cur is not None:
            self.tables.append(self._cur)
            self._cur = None


def _fail(failure_class: str) -> dict:
    return {"ok": False, "failure_class": failure_class, "headers": [], "rows": []}


def run(params: dict) -> dict:
    body, failure = _fetch(str(params.get("url", "")))
    if failure:
        return _fail(failure)
    try:
        index = int(params.get("index", 0))
    except (TypeError, ValueError):
        return _fail("no_table")
    parser = _Tables()
    parser.feed(body)
    if index < 0 or index >= len(parser.tables):
        return _fail("no_table")
    t = parser.tables[index]
    return {"ok": True, "headers": t["headers"], "rows": t["rows"]}
