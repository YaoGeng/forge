"""npm_pkg_meta：npmmirror 包元数据（s5 公开 API；浏览器 trace，阶段 1 唯一合规网络路径）。"""


def browse(port) -> None:
    import time

    port.goto("https://registry.npmmirror.com/pytest")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
