"""github_repo_read：仓库元数据（s6；浏览器 trace；匿名限额内低频）。"""


def _json(port) -> dict:
    import json

    raw = port.snapshot_html()
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def browse(port) -> dict:
    import time

    port.goto("https://api.github.com/repos/microsoft/vscode")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    data = _json(port)
    return {"repo": data.get("full_name"), "stars": data.get("stargazers_count"),
            "description": data.get("description")}
