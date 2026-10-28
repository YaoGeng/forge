"""T2.02 商店读 API 与信任字段 v2（docs/17）。

铁律（M03 §1）：通过率必带样本量；user_pass 样本 <30 → null（渲染"数据不足"）；
页脚声明原文一字不差；未上架应用 404。
"""
from datetime import datetime, timedelta

from forge_server.models import (
    App,
    AppVersion,
    Block,
    BlockVersion,
    CertificationRun,
    RunReport,
)

FOOTER = "运行条件与成功率以信任字段为准；平台审核与认证不构成对运行结果的担保"
NOW = datetime(2026, 10, 26, 12, 0, 0)


def _seed_block(s, name, *, level="C2", best_effort=False, domains=None,
                rate=1.0, n=20):
    block = Block(name=name, created_at=NOW)
    s.add(block)
    s.flush()
    s.add(BlockVersion(
        block_id=block.id, version="1.0.0", certification_level=level,
        reliability_json={"level": level, "n": n, "live_pass_rate": rate,
                          "best_effort": best_effort,
                          "window_end": NOW.isoformat()},
        side_effects=False, domains_json=domains, created_at=NOW,
    ))
    s.add(CertificationRun(
        subject_type="block", subject_id=name, version="1.0.0", level=level,
        n=n, pass_count=int(rate * n), live_pass_rate=rate, regression_pass_rate=rate,
        batch_id=f"b-{name}", started_at=NOW - timedelta(days=1), finished_at=NOW,
        verdict="pass",
    ))


def _seed_app(s, name, title, blocks, *, published=True):
    app = App(name=name, title=title, created_at=NOW)
    s.add(app)
    s.flush()
    s.add(AppVersion(
        app_id=app.id, version="0.1.0",
        status="published" if published else "draft",
        composition_json=[{"block": b, "params": {}} for b in blocks],
        created_at=NOW,
    ))
    return app


def _seeded(api, blocks_spec, app_blocks, *, published=True, app_name="hn_weekly"):
    with api.app.state.session_factory() as s:
        for spec in blocks_spec:
            _seed_block(s, **spec)
        _seed_app(s, app_name, "HN 周报", app_blocks, published=published)
        s.commit()
    return api.client


class TestStoreList:
    def test_list_only_published_with_simplified_fields(self, api):
        _seeded(api,
                [{"name": "hn_search_probe"}, {"name": "excel_export"}],
                ["hn_search_probe", "excel_export"])
        _seeded(api, [{"name": "url_read"}], ["url_read"],
                published=False, app_name="draft_app")
        r = api.client.get("/api/v1/store/apps")
        assert r.status_code == 200
        apps = r.json()
        assert [a["name"] for a in apps] == ["hn_weekly"]
        app = apps[0]
        assert app["title"] == "HN 周报"
        assert app["level"] == "C2"
        # 精简字段同样必带样本量（M03 §7.10）
        cert = app["cert_pass"]
        assert cert["n"] == 40 and cert["rate"] == 1.0 and cert["window"]
        assert app["user_pass"] is None  # 无上报 → null（渲染层显示"数据不足"）

    def test_detail_full_trust_fields(self, api):
        _seeded(api,
                [{"name": "hn_search_probe"},
                 {"name": "excel_export"}],
                ["hn_search_probe", "excel_export"])
        r = api.client.get("/api/v1/store/apps/hn_weekly")
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "hn_weekly" and d["title"] == "HN 周报"
        assert d["level"] == "C2"
        assert d["cert_pass"] == {"rate": 1.0, "n": 40, "window": NOW.isoformat()}
        assert d["user_pass"] is None
        assert d["maintenance"] == "平台维护"
        assert d["token_cost"] == "0（无模型调用）"
        assert d["login_sites"] == []
        assert d["best_effort"] is False
        assert d["footer"] == FOOTER

    def test_c1_app_level_and_login_sites(self, api):
        _seeded(api,
                [{"name": "login_demo_probe", "level": "C1",
                  "domains": ["saucedemo.com"]},
                 {"name": "excel_export"}],
                ["login_demo_probe", "excel_export"])
        d = api.client.get("/api/v1/store/apps/hn_weekly").json()
        assert d["level"] == "C1"           # 含 C1 块 → 应用 C1
        assert d["login_sites"] == ["saucedemo.com"]

    def test_best_effort_true_when_high_tier_block(self, api):
        _seeded(api,
                [{"name": "baidu_home_watch", "best_effort": True},
                 {"name": "csv_export"}],
                ["baidu_home_watch", "csv_export"])
        d = api.client.get("/api/v1/store/apps/hn_weekly").json()
        assert d["best_effort"] is True

    def test_unpublished_or_unknown_404(self, api):
        _seeded(api, [{"name": "url_read"}], ["url_read"],
                published=False, app_name="draft_app")
        assert api.client.get("/api/v1/store/apps/draft_app").status_code == 404
        r = api.client.get("/api/v1/store/apps/ghost")
        assert r.status_code == 404
        assert r.json()["detail"] == "应用不存在或未上架"


class TestUserPassThreshold:
    def _seed_with_reports(self, api, count, ok=30):
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            _seed_block(s, "excel_export")
            _seed_app(s, "hn_weekly", "HN 周报", ["hn_search_probe", "excel_export"])
            for i in range(1, count + 1):
                s.add(RunReport(
                    entitlement_id=i, app_name="hn_weekly", ok=i <= ok,
                    failure_class=None, env_class="windows", client_version="0.1",
                    first_run=(i == 1), created_at=NOW,
                ))
            s.commit()
        return api.client.get("/api/v1/store/apps/hn_weekly").json()

    def test_below_30_samples_null(self, api):
        d = self._seed_with_reports(api, count=29, ok=29)
        assert d["user_pass"] is None

    def test_at_30_samples_rate_shown_with_n(self, api):
        d = self._seed_with_reports(api, count=30, ok=24)
        assert d["user_pass"] == {"rate": 0.8, "n": 30}


class TestRunnerEndpoint:
    def test_runner_info_with_published_exe(self, api, tmp_path):
        exe = tmp_path / "forge-runner-0.1.0-win.exe"
        exe.write_bytes(b"fake-exe-bytes")
        api.app.state.dist_root = tmp_path
        api.app.state.runner_version = "0.1.0"
        import hashlib
        r = api.client.get("/api/v1/store/runner")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == "0.1.0"
        assert body["url"] == "/download/forge-runner-0.1.0-win.exe"
        assert body["sha256"] == "sha256:" + hashlib.sha256(b"fake-exe-bytes").hexdigest()

    def test_runner_not_published_404(self, api):
        api.app.state.dist_root = None
        api.app.state.runner_version = ""
        r = api.client.get("/api/v1/store/runner")
        assert r.status_code == 404
        assert r.json()["detail"] == "运行器尚未发布"
