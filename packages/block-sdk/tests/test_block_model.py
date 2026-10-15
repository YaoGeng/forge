"""T1.10：block.yaml v2 + interactions.yaml 校验器用例（冻结字段集、加载、负例门）。"""
import dataclasses
from pathlib import Path

import pytest

from forge_block_sdk import (
    BlockSpec,
    InteractionSpec,
    PermissionSpec,
    ReliabilitySpec,
    RuntimeSpec,
    ValidationError,
    load_block,
    load_interactions,
    validate_block_dir,
)
from forge_block_sdk.model import BLOCK_FIELDS

CORPUS = Path(__file__).resolve().parent / "corpus" / "valid" / "demo_block"

C1_FIELDS = {
    "schema_version", "kind", "name", "version", "title", "site_change_tier",
    "side_effects", "capabilities", "permissions", "runtime", "reliability",
    "ai_description", "default_response",
}


def test_frozen_field_names():
    assert {f.name for f in dataclasses.fields(BlockSpec)} == C1_FIELDS
    assert C1_FIELDS == set(BLOCK_FIELDS)


def test_valid_corpus_loads():
    spec = load_block(CORPUS)
    assert isinstance(spec, BlockSpec)
    assert spec.schema_version == 2 and spec.kind == "block"
    assert spec.name == "xhs_note_fetch_demo" and spec.version == "1.0.0"
    assert spec.title == "小红书笔记抓取（演示）"
    assert spec.site_change_tier == "high" and spec.side_effects is False
    assert spec.capabilities == ("browser", "ai_fast", "interact_input", "interact_login")
    assert spec.permissions == (
        PermissionSpec("domain", "xiaohongshu.com", True),
        PermissionSpec("credential", "xhs_login", True),
        PermissionSpec("ai", "fast", True),
        PermissionSpec("interact", "input", True),
        PermissionSpec("interact", "login", True),
    )
    assert spec.runtime == RuntimeSpec("python", "main.py", 300)
    assert spec.reliability == ReliabilitySpec(
        "C1", 0.90, 20, "2026-10-12", "creator-local"
    )
    assert spec.ai_description == "根据主题抓取某站点首页相关笔记内容"
    assert spec.default_response is None


def test_valid_corpus_interactions():
    items = load_interactions(CORPUS / "interactions.yaml")
    assert items == (
        InteractionSpec("topic_input", "input", "输入主题", {"type": "string"}, False, None),
        InteractionSpec("xhs_login", "login", "登录小红书", None, True, "xiaohongshu.com"),
    )


def test_validate_block_dir_roundtrip(write_block):
    d = write_block(files={
        "main.py": "x = 1\n",
        "interactions.yaml": "- { id: a, type: input, title: A }\n",
        "tests/test.yaml": "assertion: schema\n",
    })
    spec = validate_block_dir(d)
    assert spec == load_block(d / "block.yaml")


def test_semver_gate(write_block):
    for bad in ("1.2", "v1.2.0", "1.2.0-rc.1", "1.2.9999", "01.2.3"):
        text = (CORPUS / "block.yaml").read_text(encoding="utf-8").replace(
            "version: 1.0.0", f"version: {bad}"
        )
        with pytest.raises(ValidationError):
            load_block(write_block(text))


@pytest.mark.parametrize("key", [
    "schema_version", "kind", "name", "version", "title", "site_change_tier",
    "side_effects", "capabilities", "permissions", "runtime", "ai_description",
])
def test_required_fields_missing(write_block, drop_line, drop_block, key):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    text = drop_block(base, key) if key in ("capabilities", "permissions", "runtime") else drop_line(base, key)
    with pytest.raises(ValidationError) as ei:
        load_block(write_block(text))
    assert ei.value.path.endswith("." + key)


