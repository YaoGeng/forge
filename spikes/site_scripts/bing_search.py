"""cn.bing.com 两连搜索（s1 搜索聚合读取；standard 档）。"""


def browse(port) -> None:
    import time

    port.goto("https://cn.bing.com/search?q=browser+automation")
    port.wait_selector("#b_results li.b_algo, #b_results li", 15_000)
    time.sleep(1.5)
    port.goto("https://cn.bing.com/search?q=web+recorder")
    port.wait_selector("#b_results li.b_algo, #b_results li", 15_000)
    time.sleep(1.5)


