"""jsonplaceholder_posts：假数据 API 帖子（s5 公开 API；浏览器 trace；数据站方固定）。"""


def browse(port) -> None:
    import time

    port.goto("https://jsonplaceholder.typicode.com/posts/1")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
