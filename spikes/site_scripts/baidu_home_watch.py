"""baidu 首页结构监控（s7 高变更首页监控；high 档——AI 首页改版由 MS-1D C1-R2 实证）。

快照基线（baseline.json）首跑落块目录，changed 判定以基线为锚（docs/15 T1.72）。
"""
import hashlib
import json
from pathlib import Path

BASELINE = Path(__file__).resolve().parent.parent / "seed_blocks" / "baidu_home_watch" / "baseline.json"


def browse(port) -> dict:
    port.goto("https://www.baidu.com/")
    port.wait_selector("#kw, #form", 15_000)
    import time

    time.sleep(2.0)
    html = port.snapshot_html()
    headline = html.split("<title>", 1)[1].split("</title>", 1)[0] if "<title>" in html else ""
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
    if not BASELINE.exists():  # 首跑建基线
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({"digest": digest}, ensure_ascii=False), encoding="utf-8")
        return {"snapshot_changed": False, "headline": headline}
    changed = json.loads(BASELINE.read_text(encoding="utf-8"))["digest"] != digest
    return {"snapshot_changed": bool(changed), "headline": headline}
