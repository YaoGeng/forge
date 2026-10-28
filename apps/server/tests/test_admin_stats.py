"""T2.24 首跑统计面板（docs/17）：判定式钉死 + 达标态渲染（Basic Auth 域，nginx 把关）。"""
from datetime import datetime

from forge_server.models import RunReport

NOW = datetime(2026, 10, 26, 12, 0, 0)
GATE_TEXT = "MS-2 通过 = 每个上架应用首跑成功率 ≥80% 且 n≥5 不同真实注册用户；任一不达 → 不进 MS-3"


def _report(s, i, app, ok, first=True):
    s.add(RunReport(entitlement_id=i, app_name=app, ok=ok, env_class="windows",
                    client_version="0.1", first_run=first, created_at=NOW))


class TestAdminFirstRun:
    def test_page_renders_gate_verdict(self, api):
        r = api.client.get("/admin/first-run")
        assert r.status_code == 200
        assert GATE_TEXT in r.text

    def test_passing_app_shows_green_badge(self, api):
        with api.app.state.session_factory() as s:
            for i in range(1, 6):  # 5 用户首跑 5 全过 → n=5 rate=1.0 达标
                _report(s, i, "hn_weekly", ok=True)
            s.commit()
        text = api.client.get("/admin/first-run").text
        assert "hn_weekly" in text and "100.0%" in text
        assert "达标" in text

    def test_failing_app_shows_not_met(self, api):
        with api.app.state.session_factory() as s:
            for i in range(1, 11):  # 10 用户首跑 5 过 → 50% 未达标
                _report(s, i, "books_export", ok=(i <= 5))
            s.commit()
        text = api.client.get("/admin/first-run").text
        assert "books_export" in text and "50.0%" in text
        assert "未达标" in text

    def test_insufficient_samples_not_met(self, api):
        with api.app.state.session_factory() as s:
            _report(s, 1, "repo_digest", ok=True)  # n=1 <5 → 未达标（样本不足）
            s.commit()
        text = api.client.get("/admin/first-run").text
        assert "repo_digest" in text and "未达标" in text

    def test_recent_details_listed(self, api):
        with api.app.state.session_factory() as s:
            _report(s, 1, "hn_weekly", ok=True, first=True)
            _report(s, 2, "hn_weekly", ok=False, first=False)  # 非首跑也进明细
            s.commit()
        text = api.client.get("/admin/first-run").text
        assert text.count("hn_weekly") >= 2
        assert "windows" in text  # 环境类可见
