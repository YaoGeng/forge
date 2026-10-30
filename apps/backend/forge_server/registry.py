"""最小 Registry（docs/13 T1.64a；M10 §4/§5 子集 + M09 §3.3 chain 认证）。

路由约定：/apps* 逐字按 M10 §5；块注册走内部 /registry/blocks（M10 未定义创建路由，
阶段 2 M10-a 正式化）。chain 认证 = N=1 同步执行落库（C6），不经批次调度；
含 C1 积木的应用服务端拒绝同步整链，走本机整链（M09 §3.3 下行，C8）。
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.routing import APIRouter

from .models import (
    App,
    AppBlockRef,
    AppVersion,
    Block,
    BlockVersion,
    CertificationRun,
)

C1_LABEL = "创作者环境实测，平台抽查复核"
NON_STATISTICAL = "整链验证为单次执行，非统计值"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _reliability_snapshot(run: CertificationRun) -> dict:
    tier = ((run.plan_json or {}).get("tier")) or "standard"
    return {  # C13 钉死字段清单：详情页读侧仅 live 口径（M09 §5），不含 regression
        "level": run.level,
        "n": run.n,
        "live_pass_rate": run.live_pass_rate,
        "window_start": run.started_at.isoformat() if run.started_at else None,
        "window_end": run.finished_at.isoformat() if run.finished_at else None,
        "best_effort": tier == "high",
    }


def register_registry_routes(app) -> None:
    router = APIRouter()
    session_factory = app.state.session_factory

    def _get_or_404(model, pk, what):
        with session_factory() as s:
            row = s.get(model, pk)
            if row is None:
                raise HTTPException(status_code=404, detail=f"{what} 不存在")
            return row

    # --- 块注册（内部通道） -----------------------------------------------------

    @router.post("/registry/blocks")
    def register_block(body: dict):
        with session_factory() as s:
            run = s.get(CertificationRun, body.get("certification_run_id"))
            if run is None:
                raise HTTPException(status_code=404, detail="认证 run 不存在")
            if run.subject_type != "block" or run.level not in ("C1", "C2"):
                raise HTTPException(
                    status_code=422,
                    detail=f"仅块级 C1/C2 认证可注册（subject_type={run.subject_type} level={run.level}）")
            if run.subject_id != body.get("name"):
                raise HTTPException(
                    status_code=422,
                    detail=f"认证 run 归属不符（subject={run.subject_id}，注册名={body.get('name')}）")
            if run.verdict != "pass":
                raise HTTPException(
                    status_code=422,
                    detail=f"仅 verdict=pass 的认证可注册（当前 {run.verdict}）")
            name, version = body.get("name"), body.get("version", "1.0.0")
            block = s.query(Block).filter_by(name=name).one_or_none()
            if block is None:
                block = Block(name=name, created_at=_now())
                s.add(block)
                s.flush()
            elif s.query(BlockVersion).filter_by(block_id=block.id, version=version).one_or_none():
                return {"block_id": block.id, "version": version, "registered": False}
            s.add(BlockVersion(
                block_id=block.id, version=version,
                certification_level=run.level,
                reliability_json=_reliability_snapshot(run), created_at=_now(),
                side_effects=bool(body.get("side_effects", False)),
                domains_json=list(body.get("domains") or []),
            ))
            s.commit()
            return {"block_id": block.id, "version": version, "registered": True}

    # --- 应用（M10 §5 路由） -----------------------------------------------------

    @router.post("/apps")
    def create_app(body: dict):
        name = body.get("name")
        if not name:
            raise HTTPException(status_code=422, detail="应用名不能为空")
        with session_factory() as s:
            if s.query(App).filter_by(name=name).one_or_none() is not None:
                raise HTTPException(status_code=409, detail=f"应用名已存在：{name}")
            row = App(name=name, title=body.get("title", ""), created_at=_now())
            s.add(row)
            s.commit()
            return {"app_id": row.id}

    @router.get("/apps")
    def list_apps():
        with session_factory() as s:
            rows = s.query(App).all()
            out = []
            for a in rows:
                latest = (s.query(AppVersion).filter_by(app_id=a.id)
                          .order_by(AppVersion.id.desc()).first())
                out.append({"id": a.id, "name": a.name, "title": a.title,
                            "status": latest.status if latest else None,
                            "version": latest.version if latest else None})
            return out

    def _version_view(s, av: AppVersion, app_id: int) -> dict:
        blocks_view = []
        for step in (av.composition_json or []):
            name = step.get("block")
            if name is None:  # 交互步不渲染为块行（终审 #8）
                continue
            bv = (s.query(BlockVersion).join(Block, Block.id == BlockVersion.block_id)
                  .filter(Block.name == name)
                  .order_by(BlockVersion.id.desc()).first())
            if bv is None or bv.reliability_json is None:
                reliability = {"label": "数据不足"}
            else:
                reliability = dict(bv.reliability_json)
                if reliability.get("level") == "C1":
                    reliability["c1_label"] = C1_LABEL
            blocks_view.append({
                "name": name, "version": bv.version if bv else None,
                "reliability": reliability,
                "user_rolling_note": "认证初始 · 暂无用户数据",
            })
        chain_run = (s.query(CertificationRun)
                     .filter_by(subject_type="app_version", subject_id=str(app_id),
                                version=av.version)
                     .order_by(CertificationRun.id.desc()).first())
        chain = None
        if chain_run is not None:
            chain = {"verdict": chain_run.verdict, "n": chain_run.n,
                     "statistical": False, "annotation": NON_STATISTICAL}
        return {"version": av.version, "status": av.status,
                "blocks": blocks_view, "chain": chain}

    @router.get("/apps/{app_id}")
    def get_app(app_id: int):
        _get_or_404(App, app_id, "应用")
        with session_factory() as s:
            a = s.get(App, app_id)
            versions = (s.query(AppVersion).filter_by(app_id=app_id)
                        .order_by(AppVersion.id).all())
            return {"id": a.id, "name": a.name, "title": a.title,
                    "versions": [_version_view(s, av, app_id) for av in versions]}

    @router.get("/apps/{app_id}/versions")
    def list_app_versions(app_id: int):
        """应用版本列表（MS-3 T1 E1，web-admin 数据源）：只读，id desc。
        既有 GET /apps 只含 latest 摘要，版本全列表无出口（docs/18 已核实）。"""
        _get_or_404(App, app_id, "应用")
        with session_factory() as s:
            rows = (s.query(AppVersion).filter_by(app_id=app_id)
                    .order_by(AppVersion.id.desc()).all())
            return [{"id": av.id, "version": av.version, "status": av.status,
                     "created_at": av.created_at.isoformat()} for av in rows]

    @router.post("/apps/{app_id}/versions")
    def create_version(app_id: int, body: dict):
        _get_or_404(App, app_id, "应用")
        composition = body.get("composition_json") or []
        if not composition:
            raise HTTPException(status_code=422, detail="组合不能为空")
        with session_factory() as s:
            if (s.query(AppVersion).filter_by(app_id=app_id,
                                              version=body.get("version", "1.0.0"))
                    .one_or_none() is not None):
                raise HTTPException(status_code=422,
                                    detail="版本号已存在：换新 version（防旧 chain verdict 被新组合复用）")
            missing = []
            for step in composition:
                name = step.get("block")
                if name is None:  # 交互步（confirm）非可执行块，不参与注册检查
                    continue
                bv = (s.query(BlockVersion).join(Block, Block.id == BlockVersion.block_id)
                      .filter(Block.name == name)
                      .order_by(BlockVersion.id.desc()).first())
                if bv is None:
                    missing.append(name)
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"含未认证积木 {', '.join(missing)}：先完成 C1/C2 认证并注册后再入组合（转正路径：录制→认证→注册）")
            av = AppVersion(app_id=app_id, version=body.get("version", "1.0.0"),
                            composition_json=composition,
                            user_input_schema_json=body.get("user_input_schema_json") or {},
                            created_at=_now())
            s.add(av)
            s.flush()
            for step in composition:
                if step.get("block") is None:
                    continue
                bv = (s.query(BlockVersion).join(Block, Block.id == BlockVersion.block_id)
                      .filter(Block.name == step.get("block"))
                      .order_by(BlockVersion.id.desc()).first())
                s.add(AppBlockRef(app_id=app_id, block_name=step["block"],
                                  base_version=bv.version))
            s.commit()
            return {"version_id": av.id, "status": av.status}

    @router.post("/apps/{app_id}/versions/{version}/chain-cert")
    def chain_cert(app_id: int, version: str):
        _get_or_404(App, app_id, "应用")
        with session_factory() as s:
            av = (s.query(AppVersion).filter_by(app_id=app_id, version=version)
                  .order_by(AppVersion.id.desc()).first())
            if av is None:
                raise HTTPException(status_code=404, detail="应用版本不存在")
            composition = [st for st in (av.composition_json or []) if st.get("block")]
            levels = {}
            for step in composition:
                bv = (s.query(BlockVersion).join(Block, Block.id == BlockVersion.block_id)
                      .filter(Block.name == step.get("block"))
                      .order_by(BlockVersion.id.desc()).first())
                levels[step["block"]] = bv.certification_level if bv else None
            if any(lv == "C1" for lv in levels.values()):
                raise HTTPException(
                    status_code=422,
                    detail="含 C1 积木的应用须走创作者本机整链（M09 §3.3 下行），服务端不做同步整链")
            existing = (s.query(CertificationRun)
                        .filter_by(subject_type="app_version", subject_id=str(app_id),
                                   version=version, level="chain")
                        .order_by(CertificationRun.id.desc()).first())
            if existing is not None and existing.verdict is not None:
                return {"run_id": existing.id, "verdict": existing.verdict,
                        "n": existing.n, "statistical": False,
                        "annotation": NON_STATISTICAL, "steps": []}
        runner = getattr(app.state, "chain_runner", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="chain runner 未装配")
        result = runner(composition, {})
        ok = bool(result.get("ok"))
        with session_factory() as s:
            row = CertificationRun(
                subject_type="app_version", subject_id=str(app_id), version=version,
                level="chain", n=1, pass_count=1 if ok else 0,
                live_pass_rate=1.0 if ok else 0.0, regression_pass_rate=None,
                batch_id=f"chain-{uuid.uuid4().hex[:12]}",
                started_at=_now(), finished_at=_now(),
                verdict="pass" if ok else "rejected",
            )
            s.add(row)
            s.commit()
            run_id = row.id
        return {"run_id": run_id, "verdict": "pass" if ok else "rejected",
                "n": 1, "statistical": False, "annotation": NON_STATISTICAL,
                "steps": result.get("steps", [])}

    @router.post("/apps/{app_id}/submit")
    def submit_app(app_id: int):
        _get_or_404(App, app_id, "应用")
        with session_factory() as s:
            av = (s.query(AppVersion).filter_by(app_id=app_id)
                  .order_by(AppVersion.id.desc()).first())
            if av is None:
                raise HTTPException(status_code=422, detail="无版本可提审")
            chain = (s.query(CertificationRun)
                     .filter_by(subject_type="app_version", subject_id=str(app_id),
                                version=av.version, level="chain")
                     .order_by(CertificationRun.id.desc()).first())
            if chain is None or chain.verdict != "pass":
                raise HTTPException(
                    status_code=422,
                    detail="整链认证未通过：先完成 chain 认证（含未认证积木的应用不可提审）")
            av.status = "published"
            s.commit()
            return {"app_id": app_id, "version": av.version, "status": "published"}

    app.include_router(router, prefix="/api/v1")
