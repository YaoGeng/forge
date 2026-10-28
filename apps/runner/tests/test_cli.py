"""T2.10 CLI 与本地状态（docs/17）：login 落 state（密码绝不落盘）；未登录 run 退出码 2。"""
import json
import os

import pytest

from forge_runner import cli, state as state_mod

PASSWORD = "correct-horse-42"


class FakeClient:
    """记录调用的假 HTTP 客户端（CLI 单测不触网）。"""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or {}

    def post_json(self, path, body, token=None):
        self.calls.append(("POST", path, body))
        return self._responses.get(path, (200, {"token": "tok-1", "user_id": 7}))

    def get(self, path, token=None):
        self.calls.append(("GET", path, None))
        return self._responses.get(path, (200, []))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    return tmp_path / "forge-home"


class TestLogin:
    def test_login_saves_token_not_password(self, home):
        client = FakeClient()
        cli.cmd_login("a@example.com", PASSWORD, client)
        st = state_mod.load()
        assert st["token"] == "tok-1" and st["user_id"] == 7
        assert st["email"] == "a@example.com"
        raw = (home / "state.json").read_text(encoding="utf-8")
        assert PASSWORD not in raw

    def test_login_failure_raises_cli_error(self, home):
        client = FakeClient({"/api/v1/auth/login": (401, {"detail": "邮箱或密码错误"})})
        with pytest.raises(cli.CliError, match="邮箱或密码错误"):
            cli.cmd_login("a@example.com", "wrong-pass-1", client)

    def test_state_file_created_with_home(self, home):
        assert not (home / "state.json").exists()
        cli.cmd_login("a@example.com", PASSWORD, FakeClient())
        assert (home / "state.json").exists()

    @pytest.mark.skipif(os.name != "posix", reason="chmod 0600 仅 posix 可校验")
    def test_state_permissions_0600(self, home):
        cli.cmd_login("a@example.com", PASSWORD, FakeClient())
        assert os.stat(home / "state.json").st_mode & 0o777 == 0o600


class TestLogout:
    def test_logout_clears_token(self, home):
        cli.cmd_login("a@example.com", PASSWORD, FakeClient())
        cli.cmd_logout(FakeClient())
        assert "token" not in state_mod.load()


class TestRunGuard:
    def test_run_without_login_exits_2_with_chinese_message(self, home, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_run("hn_weekly", FakeClient(), home)
        assert exc.value.code == 2
        assert "登录" in capsys.readouterr().err

    def test_library_without_login_exits_2(self, home):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_library(FakeClient(), home)
        assert exc.value.code == 2


class TestLibrary:
    def test_library_renders_entitlements(self, home, capsys):
        cli.cmd_login("a@example.com", PASSWORD, FakeClient())
        client = FakeClient({"/api/v1/me/entitlements": (200, [
            {"entitlement_id": 1, "app": "hn_weekly", "version": "0.1.0",
             "activated_at": None, "source": "free_ms2",
             "acquired_at": "2026-10-26T12:00:00"},
        ])})
        cli.cmd_library(client, home)
        out = capsys.readouterr().out
        assert "hn_weekly" in out and "0.1.0" in out
