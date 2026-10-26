"""MS-2 商店读 API 与信任字段 v2（docs/17 T2.02）。

铁律（M03 §1 不变量 1/2）：任何通过率不带样本量不得出口；user_pass 样本 <30 → null
（渲染层显示"数据不足"）；页脚声明原文一字不差、不可配置。

口径（docs/17 T2.02，钉死）：
- cert_pass（应用级）= 组成积木认证汇总——rate=verdict pass 的积木数/总数，
  n=各积木 n 之和，window=最近 finished_at；
- user_pass = run_reports 滚动 30 天 ok 率，n<30 → null；
- level = 组成积木最高要求（含 C1 块 → C1）；
- login_sites = C1 积木 domains 并集；best_effort = 任一积木 tier=high。
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request

from .models import App, AppVersion, Block, BlockVersion, RunReport

FOOTER_TEXT = "运行条件与成功率以信任字段为准；平台审核与认证不构成对运行结果的担保"
USER_PASS_MIN_SAMPLES = 30
USER_PASS_WINDOW_DAYS = 30


def _latest_published_version(s, app: App) -> AppVersion | None:
    return (
        s.query(AppVersion)
        .filter_by(app_id=app.id, status="published")
        .order_by(AppVersion.id.desc())
        .first()
    )


def _composition_blocks(s, av: AppVersion) -> list[tuple[str, BlockVersion]]:
    """组成积木的 (block_name, 最新版本) 列表；未注册块跳过（读侧不炸，口径如实）。"""
    out = []
    for step in av.composition_json or []:
        name = step.get("block")
        if not name:
            continue
        block = s.query(Block).filter_by(name=name).first()
        if block is None:
            continue
        bv = (
            s.query(BlockVersion)
            .filter_by(block_id=block.id)
            .order_by(BlockVersion.id.desc())
            .first()
        )
        if bv is not None:
            out.append((name, bv))
    return out


def trust_fields(s, app: App, *, now) -> dict:
    """详情页信任字段 v2 全量（T2.03 获取流与 T2.20 Web 复用）。"""
    av = _latest_published_version(s, app)
    blocks = _composition_blocks(s, av)
    if blocks:
        passed = sum(
            1 for _n, bv in blocks
            if ((bv.reliability_json or {}).get("live_pass_rate") or 0) > 0
        )
        cert_pass = {
            "rate": round(passed / len(blocks), 4),
            "n": sum((bv.reliability_json or {}).get("n") or 0 for _n, bv in blocks),
            "window": max(
                (str((bv.reliability_json or {}).get("window_end") or "")
                 for _n, bv in blocks),
                default="",
            ),
        }
        level = "C1" if any(
            bv.certification_level == "C1" for _n, bv in blocks) else "C2"
        login_sites = sorted({
            d for _n, bv in blocks if bv.certification_level == "C1"
            for d in (bv.domains_json or [])
        })
        best_effort = any(
            (bv.reliability_json or {}).get("best_effort") for _n, bv in blocks)
    else:
        cert_pass, level, login_sites, best_effort = {"rate": 0.0, "n": 0, "window": ""}, "C0", [], False

    cutoff = now - timedelta(days=USER_PASS_WINDOW_DAYS)
    rows = (
        s.query(RunReport)
        .filter(RunReport.app_name == app.name, RunReport.created_at >= cutoff)
        .all()
    )
    user_pass = None
    if len(rows) >= USER_PASS_MIN_SAMPLES:
        user_pass = {"rate": round(sum(1 for r in rows if r.ok) / len(rows), 4),
                     "n": len(rows)}
    return {
        "name": app.name,
        "title": app.title,
        "level": level,
        "cert_pass": cert_pass,
        "user_pass": user_pass,
        "maintenance": "平台维护",       # S-1：免费平台自制 v0 固定文案
        "token_cost": "0（无模型调用）",  # 5 应用均为浏览器自动化
        "login_sites": login_sites,
        "interactions": "无（无人值守可跑）",  # S-4：现库 5 应用声明并集为空
        "best_effort": best_effort,
        "footer": FOOTER_TEXT,
    }


def register_store_routes(app) -> None:
    router = APIRouter(prefix="/api/v1/store", tags=["store"])

    def _get_published_app(s, name: str) -> App:
        app_row = s.query(App).filter_by(name=name).first()
        if app_row is None or _latest_published_version(s, app_row) is None:
            raise HTTPException(status_code=404, detail="应用不存在或未上架")
        return app_row

    @router.get("/apps")
    def list_apps(request: Request):
        now = request.app.state.clock.now()
        with request.app.state.session_factory() as s:
            apps = s.query(App).order_by(App.id).all()
            out = []
            for app_row in apps:
                av = _latest_published_version(s, app_row)
                if av is None:
                    continue
                d = trust_fields(s, app_row, now=now)
                out.append({  # 卡片精简字段（M03 §3.1）
                    "name": d["name"], "title": d["title"], "level": d["level"],
                    "cert_pass": d["cert_pass"], "user_pass": d["user_pass"],
                    "health": None,  # T2.23 健康分级回填
                })
            return out

    @router.get("/apps/{name}")
    def app_detail(name: str, request: Request):
        now = request.app.state.clock.now()
        with request.app.state.session_factory() as s:
            return trust_fields(s, _get_published_app(s, name), now=now)

    app.include_router(router)
