"""T1.12：ComponentError + runtime 外观桩用例（错误码冻结集、权限门、桩面、跨卡一致性）。"""
from pathlib import Path

import pytest

from forge_block_sdk import (
    BackendNotWired,
    COMPONENT_ERROR_CODES,
    ComponentError,
    CredentialHandle,
    PermissionDenied,
    RuntimeFacade,
    for_block,
    lint,
    load_block,
    load_interactions,
)
from test_lint_rules import hits, overlay

CORPUS = Path(__file__).resolve().parent / "corpus" / "valid" / "demo_block"

FAMILIES = (
    "browser", "file", "office", "ai", "code", "data",
    "api", "credential", "confirm", "interact", "probe",
)


def demo_spec():
    return load_block(CORPUS / "block.yaml")


def demo_facade():
    return for_block(demo_spec(), load_interactions(CORPUS / "interactions.yaml"))


def test_error_code_subset_frozen():
    assert COMPONENT_ERROR_CODES == frozenset(
        {"selector_missing", "output_schema_violation", "component_timeout"}
    )


def test_component_error_roundtrip():
    e = ComponentError("selector_missing", "选择器未命中", detail={"selector": ".a"})
    assert (e.code, e.message, e.detail) == ("selector_missing", "选择器未命中", {"selector": ".a"})
    assert "selector_missing" in str(e)


def test_unknown_code_rejected():
    with pytest.raises(ValueError):
        ComponentError("permission_denied", "broker 域错误不属于组件可抛集")


def test_facade_families_complete():
    f = demo_facade()
    assert isinstance(f, RuntimeFacade)
    for fam in FAMILIES:
        assert hasattr(f, fam), fam


def test_undeclared_family_denied():
    f = demo_facade()
    with pytest.raises(PermissionDenied):
        f.file.read("/tmp/x")
    with pytest.raises(PermissionDenied):
        f.probe.inspect("https://www.xiaohongshu.com")


def test_declared_family_not_wired():
    f = demo_facade()
    with pytest.raises(BackendNotWired):
        f.browser.open("https://www.xiaohongshu.com")
    with pytest.raises(BackendNotWired):
        f.ai.generate_text("总结")


def test_credential_gate():
    f = demo_facade()
    with pytest.raises(BackendNotWired):
        f.credential.get("xhs_login")
    with pytest.raises(PermissionDenied):
        f.credential.get("nope")


def test_interact_ask_gate():
    f = demo_facade()
    with pytest.raises(BackendNotWired):
        f.interact.ask({"type": "input", "title": "输入主题"})
    with pytest.raises(PermissionDenied):
        f.interact.ask({"type": "captcha", "title": "验证码"})
    with pytest.raises(TypeError):
        f.interact.ask("input")
    with pytest.raises(TypeError):
        f.interact.ask({"title": "缺 type"})


def test_credential_handle_shape():
    h1 = CredentialHandle()
    h2 = CredentialHandle()
    assert h1.token and h1.token != h2.token


def test_cross_lint_component_error(demo_block_dir):
    src = (
        "from forge_block_sdk import ComponentError, runtime\n\n\n"
        "def run(p):\n"
        "    try:\n"
        "        runtime.browser.open('https://www.xiaohongshu.com')\n"
        "    except Exception:\n"
        "        raise ComponentError('selector_missing', '未命中')\n"
    )
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert not hits(result, "bare_except")
    assert result.ok


def test_for_block_rejects_bad_interactions():
    with pytest.raises(TypeError):
        for_block(demo_spec(), "ab")
    with pytest.raises(TypeError):
        for_block(demo_spec(), 42)


def test_component_error_pickle_roundtrip():
    import pickle

    e = ComponentError("selector_missing", "未命中", detail={"selector": ".a"})
    e2 = pickle.loads(pickle.dumps(e))
    assert (e2.code, e2.message, e2.detail) == (e.code, e.message, e.detail)


def test_for_block_default_interactions_fail_closed():
    f = for_block(demo_spec())
    with pytest.raises(PermissionDenied):
        f.interact.ask({"type": "input", "title": "输入主题"})
