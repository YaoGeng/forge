"""MS-3 T1 端点活探针（证据生成用，docs/18 §11）：env 全链路装配 create_app 后
打 E1-E4 四个新端点，并现场核对 sha512 双口径与文件字节一致。"""
import base64
import hashlib
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend"))

EXE = b"probe-fake-client-exe-bytes"
dist = Path(tempfile.mkdtemp(prefix="t11-probe-dist-"))
(dist / "forge-client-0.2.0-win.exe").write_bytes(EXE)
os.environ["FORGE_DIST_DIR"] = str(dist)
os.environ["FORGE_CLIENT_VERSION"] = "0.2.0"
os.environ["FORGE_CORS_ORIGINS"] = "http://localhost:5173"

from fastapi.testclient import TestClient  # noqa: E402

from forge_server.app import create_app  # noqa: E402
from forge_server.models import App, AppVersion, RunReport  # noqa: E402

NOW = datetime(2026, 10, 16, 9, 0, 0)
app = create_app("sqlite:///" + (dist / "probe.db").as_posix())
with app.state.session_factory() as s:
    a = App(name="probe_app", title="探针应用", created_at=NOW)
    s.add(a)
    s.flush()
    for v in ("0.1.0", "0.2.0"):
        s.add(AppVersion(app_id=a.id, version=v, status="published",
                         composition_json=[], created_at=NOW))
    for i in range(3):
        s.add(RunReport(entitlement_id=i, app_name="probe_app", ok=(i == 0),
                        failure_class=None if i == 0 else "captcha_detected",
                        env_class="windows", client_version="0.1",
                        first_run=(i == 0), created_at=NOW))
    s.commit()
    app_id = a.id

c = TestClient(app)
r = c.get("/api/v1/store/client")
print("[E2 JSON]", r.status_code, r.json())
hex_ok = r.json()["sha512"] == "sha512:" + hashlib.sha512(EXE).hexdigest()
print("[E2 JSON sha512=sha512:<hex>(文件字节)]", "MATCH" if hex_ok else "MISMATCH")

r = c.get("/api/v1/store/client/latest.yml")
print("[E2 yml]", r.status_code, r.headers["content-type"])
print(r.text, end="")
import yaml  # noqa: E402
y = yaml.safe_load(r.text)
b64 = base64.b64encode(hashlib.sha512(EXE).digest()).decode()
print("[E2 yml sha512=base64(文件字节) 双处一致]",
      "MATCH" if (y["files"][0]["sha512"] == b64 and y["sha512"] == b64) else "MISMATCH")

r = c.get(f"/api/v1/apps/{app_id}/versions")
print("[E1]", r.status_code, r.json())

r = c.get("/api/v1/stats/run-reports?limit=2")
print("[E3 limit=2]", r.status_code, r.json())
r = c.get("/api/v1/stats/run-reports?limit=101")
print("[E3 limit=101 越界]", r.status_code)

r = c.options("/api/v1/apps", headers={
    "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
print("[E4 预检 白名单源]", r.status_code,
      "acao=" + str(r.headers.get("access-control-allow-origin")))
r = c.get("/healthz", headers={"Origin": "http://evil.example"})
print("[E4 非白名单源]", r.status_code,
      "acao=" + str(r.headers.get("access-control-allow-origin")))
