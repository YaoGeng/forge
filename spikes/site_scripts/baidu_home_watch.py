"""baidu 首页结构监控（s7 高变更首页监控；high 档——AI 首页改版由 MS-1D C1-R2 实证）。"""


def browse(port) -> None:
    port.goto("https://www.baidu.com/")
    port.wait_selector("#kw, #form", 15_000)
    import time

    time.sleep(2.0)


