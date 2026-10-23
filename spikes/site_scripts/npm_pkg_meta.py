"""npm_pkg_meta：npmmirror 包元数据（s5 公开 API；浏览器 trace，阶段 1 唯一合规网络路径）。"""


def _json(port) -> dict:
    import json

    raw = port.snapshot_html()
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def browse(port) -> dict:
    import time

    port.goto("https://registry.npmmirror.com/pytest")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    data = _json(port)
    return {"name": data.get("name"), "version": data.get("version"),
            "description": data.get("description")}
