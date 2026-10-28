"""T2.21 注册/登录页与 My Library（docs/17）：表单流 + 运行指引固定块。"""
from datetime import datetime

from forge_server.models import App, AppVersion

NOW = datetime(2026, 10, 26, 12, 0, 0)
PASSWORD = "correct-horse-42"


def _seed_app(api, name="hn_weekly", status="published"):
    with api.app.state.session_factory() as s:
        app = App(name=name, title="HN 周报", created_at=NOW)
        s.add(app)
        s.flush()
        s.add(AppVersion(app_id=app.id, version="0.1.0", status=status,
                         composition_json=[{"block": "hn_search_probe", "params": {}}],
                         created_at=NOW))
        s.commit()


def _register(api, email="a@example.com", password=PASSWORD):
    return api.client.post("/register", data={"email": email, "password": password},
                           follow_redirects=False)


def _login(api, email="a@example.com", password=PASSWORD):
    return api.client.post("/login", data={"email": email, "password": password},
                           follow_redirects=False)


class TestAuthPages:
    def test_register_form_redirects_and_sets_cookie(self, api):
        _seed_app(api)
        r = _register(api)
        assert r.status_code == 302 and r.headers["location"] == "/store"
        assert "forge_sid" in r.headers.get("set-cookie", "")

    def test_register_duplicate_shows_error_inline(self, api):
        _seed_app(api)
        _register(api)
        r = _register(api)
        assert r.status_code == 200
        assert "邮箱已注册" in r.text

    def test_register_invalid_password_message(self, api):
        r = _register(api, password="short")
        assert r.status_code == 200
        assert "密码长度需在 8-128 位之间" in r.text

    def test_login_success_redirect(self, api):
        _seed_app(api)
        _register(api)
        api.client.cookies.clear()
        r = _login(api)
        assert r.status_code == 302 and r.headers["location"] == "/store"

    def test_login_wrong_password_inline_error(self, api):
        _seed_app(api)
        _register(api)
        api.client.cookies.clear()
        r = _login(api, password="nope-nope-nope")
        assert r.status_code == 200
        assert "邮箱或密码错误" in r.text

    def test_login_page_renders(self, api):
        r = api.client.get("/login")
        assert r.status_code == 200 and "登录" in r.text and "注册" in r.text


class TestLibrary:
    def test_library_requires_login_redirect(self, api):
        from fastapi.testclient import TestClient

        fresh = TestClient(api.app)  # 无 Cookie（共享 client 可能带登录态）
        r = fresh.get("/me/library", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/login"

    def test_library_empty_state(self, api):
        _seed_app(api)
        _register(api)
        r = api.client.get("/me/library")
        assert r.status_code == 200
        assert "还没有获取" in r.text or "商店" in r.text

    def test_acquire_via_web_then_library_shows_app(self, api):
        _seed_app(api)
        _register(api)
        r = api.client.post("/store/app/hn_weekly/acquire", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/me/library"
        page = api.client.get("/me/library").text
        assert "hn_weekly" in page and "HN 周报" in page
        assert "未激活" in page

    def test_acquire_unauthenticated_redirects_login(self, api):
        from fastapi.testclient import TestClient

        _seed_app(api)
        fresh = TestClient(api.app)
        r = fresh.post("/store/app/hn_weekly/acquire", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/login"

    def test_acquire_unpublished_redirects_with_error(self, api):
        _seed_app(api, name="draft_app", status="draft")
        _register(api)
        r = api.client.post("/store/app/draft_app/acquire", follow_redirects=False)
        assert r.status_code == 302
        follow = api.client.get(r.headers["location"])
        assert "应用不存在或未上架" in follow.text


class TestRunGuide:
    def test_library_contains_runner_guide(self, api, tmp_path):
        _seed_app(api)
        _register(api)
        api.client.post("/store/app/hn_weekly/acquire")
        api.app.state.dist_root = tmp_path
        api.app.state.runner_version = "0.2.0"
        (tmp_path / "forge-runner-0.2.0-win.exe").write_bytes(b"fake")
        page = api.client.get("/me/library").text
        assert "/download/forge-runner-0.2.0-win.exe" in page
        assert "forge-runner login" in page      # 命令行三步原文
        assert "forge-runner run" in page
        assert "artifacts" in page or "产物" in page

    def test_library_guide_when_runner_unpublished(self, api):
        _seed_app(api)
        _register(api)
        api.app.state.dist_root = None
        api.app.state.runner_version = ""
        page = api.client.get("/me/library").text
        assert "运行器" in page  # 指引块始终在（未发布时提示即将上线）
