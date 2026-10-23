"""种子积木产线（docs/13 §5 T1.61；C1：manifest 为唯一输入）。

manifest.yaml 结构：
  schema_version: 1
  scenarios: [{id, title}]          # 恰 8 个（D-4 收窄，A.9 R2：砍 s2_login_inventory/s10_numeric_calc）
  sites: {host: {tier}}             # tier ∈ standard|medium|high
  blocks: [{name, site?, scenario, level, script?, params, batch, adapter,
            exists?, legacy_state_key?}]
    level ∈ C1|C2；adapter ∈ trace|python；
    C1 ⇒ site 必填（登录类必触站点）；trace ⇒ script 必填；python ⇒ site 可空（本地）或 API 域
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_TIERS = ("standard", "medium", "high")
_LEVELS = ("C1", "C2")
_ADAPTERS = ("trace", "python")
_SCENARIO_COUNT = 8  # D-4 收窄（A.9 R2，2026-10-19）：场景集 10→8，砍 s2/s10


class ManifestError(Exception):
    """manifest 结构或语义违规（含字段定位）。"""


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str


@dataclass(frozen=True)
class Site:
    host: str
    tier: str


@dataclass(frozen=True)
class BlockEntry:
    name: str
    site: str | None
    scenario: str
    level: str
    script: str | None
    params: dict
    batch: int
    adapter: str
    exists: bool = False               # MS-1E 已产出的块：produce/submit 跳过
    legacy_state_key: str | None = None  # ms1e 遗留 state 键（run_ids 聚合用）


@dataclass(frozen=True)
class Manifest:
    scenarios: tuple[Scenario, ...]
    sites: dict[str, Site]
    blocks: tuple[BlockEntry, ...]
    path: Path = field(default_factory=Path)


def load_manifest(path: Path | str) -> Manifest:
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"YAML 解析失败：{path}") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise ManifestError("schema_version 必须为 1")

    raw_scen = doc.get("scenarios") or []
    if len(raw_scen) != _SCENARIO_COUNT:
        raise ManifestError(f"scenarios 必须恰 {_SCENARIO_COUNT} 个（D-4 收窄，A.9 R2），现 {len(raw_scen)}")
    scenarios = []
    seen_ids: set[str] = set()
    for s in raw_scen:
        sid = s.get("id")
        if not sid or sid in seen_ids:
            raise ManifestError(f"scenarios.id 重复或为空：{sid!r}")
        seen_ids.add(sid)
        scenarios.append(Scenario(id=sid, title=s.get("title", "")))

    raw_sites = doc.get("sites") or {}
    sites: dict[str, Site] = {}
    for host, spec in raw_sites.items():
        tier = spec.get("tier")
        if tier not in _TIERS:
            raise ManifestError(f"sites.{host}.tier 非法：{tier!r}（∈ {_TIERS}）")
        sites[host] = Site(host=host, tier=tier)

    raw_blocks = doc.get("blocks") or []
    blocks: list[BlockEntry] = []
    seen_names: set[str] = set()
    for b in raw_blocks:
        name = b.get("name")
        if not name or not _NAME_RE.match(name):
            raise ManifestError(f"blocks.name 非法（须 ^[a-z0-9_]+$）：{name!r}")
        if name in seen_names:
            raise ManifestError(f"blocks.name 重复：{name}")
        seen_names.add(name)
        scenario = b.get("scenario")
        if scenario not in seen_ids:
            raise ManifestError(f"blocks.{name}.scenario 未在 scenarios 声明：{scenario!r}")
        level = b.get("level")
        if level not in _LEVELS:
            raise ManifestError(f"blocks.{name}.level 非法：{level!r}")
        adapter = b.get("adapter")
        if adapter not in _ADAPTERS:
            raise ManifestError(f"blocks.{name}.adapter 非法：{adapter!r}")
        site = b.get("site")
        if site is not None and site not in sites:
            raise ManifestError(f"blocks.{name}.site 未在 sites 声明：{site!r}")
        if level == "C1" and site is None:
            raise ManifestError(f"blocks.{name} 为 C1（登录类）但 site 为空")
        script = b.get("script")
        if adapter == "trace" and not script:
            raise ManifestError(f"blocks.{name} 为 trace 适配但缺 script")
        batch = b.get("batch")
        if batch not in (1, 2):
            raise ManifestError(f"blocks.{name}.batch 须为 1|2：{batch!r}")
        blocks.append(BlockEntry(
            name=name, site=site, scenario=scenario, level=level, script=script,
            params=b.get("params") or {}, batch=batch, adapter=adapter,
            exists=bool(b.get("exists")), legacy_state_key=b.get("legacy_state_key"),
        ))

    return Manifest(scenarios=tuple(scenarios), sites=sites, blocks=tuple(blocks), path=path)


# ── T1.61：产线三函数 ──

_BLOCK_YAML_TMPL = """schema_version: 2
kind: block
name: {name}
version: 1.0.0
title: {title}
site_change_tier: {tier}
side_effects: false
capabilities: []
{permissions}
runtime:
  adapter: python
  entry: main.py
  timeout_sec: 120
