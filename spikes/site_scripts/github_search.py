"""github_search：仓库搜索（s6；浏览器 trace；匿名限额内低频）。"""


def _json(port) -> dict:
    import json

    raw = port.snapshot_html()
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def browse(port) -> dict:
    import time

    port.goto("https://api.github.com/search/repositories?q=playwright&per_page=5")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    items = [{"full_name": it.get("full_name"), "stars": it.get("stargazers_count")}
             for it in _json(port).get("items", [])[:2]]
    return {"items": items}
