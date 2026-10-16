"""httpbin_echo：HTTP 往返探针（s5 公开 API；浏览器 trace）。"""


def browse(port) -> None:
    import time

    port.goto("https://httpbin.org/get?echo=hello-forge")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
