"""T1.64b 用例：Creator Center 最小版（M02 §3 九步、§1 不变量 1/2/4、§7.5/7.8；docs/13 D-M1F.1）。"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from forge_server.models import CertificationRun


@pytest.fixture
def api(make_app):
    app = make_app()
    app.state.chain_runner = lambda composition, params: {
        "ok": True, "steps": [{"block": s.get("block"), "ok": True} for s in composition]}
    return app, TestClient(app)


def _register_block(client, app, name, *, level="C2", side_effects=False,
                    domains=("example.com",), live=1.0):
    with app.state.session_factory() as s:
        row = CertificationRun(
            subject_type="block", subject_id=name, version="1.0.0", level=level,
            n=20, pass_count=int(live * 20), live_pass_rate=live,
            regression_pass_rate=live, batch_id=f"b-{name}", verdict="pass",
            started_at=datetime(2026, 10, 16, 9, 0, 0),
            finished_at=datetime(2026, 10, 18, 9, 0, 0))
        s.add(row)
        s.commit()
        rid = row.id
    r = client.post("/api/v1/registry/blocks", json={
        "name": name, "version": "1.0.0", "certification_run_id": rid,
        "side_effects": side_effects, "domains": list(domains)})
    assert r.status_code == 200, r.text


def _open_session(client, requirement="搜索并导出周报"):
    r = client.post("/api/v1/creator/sessions", json={"requirement_text": requirement})
    assert r.status_code == 200
    return r.json()["session_id"]


def test_nine_step_order_enforced(api):
    _, client = api
    sid = _open_session(client)
    r = client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 9})
    assert r.status_code == 422  # 不许跳步
    r = client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    assert r.status_code == 200


def test_session_autosave_recovery(api):
    """任一步骤产物自动保存：后续 GET 回到最近保存点（M02 §7.5 会话恢复投影）。"""
    app, client = api
    _register_block(client, app, "probe_a")
    sid = _open_session(client)
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    r = client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [{"block": "probe_a", "params": {"q": "x"}}]})
    assert r.status_code == 200
    view = client.get(f"/api/v1/creator/sessions/{sid}").json()
    assert view["step"] == 2
    assert view["draft"]["composition"][0]["block"] == "probe_a"
    assert view["autosave_at"]


def test_side_effect_rule_enforced_server_side(api):
    """副作用积木无后置 confirm → PUT canvas 直接 422，不落库（M02 不变量 1）。"""
    app, client = api
    _register_block(client, app, "publish_x", side_effects=True)
    _register_block(client, app, "probe_a")
    sid = _open_session(client)
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    r = client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [
            {"block": "probe_a", "params": {}},
            {"block": "publish_x", "params": {}},
        ]})
    assert r.status_code == 422
    assert "confirm" in r.json()["detail"]
    # 补后置 confirm 交互步 → 放行
    r = client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [
            {"block": "probe_a", "params": {}},
            {"block": "publish_x", "params": {}},
            {"interaction": "confirm"},
        ]})
    assert r.status_code == 200
    view = client.get(f"/api/v1/creator/sessions/{sid}").json()
    assert view["draft"]["composition"][-1]["interaction"] == "confirm"


def test_full_nine_step_flow_to_published(api):
    """九步全链：会话→画布→表单→干跑→认证→报告→发布→提审 published（不打开代码编辑器）。"""
    app, client = api
    _register_block(client, app, "probe_a")
    sid = _open_session(client)
    steps = client.get(f"/api/v1/creator/sessions/{sid}").json()["steps"]
    assert steps[0] == "说需求/搜积木" and len(steps) == 9

    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [{"block": "probe_a", "params": {"q": "x"}}]})
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 4})
    client.put(f"/api/v1/creator/sessions/{sid}/form", json={
        "user_input_schema": {"q": {"type": "string"}}})
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 5})
    dry = client.post(f"/api/v1/creator/sessions/{sid}/dryrun").json()
    assert dry["ok"] and dry["steps"]
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 6})
    cert = client.post(f"/api/v1/creator/sessions/{sid}/certify").json()
    assert cert["verdict"] == "pass" and cert["statistical"] is False
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 7})
    report = client.get(f"/api/v1/creator/sessions/{sid}/report").json()
    assert report["chain"]["statistical"] is False
    rel = report["blocks"][0]["reliability"]
    assert rel["n"] == 20 and rel["live_pass_rate"] == 1.0
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 8})
    client.put(f"/api/v1/creator/sessions/{sid}/publish", json={
        "title": "周报应用", "sites_compliance_confirmed": True})
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 9})
    r = client.post(f"/api/v1/creator/sessions/{sid}/submit").json()
    assert r["status"] == "published"
    apps_list = client.get("/api/v1/apps").json()
    assert any(a["status"] == "published" for a in apps_list)


def test_creator_report_labels(api):
    """报告口径：C1 标注强制；无认证样本的块显示「数据不足」（G12/M02 §7.8）。"""
    app, client = api
    _register_block(client, app, "c1_block", level="C1", live=0.95)
    sid = _open_session(client)
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [{"block": "c1_block", "params": {}}]})
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 7})
    report = client.get(f"/api/v1/creator/sessions/{sid}/report").json()
    rel = report["blocks"][0]["reliability"]
    assert "创作者环境实测，平台抽查复核" in rel.get("c1_label", "")
    # 数据缺失态：清空快照 → 字面「数据不足」
    with app.state.session_factory() as s:
        from forge_server.models import BlockVersion
        bv = s.query(BlockVersion).one()
        bv.reliability_json = None
        s.commit()
    report2 = client.get(f"/api/v1/creator/sessions/{sid}/report").json()
    assert report2["blocks"][0]["reliability"] == {"label": "数据不足"}


def test_certify_c0_intercept_via_creator(api):
    """画布层挡未注册块；已过画布的会话认证步对 C0 仍兜底（M02 不变量 2）。"""
    app, client = api
    _register_block(client, app, "probe_a")
    sid = _open_session(client)
    client.post(f"/api/v1/creator/sessions/{sid}/goto", json={"step": 2})
    r = client.put(f"/api/v1/creator/sessions/{sid}/canvas", json={
        "composition": [{"block": "ghost", "params": {}}]})
    assert r.status_code == 422 and "认证" in r.json()["detail"]
    # 无画布产物直接跳到认证步（绕过画布）→ goto 拒绝（步骤序强制 + 产物前置）
    sid2 = _open_session(client)
    client.post(f"/api/v1/creator/sessions/{sid2}/goto", json={"step": 2})
    client.put(f"/api/v1/creator/sessions/{sid2}/canvas", json={
        "composition": [{"block": "probe_a", "params": {}}]})
    client.post(f"/api/v1/creator/sessions/{sid2}/goto", json={"step": 6})
    r = client.post(f"/api/v1/creator/sessions/{sid2}/certify")
    assert r.status_code == 200  # 正常路径可认证


def test_creator_blocks_catalog_carries_n_and_window(api):
    """第 1 步块目录：通过率带 N 与时间窗；C1 强制标注；无样本「数据不足」（G12）。"""
    app, client = api
    _register_block(client, app, "probe_a")
    _register_block(client, app, "c1_block", level="C1", live=0.95)
    rows = client.get("/api/v1/creator/blocks").json()
    by_name = {b["name"]: b for b in rows}
    a = by_name["probe_a"]["reliability"]
    assert a["n"] == 20 and a["window_start"] and a["live_pass_rate"] == 1.0
    assert "创作者环境实测，平台抽查复核" in by_name["c1_block"]["reliability"]["c1_label"]
    with app.state.session_factory() as s:  # 数据缺失态
        from forge_server.models import BlockVersion
        for bv in s.query(BlockVersion).all():
            bv.reliability_json = None
        s.commit()
    rows2 = client.get("/api/v1/creator/blocks").json()
    assert all(b["reliability"] == {"label": "数据不足"} for b in rows2)
