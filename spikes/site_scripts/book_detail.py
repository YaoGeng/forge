"""books.toscrape.com 目录 → 首书详情（s3 目录书目读取；standard 档）。"""


def browse(port) -> None:
    port.goto("https://books.toscrape.com/")
    port.wait_selector("article.product_pod h3 a", 15_000)
    import time

    time.sleep(1.0)
    port.click("article.product_pod h3 a")
    port.wait_selector(".product_main", 15_000)
    time.sleep(1.5)


