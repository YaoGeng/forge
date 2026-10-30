"""T2.01 买家账号与登录（docs/17）：注册/登录/会话/限频。

铁律：密码只存 scrypt 摘要；明文密码不得出现在任何响应；未登录 401 中文。
"""
import pytest

EMAIL = "buyer@example.com"
PASSWORD = "correct-horse-42"


def _register(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


class TestRegister:
    def test_register_returns_user_id(self, api):
        r = _register(api.client)
        assert r.status_code == 201
        assert isinstance(r.json()["user_id"], int)

    def test_duplicate_email_409(self, api):
        _register(api.client)
        r = _register(api.client)
        assert r.status_code == 409
        assert r.json()["detail"] == "邮箱已注册"

    @pytest.mark.parametrize("payload", [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "", "password": PASSWORD},
        {"email": EMAIL, "password": "short"},
        {"email": EMAIL, "password": ""},
        {"email": EMAIL, "password": "x" * 129},
    ])
    def test_invalid_input_422(self, api, payload):
        assert _register(api.client, **payload).status_code == 422

    def test_password_never_echoed(self, api):
        r = _register(api.client)
        assert PASSWORD not in r.text


class TestLogin:
    def test_login_returns_token_and_sets_cookie(self, api):
        _register(api.client)
        r = _login(api.client)
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == 1 and isinstance(body["token"], str) and body["token"]
        set_cookie = r.headers["set-cookie"]
        assert "forge_sid=" in set_cookie and "HttpOnly" in set_cookie
        assert PASSWORD not in r.text

    def test_wrong_password_401_same_message_as_unknown_email(self, api):
        _register(api.client)
        wrong = _login(api.client, password="nope-nope-nope")
        unknown = _login(api.client, email="ghost@example.com")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"] == "邮箱或密码错误"

    def test_password_never_in_any_response(self, api):
        _register(api.client)
        for r in (_login(api.client), _login(api.client, password="nope-nope-nope")):
            assert PASSWORD not in r.text

    def test_email_rate_limit_429(self, api):
        _register(api.client)
        for _ in range(5):
            _login(api.client, password="nope-nope-nope")  # 同邮箱连续失败也计数
        r = _login(api.client, password="nope-nope-nope")
        assert r.status_code == 429


class TestSession:
    def test_me_via_bearer(self, api):
        _register(api.client)
        token = _login(api.client).json()["token"]
        r = api.client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"user_id": 1, "email": EMAIL}

    def test_me_via_cookie(self, api):
        _register(api.client)
        _login(api.client)  # TestClient 记住 Cookie
        assert api.client.get("/api/v1/me").status_code == 200

    @pytest.mark.parametrize("headers", [
        {},
        {"Authorization": "Bearer bogus-token"},
    ])
    def test_me_unauthenticated_401(self, api, headers):
        _register(api.client)
        r = api.client.get("/api/v1/me", headers=headers)
        assert r.status_code == 401
        assert "登录" in r.json()["detail"]

    def test_logout_invalidates_session(self, api):
        _register(api.client)
        token = _login(api.client).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        assert api.client.post("/api/v1/auth/logout", headers=auth).status_code == 204
        assert api.client.get("/api/v1/me", headers=auth).status_code == 401

    def test_expired_session_401(self, api, clock):
        _register(api.client)
        token = _login(api.client).json()["token"]
        clock.advance(days=31)  # 会话 30 天过期
        r = api.client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
