"""种子积木产线（docs/13 §5 T1.61；C1：manifest 为唯一输入）。

manifest.yaml 结构：
  schema_version: 1
  scenarios: [{id, title}]          # 恰 10 个（PRD「10 场景」）
  sites: {host: {tier}}             # tier ∈ standard|medium|high
  blocks: [{name, site?, scenario, level, script?, params, batch, adapter,
            exists?, legacy_state_key?}]
    level ∈ C1|C2；adapter ∈ trace|python；
    C1 ⇒ site 必填（登录类必触站点）；trace ⇒ script 必填；python ⇒ site 可空（本地）或 API 域
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_TIERS = ("standard", "medium", "high")
_LEVELS = ("C1", "C2")
_ADAPTERS = ("trace", "python")
_SCENARIO_COUNT = 10


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
        raise ManifestError(f"scenarios 必须恰 {_SCENARIO_COUNT} 个（PRD「10 场景」），现 {len(raw_scen)}")
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
