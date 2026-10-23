"""quotes.toscrape.com 首页名言抽取（s4 文本抽取；standard 档）。"""


def browse(port) -> dict:
    port.goto("https://quotes.toscrape.com/")
    port.wait_selector(".quote .text", 15_000)
    import time

    time.sleep(1.5)
    html = port.snapshot_html()
    quotes = []
    for chunk in html.split('class="quote"')[1:3]:
        quotes.append({"text": chunk.split('class="text">', 1)[1].split("<", 1)[0],
                       "author": chunk.split('class="author">', 1)[1].split("<", 1)[0]})
    return {"quotes": quotes}
