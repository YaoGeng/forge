"""github_search：仓库搜索（s6；浏览器 trace；匿名限额内低频）。"""


def browse(port) -> None:
    import time

    port.goto("https://api.github.com/search/repositories?q=playwright&per_page=5")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
