"""T1.64c 驱动器：五应用经产品路径组装 → 认证 → 发布（幂等可重试，离线单测注入假件）。

流程（docs/13 T1.64c 五应用，组合按计划）：
  C2 应用 ×4：Creator 会话 → 画布 → 表单 → certify（服务端 chain-cert N=1）→ publish → submit published。
  C1 应用 ×1（登录态报表，C8 本机整链）：
    ① Creator certify 返回 422（M09 §3.3 下行服务端强制——归档为证据）
    ② Registry /apps + /versions 建应用与版本
    ③ 本机整链恰一次（app.state.chain_runner，同一产品路径执行器）
    ④ certification_runs 落库 level=chain n=1（与 registry chain-cert 同一写入方式），
       attestation_sig = 设备密钥对执行摘要的签名（C8「设备密钥签名上传」v1 裁定 C8-R1）
    ⑤ /apps/{id}/submit → published
幂等：state 文件记 app_key → {session_id, app_id, published}；已发布跳过；有 app_id 未发布则续 submit。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/backend", "spikes", "packages/certifier/python",
            "packages/trace/python", "packages/proto/python", "packages/block-sdk/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_server.models import CertificationRun  # noqa: E402

EVIDENCE = _ROOT / "spikes" / "evidence"
STORE = EVIDENCE / "ms1e_store"
STATE_FILE = STORE / "t164c_state.json"

# 五应用（docs/13 T1.64c；组合=站点探针 + 本地导出/整理块，参数按 v1 字面量模型 C7）
APPS: list[dict] = [
    {
        "key": "hn_weekly", "title": "HN 周报", "level": "C2",
        "requirement": "每周把 HN 上与关注词相关的讨论整理成 Excel 周报",
        "composition": [
            {"block": "hn_search_probe", "params": {"q": "python"}},
            {"block": "excel_export", "params": {
                "rows": "HN 周报要点 1（示例条目）;HN 周报要点 2（示例条目）;HN 周报要点 3（示例条目）",
                "out": "hn-weekly.xlsx"}},
        ],
    },
    {
        "key": "books_export", "title": "书目导出", "level": "C2",
        "requirement": "把书目站目录页整理成 Excel 清单",
        "composition": [
            {"block": "books_list", "params": {}},
            {"block": "excel_export", "params": {
                "rows": "书目条目 1（示例）;书目条目 2（示例）;书目条目 3（示例）",
                "out": "books.xlsx"}},
        ],
    },
    {
        "key": "login_report", "title": "登录态报表", "level": "C1",
        "requirement": "登录演示站后把库存数据整理成 Excel 报表（C1 本机整链）",
        "composition": [
            {"block": "login_demo_probe", "params": {}},
            {"block": "excel_export", "params": {
                "rows": "库存条目 1（示例）;库存条目 2（示例）;库存条目 3（示例）",
                "out": "inventory.xlsx"}},
        ],
    },
    {
        "key": "baidu_snapshot", "title": "高变更首页快照", "level": "C2",
        "requirement": "高变更首页快照整理成 CSV（best_effort 场景可见）",
        "composition": [
            {"block": "baidu_home_watch", "params": {}},
            {"block": "csv_export", "params": {
                "rows": "首页快照要点 1（示例）;首页快照要点 2（示例）", "out": "baidu-home.csv"}},
        ],
    },
    {
        "key": "repo_digest", "title": "仓库元数据整理", "level": "C2",
        "requirement": "仓库元数据读取后做文本汇总并导出 Excel",
        "composition": [
            {"block": "github_repo_read", "params": {"repo": "microsoft/vscode"}},
            {"block": "text_digest", "params": {"lines": "repo 元数据要点 A;repo 元数据要点 B"}},
            {"block": "excel_export", "params": {
                "rows": "仓库元数据整理 1（示例）;仓库元数据整理 2（示例）", "out": "repo-meta.xlsx"}},
        ],
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"apps": {}}


def _find_or_create_app(client, name: str, title: str) -> int:
    for a in client.get("/api/v1/apps").json():
        if a.get("name") == name:
            return a["id"]
    r = client.post("/api/v1/apps", json={"name": name, "title": title})
    if r.status_code == 409:
        for a in client.get("/api/v1/apps").json():
            if a.get("name") == name:
                return a["id"]
    if r.status_code not in (200, 201):
        raise RuntimeError(f"建应用失败 {name}: {r.status_code} {r.text}")
    return r.json()["app_id"]


def _chain_row(app_state_sf, app_id: int, version: str):
    with app_state_sf() as s:
        return (s.query(CertificationRun)
                .filter_by(subject_type="app_version", subject_id=str(app_id),
                           version=version, level="chain")
                .order_by(CertificationRun.id.desc()).first())


def _local_chain_certify(app, client, app_id: int, version: str, composition: list[dict],
                         signer) -> dict:
    """C8：本机整链恰一次 + 落库 level=chain（已有 verdict 的 run 直接复用，不重跑）。"""
    existing = _chain_row(app.state.session_factory, app_id, version)
    if existing is not None and existing.verdict is not None:
        return {"run_id": existing.id, "verdict": existing.verdict, "reused": True}

    result = app.state.chain_runner([st for st in composition if st.get("block")], {})
    ok = bool(result.get("ok"))
    digest = _canon({"steps": result.get("steps", []), "ok": ok}).encode("utf-8")
    sig = signer(digest).hex() if signer else None
    now = datetime.now(timezone.utc)
    with app.state.session_factory() as s:
        row = CertificationRun(
            subject_type="app_version", subject_id=str(app_id), version=version,
            level="chain", n=1, pass_count=1 if ok else 0,
            live_pass_rate=1.0 if ok else 0.0, regression_pass_rate=None,
            batch_id=f"chain-local-{app_id}-{version}",
            started_at=now, finished_at=now,
            verdict="pass" if ok else "rejected",
            attestation_sig=sig)
        s.add(row)
        s.commit()
        run_id = row.id
    return {"run_id": run_id, "verdict": "pass" if ok else "rejected",
            "reused": False, "steps": result.get("steps", [])}


def assemble(app, client, spec: dict, state: dict, state_path: Path, *, signer=None) -> dict:
    """组装单应用（幂等）：返回 {key, app_id, status, chain, evidence}。"""
    key = spec["key"]
    rec = state["apps"].get(key) or {}
    out = {"key": key, "title": spec["title"]}

    if rec.get("published"):
        out.update(app_id=rec["app_id"], status="published", skipped=True)
        return out

    if not rec.get("app_id"):
        r = client.post("/api/v1/creator/sessions",
                        json={"requirement_text": spec["requirement"]})
        sid = r.json()["session_id"]
        rc = client.put(f"/api/v1/creator/sessions/{sid}/canvas",
                        json={"composition": spec["composition"]})
        if rc.status_code != 200:
            raise RuntimeError(f"画布保存失败 {key}: {rc.status_code} {rc.text}")
        client.put(f"/api/v1/creator/sessions/{sid}/form", json={"user_input_schema": {}})

        if spec["level"] == "C1":
            rj = client.post(f"/api/v1/creator/sessions/{sid}/certify")
            if rj.status_code != 422:
                raise RuntimeError(f"C1 应用 certify 应 422（本机整链强制）: {rj.status_code} {rj.text}")
            out["c1_certify_422"] = rj.json()
            app_id = _find_or_create_app(client, f"app-{key}", spec["title"])
            rv = client.post(f"/api/v1/apps/{app_id}/versions", json={
                "version": "1.0.0", "composition_json": spec["composition"],
                "user_input_schema_json": {}})
            if rv.status_code not in (200, 201) and "已存在" not in rv.text:
                raise RuntimeError(f"建版本失败 {key}: {rv.status_code} {rv.text}")
            local = _local_chain_certify(app, client, app_id, "1.0.0",
                                         spec["composition"], signer)
            out["chain"] = local
            out["app_id"] = app_id
            rec.update(session_id=sid, app_id=app_id, chain_run_id=local["run_id"])
        else:
            rj = client.post(f"/api/v1/creator/sessions/{sid}/certify")
            if rj.status_code != 200:
                raise RuntimeError(f"certify 失败 {key}: {rj.status_code} {rj.text}")
            out["chain"] = rj.json()
            with app.state.session_factory() as s:
                draft_app = _session_row(s, sid).draft_json.get("app_id")
            out["app_id"] = draft_app
            rec.update(session_id=sid, app_id=draft_app)
    else:
        out["app_id"] = rec["app_id"]
        out["resumed"] = True

    app_id = out["app_id"]
    version = "1.0.0"

    if rec.get("session_id") and spec["level"] == "C2":
        client.put(f"/api/v1/creator/sessions/{rec['session_id']}/publish",
                   json={"sites_compliance_confirmed": True, "title": spec["title"]})
        rs = client.post(f"/api/v1/creator/sessions/{rec['session_id']}/submit")
    else:
        rs = client.post(f"/api/v1/apps/{app_id}/submit")
    if rs.status_code != 200:
        raise RuntimeError(f"submit 失败 {key}: {rs.status_code} {rs.text}")
    out["status"] = rs.json().get("status", "published")

    rr = client.get(f"/api/v1/creator/sessions/{rec.get('session_id', 0)}/report") \
        if rec.get("session_id") else None
    out["report"] = rr.json() if rr is not None and rr.status_code == 200 else None
    rec["published"] = True
    state["apps"][key] = rec
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _session_row(s, sid):
    from forge_server.models import CreationSession

    return s.get(CreationSession, sid)


def run_all(app, client, *, signer=None, state_path: Path = STATE_FILE) -> dict:
    results = []
    state = _load_state(state_path)
    for spec in APPS:
        res = assemble(app, client, spec, state, state_path, signer=signer)
        results.append(res)
        print(f"  [{res['key']}] app_id={res.get('app_id')} status={res.get('status')}"
              f"{' (skip)' if res.get('skipped') else ''}", flush=True)
    return {"assembled_at": _now_iso(), "apps": results,
            "published": sum(1 for r in results if r.get("status") == "published")}


def real_signer(store_dir: Path):
    """C8 设备签名：复用 MS-1E 注册设备密钥（client_keys/device_key.pem）。"""
    from forge_certifier.device import DeviceKey

    key = DeviceKey.load(store_dir / "client_keys")  # load 收目录，自行拼接 key 文件名
    return key.sign


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="T1.64c 五应用组装驱动（前置：全库已 register）")
    parser.add_argument("--store", default=str(STORE))
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from product_path import build_server, wire_chain_runner

    store_dir = Path(args.store)
    app = build_server(store_dir)
    with app.state.session_factory() as s:
        from forge_server.models import Block
        names = [b.name for b in s.query(Block).all()]
    if len(names) < 20:
        raise SystemExit(f"注册块不足（{len(names)}）：先完成 seg2 + register 全库")
    wire_chain_runner(app, store_dir, names)
    client = TestClient(app)
    out = run_all(app, client, signer=real_signer(store_dir),
                  state_path=store_dir / "t164c_state.json")
    (EVIDENCE / "t164c_apps.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "apps"}, ensure_ascii=False))
    print(f"published {out['published']}/{len(APPS)} → spikes/evidence/t164c_apps.json")
    return 0 if out["published"] == len(APPS) else 1


if __name__ == "__main__":
    sys.exit(main())
