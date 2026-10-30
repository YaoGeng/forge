"""MS-3 T1 E4 env 门控 CORS（docs/18）：仅 FORGE_CORS_ORIGINS 非空才挂
CORSMiddleware（逗号白名单、credentials=False）；缺省关闭 = 生产同域零 CORS。
"""
from fastapi.testclient import TestClient

ORIGIN_OK = "http://localhost:5173"


def _client(make_app):
    return TestClient(make_app())


class TestCorsDefaultOff:
    def test_no_cors_headers_without_env(self, make_app, monkeypatch):
        monkeypatch.delenv("FORGE_CORS_ORIGINS", raising=False)
        client = _client(make_app)
        r = client.get("/healthz", headers={"Origin": ORIGIN_OK})
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers
        # 无中间件：预检不由 CORS 拦截 → 路由无 OPTIONS 即 405
        pre = client.options("/api/v1/apps", headers={
            "Origin": ORIGIN_OK, "Access-Control-Request-Method": "GET"})
        assert pre.status_code == 405

    def test_blank_env_treated_as_off(self, make_app, monkeypatch):
        monkeypatch.setenv("FORGE_CORS_ORIGINS", " , ")  # 仅逗号空白 → 无有效来源
        client = _client(make_app)
        r = client.get("/healthz", headers={"Origin": ORIGIN_OK})
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers


class TestCorsEnabled:
    def test_allowed_origin_simple_request(self, make_app, monkeypatch):
        monkeypatch.setenv(
            "FORGE_CORS_ORIGINS", f"{ORIGIN_OK}, https://admin.example.com")
        client = _client(make_app)
        r = client.get("/healthz", headers={"Origin": ORIGIN_OK})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == ORIGIN_OK
        assert r.headers.get("access-control-allow-credentials") != "true"

    def test_preflight_allowed(self, make_app, monkeypatch):
        monkeypatch.setenv("FORGE_CORS_ORIGINS", ORIGIN_OK)
        client = _client(make_app)
        r = client.options("/api/v1/apps", headers={
            "Origin": ORIGIN_OK, "Access-Control-Request-Method": "GET"})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == ORIGIN_OK

    def test_non_whitelisted_origin_gets_no_grant(self, make_app, monkeypatch):
        monkeypatch.setenv("FORGE_CORS_ORIGINS", ORIGIN_OK)
        client = _client(make_app)
        r = client.get("/healthz", headers={"Origin": "http://evil.example"})
        # 直连放行（CORS 是浏览器许可见非访问控制），但不给跨域许可头
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers
