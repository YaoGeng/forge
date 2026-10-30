"""T2.23 健康分级 v0（docs/17）：分档边界与应用最差档。"""
from datetime import datetime, timedelta

from forge_server.health import app_health, grade
from forge_server.models import App, AppVersion, Block, BlockVersion, CertificationRun

NOW = datetime(2026, 10, 26, 12, 0, 0)


def _seed_block(s, name, *, best_effort=False):
    block = Block(name=name, created_at=NOW)
    s.add(block)
    s.flush()
    s.add(BlockVersion(
        block_id=block.id, version="1.0.0", certification_level="C2",
        reliability_json={"level": "C2", "n": 20, "live_pass_rate": 1.0,
                          "best_effort": best_effort, "window_end": NOW.isoformat()},
        created_at=NOW,
    ))


def _seed_run(s, name, *, verdict, finished, level="C2"):
    s.add(CertificationRun(
        subject_type="block", subject_id=name, version="1.0.0", level=level,
        n=1, pass_count=1 if verdict == "pass" else 0,
        live_pass_rate=1.0 if verdict == "pass" else 0.0,
        batch_id=f"b-{name}-{finished.isoformat()}", started_at=finished,
        finished_at=finished, verdict=verdict,
    ))


class TestGrade:
    def test_ok_fresh_pass(self, api):
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            _seed_run(s, "hn_search_probe", verdict="pass", finished=NOW - timedelta(days=3))
            s.commit()
            assert grade(s, "hn_search_probe", now=NOW) == "ok"

    def test_degraded_fresh_fail(self, api):
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            _seed_run(s, "hn_search_probe", verdict="below_threshold",
                      finished=NOW - timedelta(days=1))
            s.commit()
            assert grade(s, "hn_search_probe", now=NOW) == "degraded"

    def test_stale_beyond_7_days(self, api):
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            _seed_run(s, "hn_search_probe", verdict="pass",
                      finished=NOW - timedelta(days=7, seconds=1))  # 恰过窗口
            s.commit()
            assert grade(s, "hn_search_probe", now=NOW) == "stale"

    def test_stale_no_runs(self, api):
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            s.commit()
            assert grade(s, "hn_search_probe", now=NOW) == "stale"

    def test_latest_run_wins(self, api):
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            _seed_run(s, "hn_search_probe", verdict="pass", finished=NOW - timedelta(days=10))
            _seed_run(s, "hn_search_probe", verdict="below_threshold",
                      finished=NOW - timedelta(days=2))
            s.commit()
            assert grade(s, "hn_search_probe", now=NOW) == "degraded"


class TestAppHealth:
    def _seed_app(self, api, blocks, runs):
        with api.app.state.session_factory() as s:
            for b in blocks:
                _seed_block(s, b)
            for name, verdict, finished in runs:
                _seed_run(s, name, verdict=verdict, finished=finished)
            app = App(name="hn_weekly", title="HN 周报", created_at=NOW)
            s.add(app)
            s.flush()
            s.add(AppVersion(app_id=app.id, version="0.1.0", status="published",
                             composition_json=[{"block": b, "params": {}} for b in blocks],
                             created_at=NOW))
            s.commit()
            return app

    def test_app_takes_worst_grade(self, api):
        app = self._seed_app(
            api, ["hn_search_probe", "excel_export"],
            [("hn_search_probe", "pass", NOW - timedelta(days=1)),
             ("excel_export", "below_threshold", NOW - timedelta(days=1))])
        with api.app.state.session_factory() as s:
            assert app_health(s, app, now=NOW) == "degraded"

    def test_app_all_ok(self, api):
        app = self._seed_app(
            api, ["hn_search_probe", "excel_export"],
            [("hn_search_probe", "pass", NOW - timedelta(days=1)),
             ("excel_export", "pass", NOW - timedelta(days=2))])
        with api.app.state.session_factory() as s:
            assert app_health(s, app, now=NOW) == "ok"

    def test_store_api_exposes_health(self, api):
        self._seed_app(api, ["hn_search_probe"],
                       [("hn_search_probe", "pass", NOW - timedelta(days=1))])
        r = api.client.get("/api/v1/store/apps/hn_weekly")
        assert r.json()["health"] == "ok"

    def test_store_list_shows_health(self, api):
        self._seed_app(api, ["hn_search_probe"],
                       [("hn_search_probe", "below_threshold", NOW - timedelta(days=1))])
        apps = api.client.get("/api/v1/store/apps").json()
        assert apps[0]["health"] == "degraded"