def test_enum_gates(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    cases = [
        ("site_change_tier: high", "site_change_tier: critical"),
        ("adapter: python", "adapter: ruby"),
        ("value: \"fast\"", "value: \"ultra\""),
        ("value: \"input\"", "value: \"logout\""),
        ("type: domain", "type: blob"),
        ("level: C1", "level: C9"),
    ]
    for old, new in cases:
        with pytest.raises(ValidationError):
            load_block(write_block(base.replace(old, new)))


def test_structural_malformed_payload(write_block, tmp_path):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        load_block(write_block(base.replace(
            "capabilities:\n  - browser\n  - ai_fast\n  - interact_input\n  - interact_login",
            "capabilities: browser",
        )))
    with pytest.raises(ValidationError):
        load_block(write_block(base.replace(
            "permissions:\n  - { type: domain, value: \"xiaohongshu.com\", required: true }",
            "permissions:\n  - oops",
        )))
    with pytest.raises(ValidationError):
        load_block(write_block(base.replace(
            "runtime:\n  adapter: python\n  entry: main.py\n  timeout_sec: 300",
            "runtime: python",
        )))
    d = write_block(files={"interactions.yaml": "a: b\n"})
    with pytest.raises(ValidationError):
        load_interactions(d / "interactions.yaml")


def test_unknown_field_rejected(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        load_block(write_block(base + "extra: 1\n"))


def test_default_response_gate(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        load_block(write_block(base.replace("side_effects: false", "side_effects: true")))
    ok = base.replace(
        "side_effects: false",
        "side_effects: true\ndefault_response:\n  action: confirm_twice\n  payload: { proceed: true }",
    )
    spec = load_block(write_block(ok))
    assert spec.default_response == {"action": "confirm_twice", "payload": {"proceed": True}}
    with pytest.raises(ValidationError):
        load_block(write_block(base + "default_response: auto\n"))


def test_reliability_optional_but_complete(write_block, drop_block, drop_line):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    spec = load_block(write_block(drop_block(base, "reliability:")))
    assert spec.reliability is None
    with pytest.raises(ValidationError):
        load_block(write_block(drop_line(base, "level: C1")))


def test_measured_at_accepts_date_and_iso(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    spec = load_block(write_block(base.replace(
        "measured_at: 2026-10-12", "measured_at: \"2026-10-12\""
    )))
    assert spec.reliability.measured_at == "2026-10-12"


def test_composite_block_unsupported(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError) as ei:
        load_block(write_block(base.replace("kind: block", "kind: composite_block")))
    assert "composite_block" in str(ei.value)


@pytest.fixture
def interactions_text():
    return (
        "- { id: topic_input, type: input, title: 输入主题, schema: { type: string }, optional: false }\n"
        "- { id: xhs_login, type: login, title: 登录小红书, site: xiaohongshu.com, optional: true }\n"
    )


def test_interactions_login_requires_site(write_block, interactions_text):
    d = write_block(files={"interactions.yaml": interactions_text.replace(
        "site: xiaohongshu.com, ", ""
    )})
    with pytest.raises(ValidationError):
        load_interactions(d / "interactions.yaml")


def test_interactions_site_only_on_login(write_block, interactions_text):
    d = write_block(files={"interactions.yaml": interactions_text.replace(
        "type: input, title: 输入主题,", "type: input, title: 输入主题, site: xiaohongshu.com,"
    )})
    with pytest.raises(ValidationError):
        load_interactions(d / "interactions.yaml")


def test_interactions_duplicate_id(write_block, interactions_text):
    d = write_block(files={"interactions.yaml": interactions_text + interactions_text.splitlines()[0] + "\n"})
    with pytest.raises(ValidationError):
        load_interactions(d / "interactions.yaml")


def test_interactions_type_and_top_level(write_block):
    bad_type = "- { id: a, type: foo, title: A }\n"
    d = write_block(files={"interactions.yaml": bad_type})
    with pytest.raises(ValidationError):
        load_interactions(d / "interactions.yaml")
    d2 = write_block(files={"interactions.yaml": "interactions: []\n"})
    with pytest.raises(ValidationError):
        load_interactions(d2 / "interactions.yaml")
    d3 = write_block(files={"interactions.yaml": "[]\n"})
    assert load_interactions(d3 / "interactions.yaml") == ()


def test_validate_block_dir_entry_gates(write_block, tmp_path):
    d = write_block(files={})  # 无 main.py
    with pytest.raises(ValidationError):
        validate_block_dir(d)
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    d2 = write_block(
        base.replace("adapter: python", "adapter: node"),
        files={"main.py": "x = 1\n"},
    )
    with pytest.raises(ValidationError):
        validate_block_dir(d2)


# ---- T1.10 评审修复轮（A4 首轮：1 Critical / 3 Important / Minor 收敛） ----


def _base() -> str:
    return (CORPUS / "block.yaml").read_text(encoding="utf-8")


def test_adapter_unhashable_rejected(write_block):
    with pytest.raises(ValidationError):
        load_block(write_block(_base().replace("adapter: python", "adapter: [python]")))


def test_nonstr_unknown_keys_rejected(write_block):
    with pytest.raises(ValidationError):
        load_block(write_block(_base() + "1: x\n"))
    d = write_block(files={"interactions.yaml": "- { id: a, type: input, title: A, 1: x }\n"})
    with pytest.raises(ValidationError):
        load_interactions(d / "interactions.yaml")


def test_entry_must_be_relative(write_block, tmp_path):
    outside = tmp_path / "evil.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    for bad in (str(outside).replace("\\", "/"), "../evil.py"):
        d = write_block(_base().replace("entry: main.py", f"entry: \"{bad}\""))
        with pytest.raises(ValidationError):
            load_block(d / "block.yaml")
        with pytest.raises(ValidationError):
            validate_block_dir(d)


def test_schema_version_float_rejected(write_block):
    with pytest.raises(ValidationError):
        load_block(write_block(_base().replace("schema_version: 2", "schema_version: 2.0")))


def test_measured_at_datetime_rejected(write_block):
    with pytest.raises(ValidationError):
        load_block(write_block(_base().replace(
            "measured_at: 2026-10-12", "measured_at: 2026-10-12T15:30:00"
        )))


def test_empty_capabilities_and_permissions_allowed(write_block):
    text = _base().replace(
        "capabilities:\n  - browser\n  - ai_fast\n  - interact_input\n  - interact_login",
        "capabilities: []",
    ).replace(
        "permissions:\n  - { type: domain, value: \"xiaohongshu.com\", required: true }\n"
        "  - { type: credential, value: \"xhs_login\", required: true }\n"
        "  - { type: ai, value: \"fast\", required: true }\n"
        "  - { type: interact, value: \"input\", required: true }\n"
        "  - { type: interact, value: \"login\", required: true }",
        "permissions: []",
    )
    spec = load_block(write_block(text))
    assert spec.capabilities == () and spec.permissions == ()
