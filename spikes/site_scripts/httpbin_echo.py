"""httpbin_echo：HTTP 往返探针（s5 公开 API；浏览器 trace）。"""


def browse(port) -> dict:
    import time

    port.goto("https://httpbin.org/get?echo=hello-forge")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    raw = port.snapshot_html()
    import json

    data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    return {"payload_keys": sorted(data), "body_head": raw[raw.find("{"):raw.find("{") + 80]}
