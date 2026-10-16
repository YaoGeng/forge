"""T1.61 产线单测（离线不触网；docs/13 §5 T1.60/T1.61）。

manifest 校验（T1.60）与产线三函数（T1.61）的行为契约在此钉死。
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedline import ManifestError, load_manifest  # noqa: E402

_SCENARIOS = [f"s{i}_x" for i in range(1, 11)]


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
    # 坏 1：场景数 != 10
    p = _write(tmp_path, _manifest_yaml(scenarios=_SCENARIOS[:9]))
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
    assert len(manifest.scenarios) == 10
    assert manifest.sites["example.com"].tier == "standard"
    by_name = {b.name: b for b in manifest.blocks}
    assert by_name["probe_a"].level == "C2"
    assert by_name["excel_export"].adapter == "python"
    assert by_name["excel_export"].site is None
