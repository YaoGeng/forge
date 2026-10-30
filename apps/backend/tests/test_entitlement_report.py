"""T2.03 免费获取、激活与运行上报（docs/17）。

幂等铁律：acquire 重复返回同一条 entitlement；激活幂等返回首次时间戳；
first_run 服务端判定（该用户该应用首条上报）——重复上报不重复计首跑。
"""
from datetime import datetime

from forge_server.models import App, AppVersion

PASSWORD = "correct-horse-42"
NOW = datetime(2026, 10, 26, 12, 0, 0)


def _seed_published_app(api, name="hn_weekly", status="published"):
    with api.app.state.session_factory() as s:
        app = App(name=name, title="HN 周报", created_at=NOW)
        s.add(app)
        s.flush()
        s.add(AppVersion(app_id=app.id, version="0.1.0", status=status,
                         composition_json=[{"block": "hn_search_probe", "params": {}}],
                         created_at=NOW))
        s.commit()


def _new_user(api, email):
    from fastapi.testclient import TestClient

    client: TestClient = api.client
    assert client.post("/api/v1/auth/register",
                       json={"email": email, "password": PASSWORD}).status_code == 201
    token = client.post("/api/v1/auth/login",
                        json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _acquire(client, name="hn_weekly", auth=None):
    return client.post(f"/api/v1/store/apps/{name}/acquire", headers=auth or {})


def _report(client, auth, entitlement_id, app="hn_weekly", ok=True, **extra):
    body = {"entitlement_id": entitlement_id, "app_name": app, "ok": ok,
            "env_class": "windows", "client_version": "0.1.0"}
    body.update(extra)
    return client.post("/api/v1/run-reports", json=body, headers=auth)


class TestAcquire:
    def test_acquire_creates_and_idempotent(self, api):
        _seed_published_app(api)
        auth = _new_user(api, "a@example.com")
        r1 = _acquire(api.client, auth=auth)
        assert r1.status_code == 201
        eid = r1.json()["entitlement_id"]
        r2 = _acquire(api.client, auth=auth)
        assert r2.status_code == 201
        assert r2.json()["entitlement_id"] == eid
        assert r2.headers.get("x-idempotent-replay") == "true"
        assert r1.headers.get("x-idempotent-replay") != "true"

    def test_acquire_unpublished_404_and_unauth_401(self, api):
        _seed_published_app(api, name="draft_app", status="draft")
        assert _acquire(api.client, name="draft_app").status_code == 401
        auth = _new_user(api, "a@example.com")
        r = _acquire(api.client, name="draft_app", auth=auth)
        assert r.status_code == 404
        assert r.json()["detail"] == "应用不存在或未上架"

    def test_me_entitlements_lists(self, api):
        _seed_published_app(api)
        auth = _new_user(api, "a@example.com")
        eid = _acquire(api.client, auth=auth).json()["entitlement_id"]
        r = api.client.get("/api/v1/me/entitlements", headers=auth)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["entitlement_id"] == eid and row["app"] == "hn_weekly"
        assert row["version"] == "0.1.0" and row["activated_at"] is None
        assert row["source"] == "free_ms2"


class TestActivate:
    def test_activate_idempotent_returns_first_timestamp(self, api, clock):
        _seed_published_app(api)
        auth = _new_user(api, "a@example.com")
        eid = _acquire(api.client, auth=auth).json()["entitlement_id"]
        r1 = api.client.post(f"/api/v1/entitlements/{eid}/activate", headers=auth)
        assert r1.status_code == 200
        first = r1.json()["activated_at"]
        clock.advance(hours=1)
        r2 = api.client.post(f"/api/v1/entitlements/{eid}/activate", headers=auth)
        assert r2.json()["activated_at"] == first  # 幂等：不刷新

    def test_activate_foreign_entitlement_404(self, api):
        _seed_published_app(api)
        alice = _new_user(api, "a@example.com")
        bob = _new_user(api, "b@example.com")
        eid = _acquire(api.client, auth=alice).json()["entitlement_id"]
        r = api.client.post(f"/api/v1/entitlements/{eid}/activate", headers=bob)
        assert r.status_code == 404  # 不泄露他人权益存在性

    def test_me_entitlements_shows_activated_at(self, api):
        _seed_published_app(api)
        auth = _new_user(api, "a@example.com")
        eid = _acquire(api.client, auth=auth).json()["entitlement_id"]
        api.client.post(f"/api/v1/entitlements/{eid}/activate", headers=auth)
        row = api.client.get("/api/v1/me/entitlements", headers=auth).json()[0]
        assert row["activated_at"] is not None


class TestRunReport:
    def test_first_run_server_side_judgement(self, api):
        _seed_published_app(api)
        alice = _new_user(api, "a@example.com")
        bob = _new_user(api, "b@example.com")
        ea = _acquire(api.client, auth=alice).json()["entitlement_id"]
        eb = _acquire(api.client, auth=bob).json()["entitlement_id"]
        assert _report(api.client, alice, ea).json()["first_run"] is True
        assert _report(api.client, alice, ea).json()["first_run"] is False
        assert _report(api.client, bob, eb).json()["first_run"] is True  # 用户独立

    def test_foreign_or_unknown_entitlement_404_and_unauth_401(self, api, make_app):
        from fastapi.testclient import TestClient

        _seed_published_app(api)
        alice = _new_user(api, "a@example.com")
        bob = _new_user(api, "b@example.com")
        ea = _acquire(api.client, auth=alice).json()["entitlement_id"]
        assert _report(api.client, bob, ea).status_code == 404
        assert _report(api.client, alice, 999).status_code == 404
        # 共享 client 带着登录 Cookie——未认证分支必须用全新无 Cookie 客户端
        fresh = TestClient(make_app())
        r = fresh.post("/api/v1/run-reports",
                       json={"entitlement_id": 1, "app_name": "hn_weekly",
                             "ok": True, "env_class": "windows",
                             "client_version": "0.1"})
        assert r.status_code == 401

    def test_invalid_failure_class_422(self, api):
        _seed_published_app(api)
        auth = _new_user(api, "a@example.com")
        eid = _acquire(api.client, auth=auth).json()["entitlement_id"]
        r = _report(api.client, auth, eid, failure_class="made_up_class")
        assert r.status_code == 422

    def test_stats_first_run_aggregate(self, api):
        _seed_published_app(api)
        _seed_published_app(api, name="books_export")
        alice = _new_user(api, "a@example.com")
        bob = _new_user(api, "b@example.com")
        ea = _acquire(api.client, auth=alice).json()["entitlement_id"]
        eb = _acquire(api.client, auth=bob).json()["entitlement_id"]
        eb2 = _acquire(api.client, "books_export", auth=bob).json()["entitlement_id"]
        _report(api.client, alice, ea, ok=True)
        _report(api.client, alice, ea, ok=False)  # 非首跑不计入
        _report(api.client, bob, eb, ok=False)
        _report(api.client, bob, eb2, app="books_export", ok=True)
        stats = {row["app"]: row for row in
                 api.client.get("/api/v1/stats/first-run").json()}
        assert stats["hn_weekly"] == {"app": "hn_weekly", "first_runs": 2,
                                      "ok_first_runs": 1, "rate": 0.5}
        assert stats["books_export"] == {"app": "books_export", "first_runs": 1,
                                         "ok_first_runs": 1, "rate": 1.0}
