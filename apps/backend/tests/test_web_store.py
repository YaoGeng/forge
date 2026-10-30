"""T2.20 商店列表/详情页（docs/17）：信任字段 v2 渲染铁律的页面级断言。

铁律（M03 §1/§3.1）：通过率必带样本量；样本不足显示"数据不足"不出数字；
页脚声明原文一字不差；best_effort 首屏警示不可折叠。
"""
from datetime import datetime

from forge_server.models import App, AppVersion, Block, BlockVersion, RunReport

NOW = datetime(2026, 10, 26, 12, 0, 0)
FOOTER = "运行条件与成功率以信任字段为准；平台审核与认证不构成对运行结果的担保"


def _seed_block(s, name, *, level="C2", best_effort=False, domains=None, rate=1.0, n=20):
    block = Block(name=name, created_at=NOW)
    s.add(block)
    s.flush()
    s.add(BlockVersion(
        block_id=block.id, version="1.0.0", certification_level=level,
        reliability_json={"level": level, "n": n, "live_pass_rate": rate,
                          "best_effort": best_effort,
                          "window_end": NOW.isoformat()},
        domains_json=domains, created_at=NOW,
    ))


def _seed_app(s, name, title, blocks, *, published=True):
    app = App(name=name, title=title, created_at=NOW)
    s.add(app)
    s.flush()
    s.add(AppVersion(
        app_id=app.id, version="0.1.0", status="published" if published else "draft",
        composition_json=[{"block": b, "params": {}} for b in blocks],
        created_at=NOW,
    ))


def _seeded(api, blocks_spec, app_blocks, *, app_name="hn_weekly", title="HN 周报",
            published=True):
    with api.app.state.session_factory() as s:
        for spec in blocks_spec:
            _seed_block(s, **spec)
        _seed_app(s, app_name, title, app_blocks, published=published)
        s.commit()
    return api.client


class TestStoreList:
    def test_list_cards_with_sample_sized_rates(self, api):
        _seeded(api, [{"name": "hn_search_probe"}, {"name": "excel_export"}],
                ["hn_search_probe", "excel_export"])
        r = api.client.get("/store")
        assert r.status_code == 200
        assert "HN 周报" in r.text
        assert "100%（近 40 次，2026-10）" in r.text   # M03 §3.1 格式，必带样本量
        assert ">C2<" in r.text                        # 认证等级徽标

    def test_draft_app_not_listed(self, api):
        _seeded(api, [{"name": "url_read"}], ["url_read"], published=False,
                app_name="draft_app")
        assert "draft_app" not in api.client.get("/store").text

    def test_list_links_to_detail(self, api):
        _seeded(api, [{"name": "url_read"}], ["url_read"])
        assert 'href="/store/app/hn_weekly"' in api.client.get("/store").text


class TestAppDetail:
    def _detail(self, api, **kwargs):
        _seeded(api,
                [{"name": "hn_search_probe"}, {"name": "excel_export"}],
                ["hn_search_probe", "excel_export"], **kwargs)
        r = api.client.get("/store/app/hn_weekly")
        assert r.status_code == 200
        return r.text

    def test_footer_verbatim(self, api):
        assert FOOTER in self._detail(api)

    def test_user_pass_insufficient_shows_placeholder(self, api):
        text = self._detail(api)
        assert "数据不足" in text
        assert text.count("100%") == 1  # 仅认证通过率有数字，用户成功率不出数字

    def test_user_pass_with_samples_shows_rate(self, api):
        text = self._detail(api)
        with api.app.state.session_factory() as s:
            for i in range(1, 31):
                s.add(RunReport(entitlement_id=i, app_name="hn_weekly", ok=i <= 24,
                                env_class="windows", client_version="0.1",
                                first_run=(i == 1), created_at=NOW))
            s.commit()
        text = api.client.get("/store/app/hn_weekly").text
        assert "80%（近 30 次" in text
        assert "数据不足" not in text

    def test_c1_annotation_pinned(self, api):
        _seeded(api,
                [{"name": "login_demo_probe", "level": "C1",
                  "domains": ["saucedemo.com"]},
                 {"name": "excel_export"}],
                ["login_demo_probe", "excel_export"])
        text = api.client.get("/store/app/hn_weekly").text
        assert "平台环境实测，平台抽查复核" in text  # 平台自制期固定文案（测试钉死）
        assert "saucedemo.com" in text

    def test_best_effort_banner_uncollapsible(self, api):
        _seeded(api,
                [{"name": "baidu_home_watch", "best_effort": True},
                 {"name": "csv_export"}],
                ["baidu_home_watch", "csv_export"])
        text = api.client.get("/store/app/hn_weekly").text
        assert 'class="best-effort-banner"' in text        # 固定 class，无折叠交互
        assert "details" not in text.split("best-effort-banner")[1][:120]  # 非 <details> 折叠
        assert "高变更" in text

    def test_static_css_served(self, api):
        r = api.client.get("/static/store.css")
        assert r.status_code == 200
        assert "--primary:#3E5C3A" in r.text          # 橄榄绿主色（原型 :root 同值）
        assert "--accent:#C25E5E" in r.text           # 豆沙红点缀（原型同值）
