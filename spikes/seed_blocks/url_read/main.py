"""url_read：通用网页只读（s4 文本抽取；python/httpx，best_effort 强制——A.9 R2）。

JS 渲染页/挑战页如实 run_failed（ok:false + failure_class），不得伪装成功（PRD §9.3）。
零第三方解析依赖：httpx 取页 + stdlib html.parser 抽取。
"""
import httpx
from html.parser import HTMLParser

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class _Extract(HTMLParser):
    """title/text/links 抽取（script/style 内文不计入 text）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data.strip())
        elif not self._skip and data.strip():
            self.text_parts.append(data.strip())


def _fail(failure_class: str, title="", text="", links=None, nbytes=0) -> dict:
    return {"ok": False, "failure_class": failure_class, "title": title,
            "text": text, "links": list(links or []), "content_bytes": nbytes}


def run(params: dict) -> dict:
    url = str(params.get("url", ""))
    try:
        resp = httpx.get(url, timeout=20.0, follow_redirects=True,
                         headers={"User-Agent": _UA})
    except (httpx.HTTPError, OSError):
        return _fail("http_error")
    nbytes = len(resp.content)
    if resp.status_code >= 400:
        return _fail("http_error", nbytes=nbytes)
    body = resp.text
    low = body[:20000].lower()
    if "cf-chl" in low or "captcha" in low:
        return _fail("blocked", nbytes=nbytes)
    ex = _Extract()
    ex.feed(body)
    title = " ".join(p for p in ex.title_parts if p).strip()
    text = " ".join(ex.text_parts)
    if len(text) < 200 or not title:  # 最小内容量断言：空壳页如实失败（Review Focus 1）
        return _fail("empty_content", title=title, text=text, links=ex.links[:20], nbytes=nbytes)
    return {"ok": True, "title": title, "text": text,
            "links": ex.links[:20], "content_bytes": nbytes}
