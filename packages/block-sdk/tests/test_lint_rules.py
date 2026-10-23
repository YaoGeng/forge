"""T1.11：lint 十规则用例——逐规则正反 + 输出确定性 + loader 一致 + adapter 门。"""
import ast
import shutil
from pathlib import Path

import pytest

from forge_block_sdk import RuntimeSpec, lint, load_block
from forge_block_sdk.lint import LintContext
from forge_block_sdk.rules import (
    rule_dependency_whitelist,
    rule_require_tests,
    rule_side_effect_idempotency_key,
    rule_timeout_declared,
)

CORPUS = Path(__file__).resolve().parent / "corpus" / "valid" / "demo_block"


def overlay(d: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def hits(result, rule_id):
    return [v for v in result.violations if v["rule_id"] == rule_id]


def make_ctx(main_src, spec=None, interactions=(), whitelist=frozenset(), block_dir=None):
    tree = ast.parse(main_src)
    if spec is None:
        spec = load_block(CORPUS / "block.yaml")
    return LintContext(
        spec=spec, interactions=interactions, block_dir=block_dir,
        entry_tree=tree, py_sources=(("main.py", tree),), whitelist=whitelist,
    )


# ---- 基线与编排 ----


def test_demo_block_passes_all_rules(demo_block_dir):
    result = lint(demo_block_dir)
    assert result.ok, result.violations
    assert result.violations == ()


def test_lint_uses_sdk_loader(write_block):
    d = write_block(
        (CORPUS / "block.yaml").read_text(encoding="utf-8").replace("schema_version: 2", "schema_version: 1")
    )
    result = lint(d)
    assert not result.ok
    assert [v["rule_id"] for v in result.violations] == ["manifest_invalid"]


def test_adapter_unsupported(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    d = write_block(
        base.replace("adapter: python", "adapter: node"),
        files={"main.js": "x = 1\n", "interactions.yaml": "[]\n"},
    )
    result = lint(d)
    assert not result.ok
    assert [v["rule_id"] for v in result.violations] == ["adapter_unsupported"]


def test_deterministic_output(demo_block_dir):
    overlay(demo_block_dir, {
        "main.py": "import requests\n\n\ndef run(p):\n    try:\n        requests.get('https://x.example.com')\n    except Exception:\n        pass\n",
    })
    r1, r2 = lint(demo_block_dir), lint(demo_block_dir)
    assert r1 == r2
    assert [ (v["file"], v["line"], v["rule_id"]) for v in r1.violations ] == sorted(
        (v["file"], v["line"], v["rule_id"]) for v in r1.violations
    )


# ---- R1 禁止裸调用 ----


def test_no_direct_network_rejected(demo_block_dir):
    cases = [
        "import requests\n\n\ndef run(p):\n    requests.get('https://x.example.com')\n",
        "from urllib.request import urlopen\n\n\ndef run(p):\n    urlopen('https://x.example.com')\n",
        "import httpx\n\n\ndef run(p):\n    httpx.get('https://x.example.com')\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "no_direct_network"), src


# ---- R2 白名单依赖 ----


def test_dependency_whitelist_rejected_and_mechanism(demo_block_dir, tmp_path):
    result = lint(overlay(demo_block_dir, {"requirements.txt": "flask==3.0.0\n"}))
    assert hits(result, "dependency_whitelist")
    ctx = make_ctx("x = 1\n", whitelist=frozenset({"flask"}), block_dir=tmp_path)
    (tmp_path / "requirements.txt").write_text("# comment\nflask[async]==3.0.0\n", encoding="utf-8")
    assert rule_dependency_whitelist(ctx) == []
    (tmp_path / "requirements.txt").write_text("django==5.0\n", encoding="utf-8")
    out = rule_dependency_whitelist(ctx)
    assert out and out[0]["file"] == "requirements.txt" and out[0]["line"] == 1


# ---- R3 必须生成测试 ----


def test_require_tests_gates(demo_block_dir, tmp_path):
    shutil.rmtree(demo_block_dir / "tests")
    assert hits(lint(demo_block_dir), "require_tests")
    result = lint(overlay(demo_block_dir, {"tests/test.yaml": "assertion: gossip\n"}))
    assert hits(result, "require_tests")
    ctx = make_ctx("x = 1\n", block_dir=tmp_path)
    assert rule_require_tests_gate(ctx)


def rule_require_tests_gate(ctx):
    from forge_block_sdk.rules import rule_require_tests
    return rule_require_tests(ctx)


def test_require_tests_positive(demo_block_dir):
    result = lint(overlay(demo_block_dir, {"tests/test.yaml": "assertion: golden_similarity\n"}))
    assert not hits(result, "require_tests")


# ---- R4 能力声明一致 ----


def test_capability_consistency_rejected(demo_block_dir):
    cases = [
        "def run(p):\n    runtime.file.read('/tmp/x')\n",
        "rt = runtime\n\n\ndef run(p):\n    rt.file.read('/tmp/x')\n",
        "def run(p):\n    runtime.credential.get('other_cred')\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "capability_consistency"), src


def test_capability_consistency_positive(demo_block_dir):
    src = "def run(p):\n    runtime.credential.get('xhs_login')\n    runtime.browser.open('https://www.xiaohongshu.com')\n"
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert not hits(result, "capability_consistency")


# ---- R5 交互声明一致 ----


def test_interaction_consistency_rejected(demo_block_dir):
    cases = [
        'def run(p):\n    runtime.interact.ask({"type": "captcha", "title": "验证码"})\n',
        'def run(p):\n    spec = {"type": "input"}\n    runtime.interact.ask(spec)\n',
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "interaction_consistency"), src


def test_interaction_consistency_positive(demo_block_dir):
    result = lint(overlay(demo_block_dir, {
        "main.py": 'def run(p):\n    runtime.interact.ask({"type": "confirm", "title": "确认"})\n',
        "interactions.yaml": "- { id: c1, type: confirm, title: 确认 }\n",
    }))
    assert not hits(result, "interaction_consistency")


# ---- R6 发布类必须 confirm ----






def test_side_effect_idempotency_key_pure():
    import dataclasses

    spec = dataclasses.replace(load_block(CORPUS / "block.yaml"), side_effects=True)
    ctx = make_ctx("def run(p):\n    return p\n", spec=spec)
    out = rule_side_effect_idempotency_key(ctx)
    assert out and out[0]["rule_id"] == "side_effect_idempotency_key"
    ctx_ok = make_ctx("def idempotency_key(params):\n    return 'k'\n", spec=spec)
    assert rule_side_effect_idempotency_key(ctx_ok) == []


def test_side_effect_idempotency_key_dir_positive(demo_block_dir):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    result = lint(overlay(demo_block_dir, {
        "block.yaml": base.replace(
            "side_effects: false",
            "side_effects: true\ndefault_response: { action: confirm_twice }",
        ),
        "main.py": "def idempotency_key(params):\n    return 'k'\n",
    }))
    assert not hits(result, "side_effect_idempotency_key")


# ---- R8 凭证外传 ----


def test_credential_exfiltration_rejected(demo_block_dir):
    cases = [
        "def run(p):\n    cred = runtime.credential.get('xhs_login')\n    runtime.api.call(cred)\n",
        "def run(p):\n    cred = runtime.credential.get('xhs_login')\n    url = f\"https://api.example.com?token={cred}\"\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "credential_exfiltration"), src


def test_credential_internal_use_positive(demo_block_dir):
    src = "def run(p):\n    cred = runtime.credential.get('xhs_login')\n    return len(cred)\n"
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert not hits(result, "credential_exfiltration")


# ---- R9 超时声明 ----


def test_timeout_declared_pure():
    import dataclasses

    spec = load_block(CORPUS / "block.yaml")
    for bad in (0, None):
        ctx = make_ctx("x = 1\n", spec=dataclasses.replace(spec, runtime=RuntimeSpec("python", "main.py", bad)))
        out = rule_timeout_declared(ctx)
        assert out and out[0]["rule_id"] == "timeout_declared"
    assert rule_timeout_declared(make_ctx("x = 1\n")) == []


# ---- R10 异常处理 ----


def test_bare_except_warning_blocks(demo_block_dir):
    result = lint(overlay(demo_block_dir, {
        "main.py": "def run(p):\n    try:\n        runtime.browser.open('https://www.xiaohongshu.com')\n    except:\n        pass\n",
    }))
    out = hits(result, "bare_except")
    assert out and out[0]["severity"] == "warning"
    assert not result.ok


def test_broad_except_without_reraise_warns(demo_block_dir):
    src = "def run(p):\n    try:\n        runtime.browser.open('https://www.xiaohongshu.com')\n    except Exception:\n        return None\n"
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert hits(result, "bare_except")


def test_reraise_positive(demo_block_dir):
    src = (
        "from forge_block_sdk import ComponentError\n\n\n"
        "def run(p):\n    try:\n        runtime.browser.open('https://www.xiaohongshu.com')\n"
        "    except ComponentError:\n        raise\n    except ValueError:\n        raise\n"
    )
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert not hits(result, "bare_except")


# ---- T1.11 评审修复轮（A4 首轮：C5 形态补全 / AnnAssign 别名 / lint() 契约路径） ----


def test_one_level_alias_tracked(demo_block_dir):
    cases = [
        "rt = runtime\n\n\ndef run(p):\n    rt.file.read('/tmp/x')\n",
        "fam = runtime.file\n\n\ndef run(p):\n    fam.read('/tmp/x')\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "capability_consistency"), src
    result = lint(overlay(demo_block_dir, {
        "main.py": "fam = runtime.browser\n\n\ndef run(p):\n    fam.open('https://www.xiaohongshu.com')\n",
    }))
    assert not hits(result, "capability_consistency")


def test_annassign_alias_tracked(demo_block_dir):
    result = lint(overlay(demo_block_dir, {
        "main.py": "h: object = runtime\n\n\ndef run(p):\n    h.file.read('/tmp/x')\n",
    }))
    assert hits(result, "capability_consistency")
    src = (
        "def run(p):\n"
        "    cred: str = runtime.credential.get('xhs_login')\n"
        "    url = f\"https://api.example.com?token={cred}\"\n"
    )
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert hits(result, "credential_exfiltration")


def test_c5_percent_and_format_exfiltration(demo_block_dir):
    cases = [
        "def run(p):\n    cred = runtime.credential.get('xhs_login')\n    url = 'https://api.example.com?token=%s' % cred\n",
        "def run(p):\n    cred = runtime.credential.get('xhs_login')\n    url = 'https://api.example.com?token={}'.format(cred)\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "credential_exfiltration"), src


def test_walrus_tuple_and_multiassign_handles(demo_block_dir):
    walrus = (
        "def run(p):\n"
        "    if (cred := runtime.credential.get('xhs_login')):\n"
        "        url = f\"https://api.example.com?token={cred}\"\n"
    )
    assert hits(lint(overlay(demo_block_dir, {"main.py": walrus})), "credential_exfiltration")
    tup = (
        "def run(p):\n"
        "    cred, _ = runtime.credential.get('xhs_login'), None\n"
        "    runtime.api.call(cred)\n"
    )
    assert hits(lint(overlay(demo_block_dir, {"main.py": tup})), "credential_exfiltration")
    multi = (
        "def run(p):\n"
        "    a = b = runtime.credential.get('xhs_login')\n"
        "    runtime.api.call(b)\n"
    )
    assert hits(lint(overlay(demo_block_dir, {"main.py": multi})), "credential_exfiltration")


def test_socket_and_http_client_banned(demo_block_dir):
    cases = [
        "import socket\n\n\ndef run(p):\n    socket.create_connection(('x.example.com', 80))\n",
        "import http.client\n\n\ndef run(p):\n    http.client.HTTPConnection('x.example.com')\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "no_direct_network"), src


def test_lint_non_utf8_source_is_manifest_invalid(demo_block_dir):
    (demo_block_dir / "main.py").write_bytes("x = '中文'\n".encode("gbk"))
    result = lint(demo_block_dir)
    assert not result.ok
    assert [v["rule_id"] for v in result.violations] == ["manifest_invalid"]


def test_lint_entry_missing_or_mismatch_is_manifest_invalid(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    d = write_block(base.replace("entry: main.py", "entry: gone.py"), files={"interactions.yaml": "[]\n"})
    result = lint(d)
    assert not result.ok and result.violations[0]["rule_id"] == "manifest_invalid"
    d2 = write_block(base.replace("entry: main.py", "entry: main.txt"), files={"main.txt": "x\n", "interactions.yaml": "[]\n"})
    result2 = lint(d2)
    assert not result2.ok and result2.violations[0]["rule_id"] == "manifest_invalid"


def test_r5_kwargs_literal_type(demo_block_dir):
    result = lint(overlay(demo_block_dir, {
        "main.py": 'def run(p):\n    runtime.interact.ask(type="confirm", title="确认")\n',
        "interactions.yaml": "- { id: c1, type: confirm, title: 确认 }\n",
    }))
    assert not hits(result, "interaction_consistency")


def test_r10_tuple_and_baseexception_broad(demo_block_dir):
    cases = [
        "def run(p):\n    try:\n        runtime.browser.open('https://www.xiaohongshu.com')\n    except (Exception, ValueError):\n        return None\n",
        "def run(p):\n    try:\n        runtime.browser.open('https://www.xiaohongshu.com')\n    except BaseException:\n        return None\n",
    ]
    for src in cases:
        result = lint(overlay(demo_block_dir, {"main.py": src}))
        assert hits(result, "bare_except"), src


# ---- 终审修复轮（I-1 非 UTF-8 声明路径 / M-1 R6 仅副作用生效 / M-7 卫生） ----


def test_lint_non_utf8_block_and_interactions_short_circuit(write_block):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    d = write_block(base)
    (d / "interactions.yaml").write_bytes("- { id: a, type: input, title: 主题 }\n".encode("gbk"))
    result = lint(d)
    assert not result.ok
    assert [v["rule_id"] for v in result.violations] == ["manifest_invalid"]
    (d / "block.yaml").write_bytes(base.encode("gbk"))
    (d / "interactions.yaml").unlink()
    result2 = lint(d)
    assert not result2.ok
    assert [v["rule_id"] for v in result2.violations] == ["manifest_invalid"]


def test_lint_non_utf8_requirements_and_testyaml_violate(demo_block_dir):
    (demo_block_dir / "requirements.txt").write_bytes("# 依赖说明：无\nflask==3.0.0\n".encode("gbk"))
    result = lint(demo_block_dir)
    assert hits(result, "dependency_whitelist")
    (demo_block_dir / "tests" / "test.yaml").write_bytes("# 断言：结构校验\nassertion: schema\n".encode("gbk"))
    result2 = lint(demo_block_dir)
    assert hits(result2, "require_tests")


def test_publish_requires_confirm(demo_block_dir):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    result = lint(overlay(demo_block_dir, {
        "block.yaml": base.replace(
            "side_effects: false",
            "side_effects: true\ndefault_response: { action: confirm_twice }",
        ),
        "main.py": 'ACTION = "publish"\n',
    }))
    assert hits(result, "publish_requires_confirm")


def test_publish_with_confirm_positive(demo_block_dir):
    base = (CORPUS / "block.yaml").read_text(encoding="utf-8")
    result = lint(overlay(demo_block_dir, {
        "block.yaml": base.replace(
            "side_effects: false",
            "side_effects: true\ndefault_response: { action: confirm_twice }",
        ),
        "main.py": 'ACTION = "submit order"\n',
        "interactions.yaml": "- { id: c1, type: confirm, title: 确认提交 }\n",
    }))
    assert not hits(result, "publish_requires_confirm")


def test_publish_readonly_not_gated(demo_block_dir):
    src = 'DOC = """Sort records in order by title."""\n'
    result = lint(overlay(demo_block_dir, {"main.py": src}))
    assert not hits(result, "publish_requires_confirm")


def test_no_direct_network_registered_waiver():
    """A.9 R2③ 登记豁免（docs/05 备案）：url_read/table_read 冻结规格为 python/httpx
    直连（best_effort 强制）；豁免只在登记清单内，清单外照常拦截。"""
    import dataclasses

    from forge_block_sdk.rules import rule_no_direct_network

    src = "import httpx\n\n\ndef run(p):\n    httpx.get('https://x.example.com')\n"
    base = load_block(CORPUS / "block.yaml")
    for name in ("url_read", "table_read"):
        spec = dataclasses.replace(base, name=name)
        assert rule_no_direct_network(make_ctx(src, spec=spec)) == [], name
    other = dataclasses.replace(base, name="some_other_block")
    out = rule_no_direct_network(make_ctx(src, spec=other))
    assert out and all(v["rule_id"] == "no_direct_network" for v in out)
