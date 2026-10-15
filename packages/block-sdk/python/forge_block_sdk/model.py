"""block.yaml v2 类型化模型（TDD §2.1 冻结字段的编码；字段集即公开契约）。"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionSpec:
    type: str
    value: str
    required: bool


@dataclass(frozen=True)
class RuntimeSpec:
    adapter: str
    entry: str
    timeout_sec: int


@dataclass(frozen=True)
class ReliabilitySpec:
    level: str
    pass_rate: float
    samples: int
    measured_at: str
    environment: str


@dataclass(frozen=True)
class InteractionSpec:
    id: str
    type: str
    title: str
    schema: dict | None
    optional: bool
    site: str | None


@dataclass(frozen=True)
class BlockSpec:
    schema_version: int
    kind: str
    name: str
    version: str
    title: str
    site_change_tier: str
    side_effects: bool
    capabilities: tuple[str, ...]
    permissions: tuple[PermissionSpec, ...]
    runtime: RuntimeSpec
    reliability: ReliabilitySpec | None
    ai_description: str
    default_response: str | dict | None


BLOCK_FIELDS = frozenset(f.name for f in dataclasses.fields(BlockSpec))

# M05 §4 / 架构 §6.4 Capability 家族面（lint R4 静态门与 runtime 运行时门共用单一来源）
FAMILIES = (
    "browser", "file", "office", "ai", "code", "data",
    "api", "credential", "confirm", "interact", "probe",
)


def has_capability(spec: BlockSpec, family: str) -> bool:
    """capability 家族或家族_变体匹配（ai_fast → ai）。"""
    return any(c == family or c.startswith(family + "_") for c in spec.capabilities)
