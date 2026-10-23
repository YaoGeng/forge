"""books.toscrape.com 目录页读取（s3 目录书目读取；standard 档）。"""


def browse(port) -> dict:
    port.goto("https://books.toscrape.com/")
    port.wait_selector("article.product_pod", 15_000)
    import time

    time.sleep(1.5)
    html = port.snapshot_html()
    books = []
    for chunk in html.split('class="product_pod"')[1:3]:
        books.append({"title": chunk.split('title="', 1)[1].split('"', 1)[0],
                      "price": chunk.split('class="price_color">', 1)[1].split("<", 1)[0]})
    return {"books": books}
