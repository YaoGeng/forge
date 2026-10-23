"""quotes.toscrape.com 标签分页读取（s4 文本抽取；standard 档）。

v2（重录）：双 goto 直达页 1/页 2——v1 的「点 Next 按钮」被录制器推导为文本锚
（内嵌 span+特殊字符 →），回放不匹配致 live 全败；沿用 hn_search 双导航先例。
"""


def browse(port) -> dict:
    import time

    port.goto("https://quotes.toscrape.com/tag/love/")
    port.wait_selector(".quote .text", 15_000)
    time.sleep(1.2)
    port.goto("https://quotes.toscrape.com/tag/love/page/2/")
    port.wait_selector(".quote .text", 15_000)
    time.sleep(1.5)
    html = port.snapshot_html()
    quotes = []
    for chunk in html.split('class="quote"')[1:3]:
        quotes.append({"text": chunk.split('class="text">', 1)[1].split("<", 1)[0],
                       "author": chunk.split('class="author">', 1)[1].split("<", 1)[0]})
    return {"quotes": quotes}
