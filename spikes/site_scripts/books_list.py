"""books.toscrape.com 目录页读取（s3 目录书目读取；standard 档）。"""


def browse(port) -> None:
    port.goto("https://books.toscrape.com/")
    port.wait_selector("article.product_pod", 15_000)
    import time

    time.sleep(1.5)


