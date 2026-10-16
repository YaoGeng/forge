"""quotes.toscrape.com 首页名言抽取（s4 文本抽取；standard 档）。"""


def browse(port) -> None:
    port.goto("https://quotes.toscrape.com/")
    port.wait_selector(".quote .text", 15_000)
    import time

    time.sleep(1.5)


