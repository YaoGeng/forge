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

from fastapi import APIRouter, HTTPException, Request, Response

from .auth import current_user
from .models import App, AppVersion, Block, BlockVersion, Entitlement, RunReport

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

    @router.get("/runner")
    def runner_info(request: Request):
        """运行器分发信息（T2.13）：版本/下载路径/sha256；未发布 → 404。"""
        import hashlib
        from pathlib import Path

        version = getattr(request.app.state, "runner_version", "") or ""
        dist = getattr(request.app.state, "dist_root", None)
        fname = f"forge-runner-{version}-win.exe"
        if not version or dist is None or not (Path(dist) / fname).exists():
            raise HTTPException(status_code=404, detail="运行器尚未发布")
        content = (Path(dist) / fname).read_bytes()
        return {"version": version, "url": f"/download/{fname}",
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest()}

    @router.post("/apps/{name}/acquire", status_code=201)
    def acquire(name: str, request: Request, response: Response):
        """免费获取（S-1/S-3）：幂等——重复获取返回既有权益并标记 replay。"""
        user = current_user(request)
        now = request.app.state.clock.now()
        with request.app.state.session_factory() as s:
            app_row = _get_published_app(s, name)
            existing = (
                s.query(Entitlement)
                .filter_by(user_id=user.id, app_name=app_row.name)
                .first()
            )
            if existing is not None:
                response.headers["X-Idempotent-Replay"] = "true"
                return {"entitlement_id": existing.id}
            av = _latest_published_version(s, app_row)
            ent = Entitlement(user_id=user.id, app_name=app_row.name,
                              version=av.version, acquired_at=now)
            s.add(ent)
            s.commit()
            return {"entitlement_id": ent.id}

    app.include_router(router)


FAILURE_CLASSES = frozenset({
    "component_timeout", "captcha_detected", "selector_missing",
    "anchor_mismatch", "env_error", None, "",
})


def _own_entitlement(s, user_id: int, entitlement_id: int) -> Entitlement:
    ent = s.get(Entitlement, entitlement_id)
    if ent is None or ent.user_id != user_id:
        raise HTTPException(status_code=404, detail="权益不存在")
    return ent


def register_report_routes(app) -> None:
    """运行上报 + 权益激活/清单 + 首跑统计（docs/17 T2.03）——/api/v1 顶层前缀。"""
    router = APIRouter(prefix="/api/v1", tags=["entitlements"])

    @router.post("/entitlements/{entitlement_id}/activate")
    def activate(entitlement_id: int, request: Request):
        """激活校验（退款判据锚点语义保留，S-1 下无退款仅作首用时间戳）。"""
        user = current_user(request)
        now = request.app.state.clock.now()
        with request.app.state.session_factory() as s:
            ent = _own_entitlement(s, user.id, entitlement_id)
            if ent.activated_at is None:
                ent.activated_at = now
                s.commit()
            return {"activated_at": ent.activated_at.isoformat()}

    @router.get("/me/entitlements")
    def my_entitlements(request: Request):
        user = current_user(request)
        with request.app.state.session_factory() as s:
            rows = (
                s.query(Entitlement)
                .filter_by(user_id=user.id)
                .order_by(Entitlement.id)
                .all()
            )
            return [{
                "entitlement_id": e.id, "app": e.app_name, "version": e.version,
                "source": e.source,
                "acquired_at": e.acquired_at.isoformat(),
                "activated_at": e.activated_at.isoformat() if e.activated_at else None,
            } for e in rows]

    @router.post("/run-reports", status_code=201)
    def create_report(body: dict, request: Request):
        user = current_user(request)
        now = request.app.state.clock.now()
        failure_class = body.get("failure_class")
        if failure_class not in FAILURE_CLASSES:
            raise HTTPException(status_code=422, detail="failure_class 不在 C4+env_error 枚举内")
        with request.app.state.session_factory() as s:
            ent = _own_entitlement(s, user.id, int(body.get("entitlement_id") or 0))
            first_run = (
                s.query(RunReport)
                .filter(RunReport.entitlement_id.in_(
                    e.id for e in s.query(Entitlement.id)
                    .filter_by(user_id=user.id, app_name=ent.app_name).all()))
                .count() == 0
            )
            s.add(RunReport(
                entitlement_id=ent.id, app_name=ent.app_name,
                ok=bool(body.get("ok")), failure_class=failure_class,
                env_class=str(body.get("env_class") or "unknown"),
                client_version=str(body.get("client_version") or ""),
                first_run=first_run, created_at=now,
            ))
            s.commit()
            return {"first_run": first_run}

    @router.get("/stats/first-run")
    def stats_first_run(request: Request):
        """D-5' 面板数据源（docs/17 T2.24 消费）：first_run 行即不同用户首跑。"""
        with request.app.state.session_factory() as s:
            rows = (
                s.query(RunReport)
                .filter_by(first_run=True)
                .order_by(RunReport.id)
                .all()
            )
            agg: dict[str, dict] = {}
            for r in rows:
                bucket = agg.setdefault(
                    r.app_name, {"app": r.app_name, "first_runs": 0, "ok_first_runs": 0})
                bucket["first_runs"] += 1
                bucket["ok_first_runs"] += 1 if r.ok else 0
            out = []
            for bucket in agg.values():
                bucket["rate"] = round(
                    bucket["ok_first_runs"] / bucket["first_runs"], 4)
                out.append(bucket)
            return out

    app.include_router(router)
