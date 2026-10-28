"""健康分级 v0（docs/17 T2.23；2026-10-26 实测修订）。

分档口径（D7 子集）：ok=近 7 天有复检（certification run）且 verdict=pass；
degraded=近 7 天有复检但未 pass；stale=超 7 天无复检。应用健康 = 组成积木最差档。

复检执行修订：生产服务端无浏览器执行器（deploy/Dockerfile 契约），服务端自排
复检无人执行——复检沿用阶段 1 离线批跑器（spikes/cert_batch.py）运维节奏，
本模块只做分档与商店标识。高变更块不进复检口径（D7）。
"""
from __future__ import annotations

from datetime import timedelta

RECHECK_WINDOW_DAYS = 7
_ORDER = {"ok": 0, "degraded": 1, "stale": 2}


def grade(s, block_name: str, *, now) -> str:
    """块健康档：按最近一次该块的认证 run（subject_type=block）。"""
    from .models import CertificationRun

    run = (
        s.query(CertificationRun)
        .filter_by(subject_type="block", subject_id=block_name)
        .order_by(CertificationRun.id.desc())
        .first()
    )
    if run is None or run.finished_at is None:
        return "stale"
    fresh = run.finished_at >= now - timedelta(days=RECHECK_WINDOW_DAYS)
    if not fresh:
        return "stale"
    return "ok" if run.verdict == "pass" else "degraded"


def app_health(s, app_row, *, now) -> str | None:
    """应用健康 = 组成积木最差档（无组成积木可判时 None——不渲染档位）。"""
    from .store import _composition_blocks

    blocks = _composition_blocks(s, _published_version(s, app_row))
    if not blocks:
        return None
    worst = max((grade(s, name, now=now) for name, _bv in blocks),
                key=lambda g: _ORDER[g])
    return worst


def _published_version(s, app_row):
    from .store import _latest_published_version

    return _latest_published_version(s, app_row)
