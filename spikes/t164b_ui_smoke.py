"""T1.64b UI 冒烟（docs/13 §5 T1.64b 步 5）：一次性服务 + 种子块 + patchright 截图两帧。"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/server", "packages/trace/python", "packages/proto/python",
            "packages/block-sdk/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_trace.patchright_browser import PatchrightBrowser  # noqa: E402

EVIDENCE = _ROOT / "spikes" / "evidence"
PORT = 8791


def main() -> int:
    from fastapi.testclient import TestClient

    from forge_server.app import create_app
    from forge_server.models import CertificationRun

    db = tempfile.mktemp(suffix=".db").replace("\\", "/")
    app = create_app(f"sqlite:///{db}")

    def chain(composition, params):
        return {"ok": True, "steps": [{"index": i, "block": s.get("block"), "ok": True}
                                      for i, s in enumerate(composition)]}

    app.state.chain_runner = chain
    client = TestClient(app)
    with app.state.session_factory() as s:
        for name, level, live in (("hn_search_probe", "C2", 1.0),
                                  ("login_demo_probe", "C1", 0.95),
                                  ("excel_export", "C2", 1.0)):
            row = CertificationRun(
                subject_type="block", subject_id=name, version="1.0.0", level=level,
                n=20, pass_count=int(live * 20), live_pass_rate=live,
                regression_pass_rate=live, batch_id=f"smoke-{name}", verdict="pass",
                started_at=datetime(2026, 10, 16, 9), finished_at=datetime(2026, 10, 18, 9))
            s.add(row)
            s.commit()  # 先提交：注册端点经独立会话查询
            r = client.post("/api/v1/registry/blocks", json={
                "name": name, "version": "1.0.0", "certification_run_id": row.id,
                "domains": ["hn.algolia.com"] if name.startswith("hn") else []})
            assert r.status_code == 200, r.text

    # 推一个会话到第 7 步（报告视图），供 ?session= 恢复截图
    sid = client.post("/api/v1/creator/sessions",
                      json={"requirement_text": "搜索并导出周报"}).json()["session_id"]
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [{"block": "hn_search_probe", "params": {"q": "python"}},
                        {"block": "excel_export", "bindings": {"rows": "hn_search_probe.hits"}}]})
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 4})
    client.put(f"/api/v1/creator/sessions/{sid}/form", json={"user_input_schema": {"q": {"type": "string"}}})
    for step in (5, 6, 7):
        client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": step})
        if step == 6:
            client.post(f"/api/v1/creator/sessions/{sid}/certify")

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
        p1 = EVIDENCE / "t1.64b_ui_step1.png"
        browser._page.screenshot(path=str(p1), full_page=True)
        browser.goto(f"http://127.0.0.1:{PORT}/creator?session={sid}")
        time.sleep(1.5)
        p2 = EVIDENCE / "t1.64b_ui_step7_report.png"
        browser._page.screenshot(path=str(p2), full_page=True)
    finally:
        browser.close()
    print(f"UI 冒烟截图：{p1.name} / {p2.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
