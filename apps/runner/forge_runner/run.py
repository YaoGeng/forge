"""执行流（docs/17 T2.12）：acquire → download/verify → activate → execute → report。

上报兜底：网络失败落 ~/.forge/outbox/，下次任意运行先重发（首跑判定以服务端为准）。
"""
from __future__ import annotations

import json
import platform
import uuid
from pathlib import Path

from . import pkg, state as state_mod
from .chain import ChainRunner

CLIENT_VERSION = "0.1.0"


class RunFlowError(Exception):
    """执行流失败（中文可读）。"""


def _outbox_dir() -> Path:
    return state_mod.home_dir() / "outbox"


def _flush_outbox(client, token: str) -> None:
    outbox = _outbox_dir()
    if not outbox.exists():
        return
    for f in sorted(outbox.glob("*.json")):
        try:
            body = json.loads(f.read_text(encoding="utf-8"))
            status, resp = client.post_json("/api/v1/run-reports", body, token=token)
            if status == 201:
                f.unlink()
        except Exception:  # noqa: BLE001 —— 重发失败留待下次
            pass


def _queue_report(client, token: str, body: dict) -> dict | None:
    """同步上报；失败落 outbox 返回 None。"""
    try:
        status, resp = client.post_json("/api/v1/run-reports", body, token=token)
        if status == 201 and isinstance(resp, dict):
            return resp
    except Exception:  # noqa: BLE001 —— 网络失败走 outbox
        pass
    _outbox_dir().mkdir(parents=True, exist_ok=True)
    (_outbox_dir() / f"{uuid.uuid4().hex}.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return None


def _resolve_entitlement(client, token: str, app_name: str) -> int:
    status, rows = client.get("/api/v1/me/entitlements", token=token)
    if status == 200 and isinstance(rows, list):
        for row in rows:
            if row.get("app") == app_name:
                return int(row["entitlement_id"])
    status, body = client.post_json(
        f"/api/v1/store/apps/{app_name}/acquire", {}, token=token)
    if status != 201 or not isinstance(body, dict) or "entitlement_id" not in body:
        detail = (body or {}).get("detail") if isinstance(body, dict) else None
        raise RunFlowError(detail or f"获取应用失败（HTTP {status}）")
    return int(body["entitlement_id"])


def app_run(app_name: str, client, token: str, *, browser_factory=None) -> dict:
    _flush_outbox(client, token)
    entitlement_id = _resolve_entitlement(client, token, app_name)

    app_dir = pkg.fetch_and_unpack(app_name, client, token)

    status, _ = client.post_json(
        f"/api/v1/entitlements/{entitlement_id}/activate", {}, token=token)
    if status != 200:
        raise RunFlowError(f"激活校验失败（HTTP {status}）")

    from .blocks import build_routes

    routes = build_routes(app_dir, browser_factory=browser_factory)
    import json as _json

    composition = _json.loads(
        (app_dir / "app.json").read_text(encoding="utf-8"))["composition"]
    result = ChainRunner(routes).execute(composition)

    failure = next(
        (s.get("failure_class") for s in result["steps"] if not s.get("ok")), None)
    report_body = {
        "entitlement_id": entitlement_id,
        "app_name": app_name,
        "ok": bool(result["ok"]),
        "failure_class": failure,
        "env_class": platform.system().lower(),
        "client_version": CLIENT_VERSION,
    }
    report = _queue_report(client, token, report_body)

    return {"ok": result["ok"], "steps": result["steps"],
            "context": result["context"],
            "first_run": (report or {}).get("first_run"),
            "report_queued": report is None}
