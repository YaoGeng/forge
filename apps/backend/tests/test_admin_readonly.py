"""MS-3 T1 只读端点（docs/18）：E1 GET /api/v1/apps/{app_id}/versions 与
E3 GET /api/v1/stats/run-reports——web-admin 版本列表 / 认证记录浏览数据源
（既有 GET /api/v1/apps 只含 latest 摘要、/api/v1/certifications 无列表端点）。
"""
from datetime import datetime

from forge_server.models import App, AppVersion, RunReport

NOW = datetime(2026, 10, 16, 9, 0, 0)


def _seed_app_with_versions(api, specs):
    """specs: [(version, status), ...] 按 id 升序落库；返回 app_id。"""
    with api.app.state.session_factory() as s:
        app = App(name="hn_weekly", title="HN 周报", created_at=NOW)
        s.add(app)
        s.flush()
        for version, status in specs:
            s.add(AppVersion(app_id=app.id, version=version, status=status,
                             composition_json=[], created_at=NOW))
        s.commit()
        return app.id


class TestAppVersionsEndpoint:  # E1
    def test_shape_and_id_desc(self, api):
        app_id = _seed_app_with_versions(
            api, [("0.1.0", "published"), ("0.2.0", "draft"), ("0.3.0", "draft")])
        r = api.client.get(f"/api/v1/apps/{app_id}/versions")
        assert r.status_code == 200
        rows = r.json()
        ids = [row["id"] for row in rows]
        assert ids == sorted(ids, reverse=True)  # id desc
        assert [row["version"] for row in rows] == ["0.3.0", "0.2.0", "0.1.0"]
        assert rows[0]["status"] == "draft"
        assert rows[0]["created_at"] == NOW.isoformat()
        assert set(rows[0]) == {"id", "version", "status", "created_at"}

    def test_unknown_app_404_chinese(self, api):
        r = api.client.get("/api/v1/apps/999/versions")
        assert r.status_code == 404
        assert "不存在" in r.json()["detail"]

    def test_app_without_versions_empty_list(self, api):
        app_id = _seed_app_with_versions(api, [])
        r = api.client.get(f"/api/v1/apps/{app_id}/versions")
        assert r.status_code == 200
        assert r.json() == []


def _seed_reports(api, n):
    """n 条上报：奇数行 hn_weekly、偶数行 books_export；i>3 失败（captcha）。"""
    with api.app.state.session_factory() as s:
        for i in range(1, n + 1):
            s.add(RunReport(
                entitlement_id=i,
                app_name="books_export" if i % 2 else "hn_weekly",
                ok=(i <= 3),
                failure_class=None if i <= 3 else "captcha_detected",
                env_class="windows", client_version="0.1",
                first_run=(i == 1), created_at=NOW,
            ))
        s.commit()


class TestRunReportsListing:  # E3
    def test_shape_and_id_desc(self, api):
        _seed_reports(api, 5)
        r = api.client.get("/api/v1/stats/run-reports")
        assert r.status_code == 200
        rows = r.json()
        assert [row["id"] for row in rows] == [5, 4, 3, 2, 1]
        assert set(rows[0]) == {"id", "app_name", "ok", "failure_class",
                                "env_class", "first_run", "created_at"}
        top = rows[0]  # 最新一条（i=5）：books_export 失败 captcha_detected
        assert top["app_name"] == "books_export"
        assert top["ok"] is False
        assert top["failure_class"] == "captcha_detected"
        assert top["env_class"] == "windows"
        assert top["first_run"] is False
        assert top["created_at"] == NOW.isoformat()

    def test_default_limit_50_takes_newest(self, api):
        _seed_reports(api, 60)
        rows = api.client.get("/api/v1/stats/run-reports").json()
        assert len(rows) == 50
        assert rows[0]["id"] == 60 and rows[-1]["id"] == 11

    def test_limit_param(self, api):
        _seed_reports(api, 5)
        rows = api.client.get("/api/v1/stats/run-reports?limit=2").json()
        assert [row["id"] for row in rows] == [5, 4]

    def test_limit_bounds(self, api):
        assert api.client.get("/api/v1/stats/run-reports?limit=0").status_code == 422
        assert api.client.get("/api/v1/stats/run-reports?limit=101").status_code == 422
        assert api.client.get("/api/v1/stats/run-reports?limit=100").status_code == 200
