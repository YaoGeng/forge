"""T2.12 本地 E2E 冒烟（docs/17 Step 4；真浏览器用例，CI deselect 惯例）。

链路：本地起 forge-server（临时 sqlite）→ 直插 2 块 + 1 应用（published）→
API 灌块包（hn_search_probe 含 trace+script / excel_export）→ 注册买家 →
acquire → CLI `python -m forge_runner run hn_weekly`（真浏览器访 hn.algolia.com）
→ 断言：运行 ok / 首跑上报落库 first_run=1 / 产物 xlsx 存在。
用法：python spikes/ms2_local_smoke.py（开发机执行，恰一次留证据）
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = _ROOT / "spikes" / ".venv" / "Scripts" / "python.exe"
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"

sys.path.insert(0, str(_ROOT / "spikes"))
from upload_bundles import block_dirs, zip_block  # noqa: E402


def _api(path, method="GET", body=None, token=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.loads(resp.read().decode())


def _seed_db(db: Path) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE IF NOT EXISTS blocks (id INTEGER PRIMARY KEY, name VARCHAR(255)"
        " UNIQUE, distribution VARCHAR(32) DEFAULT 'public', owner_id VARCHAR(255)"
        " DEFAULT 'platform', created_at DATETIME);"
        "CREATE TABLE IF NOT EXISTS block_versions (id INTEGER PRIMARY KEY,"
        " block_id INTEGER, version VARCHAR(64), change_kind VARCHAR(32) DEFAULT"
        " 'code', certification_level VARCHAR(16), reliability_json JSON,"
        " side_effects BOOLEAN DEFAULT 0, domains_json JSON, code_digest VARCHAR(128),"
        " code_bundle VARCHAR(512), created_at DATETIME);"
        "CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY, name VARCHAR(255)"
        " UNIQUE, title VARCHAR(255), owner_id VARCHAR(255) DEFAULT 'platform',"
        " created_at DATETIME);"
        "CREATE TABLE IF NOT EXISTS app_versions (id INTEGER PRIMARY KEY,"
        " app_id INTEGER, version VARCHAR(64), status VARCHAR(32) DEFAULT 'draft',"
        " composition_json JSON, user_input_schema_json JSON, created_at DATETIME);"
    )
    rel = json.dumps({"level": "C2", "n": 20, "live_pass_rate": 1.0,
                      "best_effort": False, "window_end": now})
    comp = json.dumps([
        {"block": "hn_search_probe", "params": {"q": "python"}},
        {"block": "excel_export", "params": {
            "rows": "HN 周报要点 1（示例条目）", "out": "hn-weekly-smoke.xlsx"}},
    ], ensure_ascii=False)
    con.execute("INSERT INTO blocks (name, created_at) VALUES ('hn_search_probe', ?)", (now,))
    con.execute("INSERT INTO blocks (name, created_at) VALUES ('excel_export', ?)", (now,))
    for name, level in (("hn_search_probe", "C2"), ("excel_export", "C2")):
        bid = con.execute("SELECT id FROM blocks WHERE name=?", (name,)).fetchone()[0]
        con.execute(
            "INSERT INTO block_versions (block_id, version, certification_level,"
            " reliability_json, created_at) VALUES (?,?,?,?,?)",
            (bid, "1.0.0", level, rel, now))
    con.execute("INSERT INTO apps (name, title, created_at)"
                " VALUES ('hn_weekly', 'HN 周报', ?)", (now,))
    aid = con.execute("SELECT id FROM apps WHERE name='hn_weekly'").fetchone()[0]
    con.execute(
        "INSERT INTO app_versions (app_id, version, status, composition_json,"
        " created_at) VALUES (?,?,?,?,?)", (aid, "0.1.0", "published", comp, now))
    con.commit()
    con.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="forge-ms2-smoke-"))
    data_dir = tmp / "data"
    data_dir.mkdir()
    db = tmp / "smoke.db"
    _seed_db(db)
    signing_key = base64.b64encode(os.urandom(32)).decode()

    server_env = {**os.environ,
                  "FORGE_DB_URL": f"sqlite:///{db.as_posix()}",
                  "FORGE_DATA_DIR": str(data_dir), "FORGE_PORT": str(PORT),
                  "FORGE_HOST": "127.0.0.1", "FORGE_SIGNING_KEY": signing_key}
    server = subprocess.Popen(
        [str(VENV_PY), "-m", "forge_server"], env=server_env, cwd=str(_ROOT / "apps" / "server"),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{BASE}/healthz", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            print("FAIL: server 未起来")
            print(server.stdout.read() if server.stdout else "")
            return 1
        print("server up")

        # 灌 2 个块包
        import secrets

        for name, version, d in block_dirs():
            if name not in ("hn_search_probe", "excel_export"):
                continue
            content = zip_block(name, d)
            boundary = "----smoke" + secrets.token_hex(8)
            body = (f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="file"; '
                    f'filename="{name}.zip"\r\nContent-Type: application/zip\r\n\r\n'
                    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                f"{BASE}/api/v1/registry/blocks/{name}/versions/{version}/bundle",
                data=body, method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                assert resp.status == 201, (name, resp.status)
            print(f"bundle uploaded: {name}")

        _api("/api/v1/auth/register", "POST",
             {"email": "smoke@example.com", "password": "smoke-pass-123"})
        _, login = _api("/api/v1/auth/login", "POST",
                        {"email": "smoke@example.com", "password": "smoke-pass-123"})
        token = login["token"]
        _, acq = _api("/api/v1/store/apps/hn_weekly/acquire", "POST", {}, token)
        print(f"acquired entitlement {acq['entitlement_id']}")

        home = tmp / "runner-home"
        runner_env = {**os.environ,
                      "FORGE_SERVER": BASE, "FORGE_HOME": str(home),
                      "PYTHONPATH": ";".join(str(p) for p in [
                          _ROOT / "apps" / "runner",
                          _ROOT / "packages" / "trace" / "python",
                          _ROOT / "packages" / "proto" / "python",
                          _ROOT / "packages" / "block-sdk" / "python",
                      ])}
        r = subprocess.run(
            [str(VENV_PY), "-m", "forge_runner", "login", "smoke@example.com",
             "--password", "smoke-pass-123"],
            env=runner_env, cwd=str(tmp), capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"login 失败:\n{r.stdout}\n{r.stderr}"
        print("runner login ok")

        r = subprocess.run(
            [str(VENV_PY), "-m", "forge_runner", "run", "hn_weekly"],
            env=runner_env, cwd=str(tmp), capture_output=True, text=True,
            timeout=300)
        print("--- runner stdout ---")
        print(r.stdout)
        if r.returncode != 0:
            print("--- runner stderr ---")
            print(r.stderr)
            return 1

        # 断言：首跑上报落库 + 产物存在
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT ok, first_run FROM run_reports WHERE app_name='hn_weekly'").fetchone()
        con.close()
        assert row and row[0] == 1 and row[1] == 1, f"run_reports 断言失败: {row}"
        artifact = Path(tempfile.gettempdir()) / "forge-blocks" / "hn-weekly-smoke.xlsx"
        assert artifact.exists(), f"产物缺失: {artifact}"
        print(f"E2E SMOKE PASS: first_run={row[1]} 产物={artifact}")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
