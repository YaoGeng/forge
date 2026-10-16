"""github_repo_read：仓库元数据（s6；浏览器 trace；匿名限额内低频）。"""


def browse(port) -> None:
    import time

    port.goto("https://api.github.com/repos/microsoft/vscode")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
