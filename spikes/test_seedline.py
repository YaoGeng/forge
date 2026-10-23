"""T1.61 产线单测（离线不触网；docs/13 §5 T1.60/T1.61）。

manifest 校验（T1.60）与产线三函数（T1.61）的行为契约在此钉死。
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedline import ManifestError, Site, load_manifest  # noqa: E402

_SCENARIOS = [f"s{i}_x" for i in range(1, 9)]  # 恰 8（D-4 收窄，A.9 R2）
_LIVE_MANIFEST = Path(__file__).resolve().parent / "seed_blocks" / "manifest.yaml"


def _manifest_yaml(
    *,
    scenarios: list[str] | None = None,
    sites: dict | None = None,
    blocks: list[dict] | None = None,
) -> str:
    scenarios = _SCENARIOS if scenarios is None else scenarios
    sites = sites if sites is not None else {
        "example.com": {"tier": "standard"},
    }
    blocks = blocks if blocks is not None else [
        {"name": "probe_a", "site": "example.com", "scenario": scenarios[0],
         "level": "C2", "script": "site_scripts.probe_a:browse",
         "params": {"q": "python"}, "batch": 1, "adapter": "trace"},
        {"name": "excel_export", "site": None, "scenario": scenarios[7],
         "level": "C2", "script": None, "params": {"rows": "[]"},
         "batch": 2, "adapter": "python"},
    ]
    lines = ["schema_version: 1", "scenarios:"]
    lines += [f"  - {{id: {sid}, title: 场景{sid}}}" for sid in scenarios]
    lines.append("sites:")
    for host, spec in sites.items():
        lines.append(f"  {host}: {{tier: {spec['tier']}}}")
    lines.append("blocks:")
    for b in blocks:
        parts = [f"name: {b['name']}"]
        for key in ("site", "scenario", "level", "script", "params", "batch", "adapter"):
            val = "null" if b[key] is None else repr(b[key])
            parts.append(f"{key}: {val}")
        lines.append("  - {" + ", ".join(parts) + "}")
    return "\n".join(lines) + "\n"


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "manifest.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_manifest_schema_rejects_bad(tmp_path):
    # 坏 1：场景数 != 8（D-4 收窄，A.9 R2；11 与旧值 10 都不合法）
    p = _write(tmp_path, _manifest_yaml(scenarios=[f"s{i}_x" for i in range(1, 12)]))
    with pytest.raises(ManifestError, match="scenarios"):
        load_manifest(p)

    # 坏 2：块重名
    dup = dict(_block_a())
    p = _write(tmp_path, _manifest_yaml(blocks=[_block_a(), dup]))
    with pytest.raises(ManifestError, match="重复"):
        load_manifest(p)

    # 坏 3：C1 块 site 为空（C1 必然触登录站点）
    c1_no_site = {"name": "login_x", "site": None, "scenario": _SCENARIOS[1],
                  "level": "C1", "script": "site_scripts.login_x:browse",
                  "params": {}, "batch": 1, "adapter": "trace"}
    p = _write(tmp_path, _manifest_yaml(blocks=[_block_a(), c1_no_site, _python_block()]))
    with pytest.raises(ManifestError, match="C1"):
        load_manifest(p)

    # 坏 4：tier 非法
    p = _write(tmp_path, _manifest_yaml(sites={"example.com": {"tier": "extreme"}}))
    with pytest.raises(ManifestError, match="tier"):
        load_manifest(p)

    # 坏 5：trace 块缺 script
    no_script = {"name": "probe_b", "site": "example.com", "scenario": _SCENARIOS[0],
                 "level": "C2", "script": None, "params": {}, "batch": 1, "adapter": "trace"}
    p = _write(tmp_path, _manifest_yaml(blocks=[no_script, _python_block()]))
    with pytest.raises(ManifestError, match="script"):
        load_manifest(p)

    # 坏 6：块名含目录不安全字符
    bad_name = _block_a()
    bad_name["name"] = "probe/a"
    p = _write(tmp_path, _manifest_yaml(blocks=[bad_name, _python_block()]))
    with pytest.raises(ManifestError, match="name"):
        load_manifest(p)


def _block_a() -> dict:
    return {"name": "probe_a", "site": "example.com", "scenario": _SCENARIOS[0],
            "level": "C2", "script": "site_scripts.probe_a:browse",
            "params": {"q": "python"}, "batch": 1, "adapter": "trace"}


def _python_block() -> dict:
    return {"name": "excel_export", "site": None, "scenario": _SCENARIOS[7],
            "level": "C2", "script": None, "params": {"rows": "[]"},
            "batch": 2, "adapter": "python"}


def test_manifest_accepts_good_sample(tmp_path):
    p = _write(tmp_path, _manifest_yaml())
    manifest = load_manifest(p)
    assert len(manifest.scenarios) == 8
    assert manifest.sites["example.com"].tier == "standard"
    by_name = {b.name: b for b in manifest.blocks}
    assert by_name["probe_a"].level == "C2"
    assert by_name["excel_export"].adapter == "python"
    assert by_name["excel_export"].site is None


def test_manifest_v2_scenario_set():
    """T1.70 Produces：现网 manifest v2 恰 8 场景，id 集合 pin（D-4 收窄，A.9 R2）。"""
    manifest = load_manifest(_LIVE_MANIFEST)
    assert [s.id for s in manifest.scenarios] == [
        "s1_search_digest", "s3_catalog_read", "s4_text_extract", "s5_public_api",
        "s6_repo_meta", "s7_home_watch", "s8_data_export", "s9_text_digest",
    ]
    # s2/s10 原块已移保留清单：blocks[] 不得再引用被裁场景
    assert all(b.scenario != "s2_login_inventory" for b in manifest.blocks)
    assert all(b.scenario != "s10_numeric_calc" for b in manifest.blocks)
    by_name = {b.name: b for b in manifest.blocks}
    assert "login_demo_probe" not in by_name and "price_calc" not in by_name
    assert "stats_summary" not in by_name and "unit_convert" not in by_name


# ── T1.61：产线三函数（脚手架/录制幂等/输出快照）──

def _entry(**over) -> "BlockEntry":
    from seedline import BlockEntry
    base = dict(name="probe_a", site="example.com", scenario="s1_x", level="C2",
                script="site_scripts.probe_a:browse", params={"q": "python"},
                batch=1, adapter="trace")
    base.update(over)
    return BlockEntry(**base)


def test_scaffold_passes_sdk_gates(tmp_path, monkeypatch):
    """脚手架产物必须直接过 SDK 两道门（validate_block_dir + lint）。"""
    import sys
    sdk = Path(__file__).resolve().parent.parent / "packages" / "block-sdk" / "python"
    if str(sdk) not in sys.path:
        sys.path.insert(0, str(sdk))
    from forge_block_sdk import lint, validate_block_dir

    from seedline import scaffold_block
    seeds = tmp_path / "seed_blocks"
    sites = {"example.com": Site(host="example.com", tier="medium")}
    d1 = scaffold_block(_entry(), seeds_dir=seeds, sites=sites)
    d2 = scaffold_block(_entry(name="excel_export", site=None, scenario="s8_x",
                               script=None, adapter="python"),
                        seeds_dir=seeds, sites=sites)
    for d in (d1, d2):
        spec = validate_block_dir(d)  # 失败抛错，成功返回 BlockSpec
        assert spec is not None and spec.name == d.name
        assert lint(d).ok, f"{d} lint 未过"
    yaml_text = (d1 / "block.yaml").read_text(encoding="utf-8")
    assert "example.com" in yaml_text and "medium" in yaml_text


def test_ensure_block_retry_then_state_reuse(tmp_path):
    """录制 3 次重试内成功可续；state 有 ref 时不重录（Review Focus 1）。"""
    from seedline import ensure_block

    calls = []

    def flaky(record_target, entry):
        calls.append(entry.name)
        if len(calls) < 3:
            raise ConnectionError("网络抖动")
        return "ref-abc"

    state: dict = {}
    ref = ensure_block(_entry(), store=None, state=state,
                       record_once=flaky, sleep=lambda s: None)
    assert ref == "ref-abc" and len(calls) == 3
    assert state["trace_refs"]["probe_a"] == "ref-abc"

    # 二次调用：state 复用，不触录制
    ref2 = ensure_block(_entry(), store=None, state=state,
                        record_once=lambda *a: (_ for _ in ()).throw(AssertionError("不应重录")))
    assert ref2 == "ref-abc" and len(calls) == 3


def test_snapshot_output_writes_golden(tmp_path):
    """python 块首跑输出落 tests/golden/expected_output.json（C5 对拍基准）。"""
    import json

    from seedline import snapshot_output

    d = tmp_path / "excel_export"
    d.mkdir()
    (d / "main.py").write_text(
        "def run(params):\n    return {'rows': len(params.get('rows', '').split(';')), 'ok': True}\n",
        encoding="utf-8")
    p = snapshot_output(d, {"rows": "a;b;c"})
    assert p == d / "tests" / "golden" / "expected_output.json"
    assert json.loads(p.read_text(encoding="utf-8")) == {"rows": 3, "ok": True}