ai_description: {desc}
"""

_PROBE_MAIN = '''"""{name} 入口：回放驱动的只读探针（无 runtime 能力调用）。"""


def run(params: dict) -> dict:
    return {{"ok": True}}
'''

_STUB_MAIN = '''"""{name} 占位入口：python 块逻辑随批次手写（替换本文件后先 snapshot 再认证）。"""


def run(params: dict) -> dict:
    raise NotImplementedError("python 块逻辑未落（T1.63 手写替换）")
'''

_TEST_YAML = """assertion: schema
expect:
  type: object
  required:
    - ok
  properties:
    ok: { type: boolean }
"""


def scaffold_block(entry: BlockEntry, *, seeds_dir: Path, sites: dict[str, Site]) -> Path:
    """按 manifest 条目落积木目录五件套；产物必须直接过 validate+lint 两道门。

    python 适配块不写 main.py（真实逻辑随批次手写，脚手架不得覆盖）。
    """
    d = Path(seeds_dir) / entry.name
    d.mkdir(parents=True, exist_ok=True)
    tier = sites[entry.site].tier if entry.site else "standard"  # 本地计算块按最稳档
    if entry.site:
        permissions = ('permissions:\n  - { type: domain, value: "'
                       + entry.site + '", required: true }')
    else:
        permissions = 'permissions: []'
    (d / "block.yaml").write_text(_BLOCK_YAML_TMPL.format(
        name=entry.name, title=entry.name, tier=tier, permissions=permissions,
        desc=f"seed 块 {entry.name}（场景 {entry.scenario}）",
    ), encoding="utf-8")
    (d / "interactions.yaml").write_text("[]\n", encoding="utf-8")
    (d / "requirements.txt").write_text("", encoding="utf-8")
    (d / "tests").mkdir(exist_ok=True)
    (d / "tests" / "test.yaml").write_text(_TEST_YAML, encoding="utf-8")
    if entry.adapter == "trace":
        (d / "main.py").write_text(_PROBE_MAIN.format(name=entry.name), encoding="utf-8")
    elif not (d / "main.py").exists():
        (d / "main.py").write_text(_STUB_MAIN.format(name=entry.name), encoding="utf-8")
    return d


def ensure_block(entry: BlockEntry, store, state: dict, record_once, *,
                 retries: int = 3, sleep=time.sleep) -> str:
    """录制幂等：state 已有 ref 直接复用；record_once 异常按 retries 次重试。"""
    ref = state.get("trace_refs", {}).get(entry.name)
    if ref:
        return ref
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            ref = record_once(store, entry)
            break
        except Exception as exc:
            last_exc = exc
            print(f"  [produce] {entry.name} 第{attempt + 1}次失败：{type(exc).__name__}，重试",
                  flush=True)
            sleep(5 * (attempt + 1))
    if ref is None:
        raise RuntimeError(f"录制失败（{retries} 次）：{entry.name}") from last_exc
    state.setdefault("trace_refs", {})[entry.name] = ref
    return ref


def snapshot_output(block_dir: Path, params: dict) -> Path:
    """python 块首跑输出快照 → tests/golden/expected_output.json（C5 对拍基准）。"""
    import importlib.util

    d = Path(block_dir)
    spec = importlib.util.spec_from_file_location(f"snap_{d.name}", d / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    output = mod.run(dict(params or {}))
    golden_dir = d / "tests" / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    out = golden_dir / "expected_output.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    return out
