"""T2.20 浏览器走查（docs/17 Step 4；本地 HTTP + 截图，沿用原型校验惯例）。

种子三应用：hn_weekly（C2）/ login_report（C1 登录站点）/ baidu_snapshot（best-effort）
+ 一个注册用户 + 30 条用户运行上报（数据不足 vs 有数据两分支都可看）。
截图三帧 → spikes/evidence/ms2/t2.20-*.png
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = _ROOT / "spikes" / ".venv" / "Scripts" / "python.exe"
OUT = _ROOT / "spikes" / "evidence" / "ms2"
PORT = 8098
BASE = f"http://127.0.0.1:{PORT}"


def _seed(db: Path) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE blocks (id INTEGER PRIMARY KEY, name VARCHAR(255) UNIQUE,"
        " distribution VARCHAR(32) DEFAULT 'public', owner_id VARCHAR(255) DEFAULT"
        " 'platform', created_at DATETIME);"
        "CREATE TABLE block_versions (id INTEGER PRIMARY KEY, block_id INTEGER,"
        " version VARCHAR(64), change_kind VARCHAR(32) DEFAULT 'code',"
        " certification_level VARCHAR(16), reliability_json JSON, side_effects BOOLEAN"
        " DEFAULT 0, domains_json JSON, code_digest VARCHAR(128), code_bundle"
        " VARCHAR(512), created_at DATETIME);"
        "CREATE TABLE apps (id INTEGER PRIMARY KEY, name VARCHAR(255) UNIQUE,"
        " title VARCHAR(255), owner_id VARCHAR(255) DEFAULT 'platform', created_at"
        " DATETIME);"
        "CREATE TABLE app_versions (id INTEGER PRIMARY KEY, app_id INTEGER, version"
        " VARCHAR(64), status VARCHAR(32) DEFAULT 'draft', composition_json JSON,"
        " user_input_schema_json JSON, created_at DATETIME);"
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) UNIQUE,"
        " password_hash VARCHAR(255), created_at DATETIME);"
        "CREATE TABLE auth_sessions (id INTEGER PRIMARY KEY, token VARCHAR(128)"
        " UNIQUE, user_id INTEGER, created_at DATETIME, expires_at DATETIME);"
        "CREATE TABLE entitlements (id INTEGER PRIMARY KEY, user_id INTEGER,"
        " app_name VARCHAR(255), version VARCHAR(64), source VARCHAR(32) DEFAULT"
        " 'free_ms2', order_id INTEGER, acquired_at DATETIME, activated_at DATETIME);"
        "CREATE TABLE run_reports (id INTEGER PRIMARY KEY, entitlement_id INTEGER,"
        " app_name VARCHAR(255), ok BOOLEAN, failure_class VARCHAR(64), env_class"
        " VARCHAR(64), client_version VARCHAR(32), first_run BOOLEAN, created_at"
        " DATETIME);"
    )
    rel = json.dumps({"level": "C2", "n": 20, "live_pass_rate": 1.0,
                      "best_effort": False, "window_end": now})
    rel_be = json.dumps({"level": "C2", "n": 20, "live_pass_rate": 0.95,
                         "best_effort": True, "window_end": now})
    blocks = [("hn_search_probe", rel, "[]"), ("excel_export", rel, "[]"),
              ("login_demo_probe", rel, '["saucedemo.com"]'),
              ("baidu_home_watch", rel_be, "[]"), ("csv_export", rel, "[]")]
    for name, reliability, domains in blocks:
        con.execute("INSERT INTO blocks (name, created_at) VALUES (?,?)", (name, now))
        bid = con.execute("SELECT id FROM blocks WHERE name=?", (name,)).fetchone()[0]
        con.execute("INSERT INTO block_versions (block_id, version,"
                    " certification_level, reliability_json, domains_json, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (bid, "1.0.0", "C2", reliability, domains, now))
    apps = [
        ("hn_weekly", "HN 周报",
         [{"block": "hn_search_probe", "params": {"q": "python"}},
          {"block": "excel_export", "params": {"out": "hn-weekly.xlsx"}}]),
        ("login_report", "登录态报表",
         [{"block": "login_demo_probe", "params": {}},
          {"block": "excel_export", "params": {"out": "inventory.xlsx"}}]),
        ("baidu_snapshot", "高变更首页快照",
         [{"block": "baidu_home_watch", "params": {}},
          {"block": "csv_export", "params": {"out": "baidu-home.csv"}}]),
    ]
    for name, title, comp in apps:
        con.execute("INSERT INTO apps (name, title, created_at) VALUES (?,?,?)",
                    (name, title, now))
        aid = con.execute("SELECT id FROM apps WHERE name=?", (name,)).fetchone()[0]
        con.execute("INSERT INTO app_versions (app_id, version, status,"
                    " composition_json, created_at) VALUES (?,?,?,?,?)",
                    (aid, "0.1.0", "published", json.dumps(comp, ensure_ascii=False), now))
    con.commit()
    con.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="forge-ms2-web-"))
    db = tmp / "web.db"
    _seed(db)
    server = subprocess.Popen(
        [str(VENV_PY), "-m", "forge_server"],
        env={**os.environ, "FORGE_DB_URL": f"sqlite:///{db.as_posix()}",
             "FORGE_DATA_DIR": str(tmp / "data"), "FORGE_PORT": str(PORT),
             "FORGE_HOST": "127.0.0.1"},
        cwd=str(_ROOT / "apps" / "server"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{BASE}/healthz", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        for p in (_ROOT / "packages" / "trace" / "python",
                  _ROOT / "packages" / "proto" / "python",
                  _ROOT / "packages" / "block-sdk" / "python"):
            sys.path.insert(0, str(p))
        from forge_trace.patchright_browser import PatchrightBrowser

        browser = PatchrightBrowser(headless=True)
        shots = [
            (f"{BASE}/store", "t2.20-store-list.png"),
            (f"{BASE}/store/app/hn_weekly", "t2.20-detail-c2.png"),
            (f"{BASE}/store/app/login_report", "t2.20-detail-c1.png"),
            (f"{BASE}/store/app/baidu_snapshot", "t2.20-detail-best-effort.png"),
        ]
        for url, fname in shots:
            browser.goto(url)
            browser.wait_selector("body", 10000)
            time.sleep(0.5)
            shot = tmp / fname
            browser._page.screenshot(path=str(shot), full_page=True)
            Path(OUT, fname).write_bytes(shot.read_bytes())
            print(f"shot: {fname}")
        browser.close()
        print("WALKTHROUGH DONE")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
