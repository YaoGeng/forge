"""T1.64c UI 走查（docs/13 §5 T1.64c）：真实库（ms1e_store）+ 真 22 块目录驱动 Creator UI，
patchright 截图三帧——步 1 需求输入 / 步 2 目录（真实注册块）/ 步 7 报告视图（已发布应用）。

只读导航（goto），不触发新的 certify/submit——全库恰 5 应用是 T1.64c 验收口径。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/backend", "spikes", "packages/trace/python", "packages/proto/python",
            "packages/block-sdk/python", "packages/certifier/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_trace.patchright_browser import PatchrightBrowser  # noqa: E402

EVIDENCE = _ROOT / "spikes" / "evidence"
STORE = EVIDENCE / "ms1e_store"
PORT = 8792


def main() -> int:
    from fastapi.testclient import TestClient

    from product_path import build_server, wire_chain_runner
    from forge_server.models import Block

    app = build_server(STORE)
    with app.state.session_factory() as s:
        names = [b.name for b in s.query(Block).all()]
    assert len(names) >= 20, f"注册块不足：{len(names)}"
    wire_chain_runner(app, store_dir=STORE, names=names)  # 真实装配（dryrun 可用；本走查只读）
    client = TestClient(app)

    sid = 2  # hn_weekly（t164c_state.json）

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        time.sleep(0.2)
        if server.started:
            break

    browser = PatchrightBrowser()
    try:
        browser.goto(f"http://127.0.0.1:{PORT}/creator")
        time.sleep(1.2)
        p1 = EVIDENCE / "t164c_ui_step1.png"
        browser._page.screenshot(path=str(p1), full_page=True)

        client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})  # 目录视图（只读导航）
        browser.goto(f"http://127.0.0.1:{PORT}/creator?session={sid}")
        time.sleep(1.2)
        p2 = EVIDENCE / "t164c_ui_step2_catalog.png"
        browser._page.screenshot(path=str(p2), full_page=True)

        # 步序门 ±1（M02）：逐级走到报告视图；只导航、不 certify/submit
        for step in (3, 4, 5, 6, 7):
            r = client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": step})
            assert r.status_code == 200, f"goto {step}: {r.status_code} {r.text}"
        browser.goto(f"http://127.0.0.1:{PORT}/creator?session={sid}")
        browser._page.reload()  # 同 URL 二跳不重载（SPA 缓存）——强制刷新取新步号
        time.sleep(1.5)
        p3 = EVIDENCE / "t164c_ui_step7_report.png"
        browser._page.screenshot(path=str(p3), full_page=True)
    finally:
        browser.close()
    print(f"UI 走查截图：{p1.name} / {p2.name} / {p3.name}（真实库 22 块、只读导航）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
