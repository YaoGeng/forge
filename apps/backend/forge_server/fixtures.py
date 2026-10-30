"""ResponseFixtures 最小版（M07 §8.6 / docs/12 C14）：confirm 自动应答 + 副作用幂等两遍验证。

真实副作用站点联测缓办（阶段 1 seed 全部 side_effects=false）。
"""
import hashlib
import json
from dataclasses import dataclass

from forge_block_sdk import load_block


@dataclass(frozen=True)
class FixtureAnswer:
    value: object  # 声明命中时为 default_response 逐字；未声明为 None
    declared: bool


def apply_default_response(interactions, ask, *, default_response=None) -> FixtureAnswer | None:
    """confirm 类交互按声明自动应答。ask() 返回触发的 confirm id（无触发返回 None）。"""
    confirm_id = ask()
    if confirm_id is None:
        return None
    declared = any(
        getattr(i, "type", None) == "confirm" and i.id == confirm_id for i in interactions
    )
    return FixtureAnswer(value=default_response if declared else None, declared=declared)


def idempotency_key(params: dict) -> str:
    """canonical（键排序、无空白）→ sha256 前 16 hex（与 C7 report_hash 同规范）。"""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class IdemVerdict:
    ok: bool
    key: str | None
    passes: int
    detail: str = ""


def verify_idempotency(block_dir, params: dict, invoke) -> IdemVerdict:
    """side_effects=true 的积木：以同一幂等键执行两遍，键一致且输出一致才通过。"""
    spec = load_block(block_dir)
    if not spec.side_effects:
        return IdemVerdict(ok=True, key=None, passes=0, detail="not_side_effects")
    key1 = idempotency_key(params)
    result1 = invoke(key1)
    key2 = idempotency_key(params)
    result2 = invoke(key2)
    if key1 != key2:
        return IdemVerdict(ok=False, key=key2, passes=2, detail="idempotency key drifted between passes")
    if result1 != result2:
        return IdemVerdict(ok=False, key=key2, passes=2, detail="outputs diverged between passes")
    return IdemVerdict(ok=True, key=key2, passes=2)
