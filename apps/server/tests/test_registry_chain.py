"""T1.64a 用例：最小 Registry + chain 认证（M10 §4/§5 子集、M09 §3.3、docs/13 C6/C7/C11/C13）。"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from forge_server.models import Base, CertificationRun  # noqa: F401


@pytest.fixture
def api(make_app):
    app = make_app()
    app.state.chain_runner = None
    client = TestClient(app)
    return app, client


def _pass_run(app, name, *, level="C2", n=20, live=1.0):
    """直接落一行已完成认证（registry 测试聚焦注册/读侧，不再走调度器）。"""
    with app.state.session_factory() as s:
        row = CertificationRun(
            subject_type="block", subject_id=name, version="1.0.0", level=level,
            n=n, pass_count=int(live * n), live_pass_rate=live,
            regression_pass_rate=live, batch_id=f"batch-{name}",
            started_at=datetime(2026, 10, 16, 9, 0, 0),
            finished_at=datetime(2026, 10, 18, 9, 0, 0), verdict="pass",
        )
        s.add(row)
        s.commit()
        return row.id


def _register(client, name, run_id, version="1.0.0"):
    return client.post("/api/v1/registry/blocks", json={
        "name": name, "version": version, "certification_run_id": run_id})


def test_register_requires_passed_run(api):
    app, client = api
    rid = _pass_run(app, "probe_a")
    assert _register(client, "probe_a", rid).status_code == 200

    with app.state.session_factory() as s:  # rejected run
        bad = CertificationRun(subject_type="block", subject_id="probe_b", version="1.0.0",
                               level="C2", n=5, pass_count=0, live_pass_rate=0.0,
                               batch_id="b", verdict="rejected")
        s.add(bad)
        s.commit()
        bad_id = bad.id
    r = _register(client, "probe_b", bad_id)
    assert r.status_code == 422
    assert "pass" in r.json()["detail"]


def test_reliability_view_carries_n_and_window(api):
    app, client = api
    rid = _pass_run(app, "probe_a", level="C1", live=0.95)
    _register(client, "probe_a", rid)
    r = client.post("/api/v1/apps", json={"name": "app1", "title": "应用一"})
    app_id = r.json()["app_id"]
    client.post(f"/api/v1/apps/{app_id}/versions", json={
        "version": "1.0.0",
        "composition_json": [{"block": "probe_a", "params": {"q": "x"}}],
        "user_input_schema_json": {"q": {"type": "string"}},
    })
    view = client.get(f"/api/v1/apps/{app_id}").json()
    rel = view["versions"][0]["blocks"][0]["reliability"]
    assert rel["n"] == 20 and rel["live_pass_rate"] == 0.95
    assert rel["window_start"] and rel["window_end"]
    assert rel["level"] == "C1"
    assert "创作者环境实测，平台抽查复核" in rel["c1_label"]
    assert "暂无用户数据" in view["versions"][0]["blocks"][0]["user_rolling_note"]

    # 无样本（快照被清空的数据缺失态）：读侧字面「数据不足」
    with app.state.session_factory() as s:
        from forge_server.models import BlockVersion
        bv = s.query(BlockVersion).one()
        bv.reliability_json = None
        s.commit()
    view2 = client.get(f"/api/v1/apps/{app_id}").json()
    rel2 = view2["versions"][0]["blocks"][0]["reliability"]
    assert rel2 == {"label": "数据不足"}


def test_app_version_rejects_unregistered_block(api):
    app, client = api
    r = client.post("/api/v1/apps", json={"name": "app2", "title": "应用二"})
    app_id = r.json()["app_id"]
    r = client.post(f"/api/v1/apps/{app_id}/versions", json={
        "version": "1.0.0",
        "composition_json": [{"block": "ghost_block", "params": {}}],
        "user_input_schema_json": {},
    })
    assert r.status_code == 422


def test_chain_report_marked_non_statistical(api):
    app, client = api
    rid = _pass_run(app, "probe_a")
    _register(client, "probe_a", rid)
    app_id = client.post("/api/v1/apps", json={"name": "app3", "title": "应用三"}).json()["app_id"]
    client.post(f"/api/v1/apps/{app_id}/versions", json={
        "version": "1.0.0",
        "composition_json": [{"block": "probe_a", "params": {}}],
        "user_input_schema_json": {},
    })

    def fake_chain(composition, params):
        return {"ok": True, "steps": [{"block": "probe_a", "ok": True}]}

    app.state.chain_runner = fake_chain
    r = client.post(f"/api/v1/apps/{app_id}/versions/1.0.0/chain-cert")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "pass" and body["n"] == 1
    assert body["statistical"] is False
    assert "非统计值" in body["annotation"]
    view = client.get(f"/api/v1/apps/{app_id}").json()
    assert view["versions"][0]["chain"]["statistical"] is False


def test_chain_run_executes_pipeline(api):
    app, client = api
    for name in ("step_a", "step_b"):
        _register(client, name, _pass_run(app, name))
    app_id = client.post("/api/v1/apps", json={"name": "app4", "title": "应用四"}).json()["app_id"]
    client.post(f"/api/v1/apps/{app_id}/versions", json={
        "version": "1.0.0",
        "composition_json": [
            {"block": "step_a", "params": {"q": "hello"}},
            {"block": "step_b", "bindings": {"src": "step_a.rows"}},
        ],
        "user_input_schema_json": {"q": {"type": "string"}},
    })
    seen = []

    def fake_chain(composition, params):
        seen.append((composition, params))
        return {"ok": True, "steps": [{"block": s["block"], "ok": True} for s in composition]}

    app.state.chain_runner = fake_chain
    r = client.post(f"/api/v1/apps/{app_id}/versions/1.0.0/chain-cert")
    assert r.status_code == 200
    composition, params = seen[0]
    assert composition[1]["bindings"] == {"src": "step_a.rows"}
    with app.state.session_factory() as s:
        row = s.query(CertificationRun).filter_by(
            subject_type="app_version", subject_id=str(app_id)).one()
        assert row.level == "chain" and row.n == 1 and row.verdict == "pass"


def test_chain_cert_rejects_c1_app_on_server(api):
    """含 C1 积木的应用：服务端同步整链拒绝，提示走本机整链（M09 §3.3 下行）。"""
    app, client = api
    _register(client, "c1_block", _pass_run(app, "c1_block", level="C1"))
    app_id = client.post("/api/v1/apps", json={"name": "app5", "title": "应用五"}).json()["app_id"]
    client.post(f"/api/v1/apps/{app_id}/versions", json={
        "version": "1.0.0",
        "composition_json": [{"block": "c1_block", "params": {}}],
        "user_input_schema_json": {},
    })
    app.state.chain_runner = lambda c, p: {"ok": True, "steps": []}
    r = client.post(f"/api/v1/apps/{app_id}/versions/1.0.0/chain-cert")
    assert r.status_code == 422
    assert "本机" in r.json()["detail"]


def test_submit_rejects_uncertified_block(api):
    """提审：含未认证（未注册）块的应用被拦截并给转正路径提示（M02 不变量 2 服务端强制）。"""
    app, client = api
    _register(client, "probe_a", _pass_run(app, "probe_a"))
    app_id = client.post("/api/v1/apps", json={"name": "app6", "title": "应用六"}).json()["app_id"]
    # 组合里混入一个未注册块 → 版本创建即被拒（C0 拦截在版本层）
    r = client.post(f"/api/v1/apps/{app_id}/versions", json={
        "version": "1.0.0",
        "composition_json": [
            {"block": "probe_a", "params": {}},
            {"block": "uncertified_x", "params": {}},
        ],
        "user_input_schema_json": {},
    })
    assert r.status_code == 422
    assert "认证" in r.json()["detail"]
