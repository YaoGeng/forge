"""T2.10 ChainRunner 移植一致性（docs/17）：runner 与 server 输出逐字段相等（防分叉）。"""
import pytest

from forge_runner.chain import BindingError, ChainRunner, RunOutcome

COMPOSITION = [
    {"block": "site_probe", "params": {"q": "python"}},
    {"block": "export", "params": {"out": "r.xlsx"},
     "bindings": {"rows": "site_probe.rows"}},
    {"block": "digest", "params": {}},
]

OUTCOMES = {
    "site_probe": {"mode": "local", "ok": True, "output": {"rows": "a;b"}},
    "export": {"mode": "local", "ok": True, "output": {"path": "r.xlsx"}},
    "digest": {"mode": "local", "ok": True, "output": None},
}


def _fake_port(outcome_cls, outcomes):
    class FakePort:
        def run_once(self, ref, params=None, *, mode="local", browser_factory=None):
            return outcome_cls(**outcomes[ref])

    return FakePort()


def _server_execute(composition, outcomes):
    from forge_server.chain import ChainRunner as ServerChain
    from forge_server.sandbox import RunOutcome as ServerOutcome

    port = _fake_port(ServerOutcome, outcomes)
    routes = {name: (port, name) for name in outcomes}
    return ServerChain(routes).execute(composition)


def _runner_execute(composition, outcomes):
    port = _fake_port(RunOutcome, outcomes)
    routes = {name: (port, name) for name in outcomes}
    return ChainRunner(routes).execute(composition)


class TestConsistency:
    def test_happy_path_outputs_identical(self):
        assert _runner_execute(COMPOSITION, OUTCOMES) == _server_execute(
            COMPOSITION, OUTCOMES)

    def test_step_failure_stops_chain_identically(self):
        outcomes = {
            "site_probe": {"mode": "local", "ok": False,
                           "failure_class": "selector_missing"},
            "export": OUTCOMES["export"],  # 不应被触达
        }
        assert _runner_execute(COMPOSITION[:2], outcomes) == _server_execute(
            COMPOSITION[:2], outcomes)

    def test_binding_error_same_semantics(self):
        port = _fake_port(RunOutcome, {"site_probe": OUTCOMES["site_probe"],
                                       "export": OUTCOMES["export"]})
        runner = ChainRunner({"site_probe": (port, "site_probe"),
                              "export": (port, "export")})
        with pytest.raises(BindingError):
            runner.execute([
                {"block": "site_probe", "params": {}},
                {"block": "export", "params": {},
                 "bindings": {"rows": "site_probe.missing_key"}},
            ])

    def test_unregistered_block_env_error(self):
        result = ChainRunner({}).execute([{"block": "ghost", "params": {}}])
        assert result["ok"] is False
        assert result["steps"][0]["failure_class"] == "env_error"


class TestOutcomeShape:
    def test_runoutcome_fields(self):
        o = RunOutcome(mode="local", ok=True, output={"x": 1})
        assert o.mode == "local" and o.ok and o.output == {"x": 1}
        assert o.failure_class is None and o.step_results == ()
