"""Creator Center 最小版（docs/13 T1.64b；M02 §3 九步、D-M1F.1 web 载体）。

服务端 FlowOrchestrator：会话状态 + 自动保存（M02 不变量 4）；副作用规则与 C0 拦截
在 API 层强制（不变量 1/2）；报告口径 G12（N/时间窗/C1 标注/非统计值/数据不足）。
步骤序：n±1，另允许 2→4（「缺积木」为可选步，阶段 1 无 RecordStudio）。
"""
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
    CreationSession,
)

STEPS = ("说需求/搜积木", "画布组装", "缺积木", "启动表单", "本地干跑",
         "提交认证", "认证报告", "发布配置", "提审上架")
C1_LABEL = "创作者环境实测，平台抽查复核"
NON_STATISTICAL = "整链验证为单次执行，非统计值"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _save(session, row: CreationSession) -> None:
    row.autosave_at = _now()
    session.add(row)
    session.commit()


def _get_session(session_factory, sid: int) -> CreationSession:
    with session_factory() as s:
        row = s.get(CreationSession, sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return row


def register_creator_routes(app) -> None:
    router = APIRouter()
    sf = app.state.session_factory

    def _registry_view(s, composition):
        """画布块的注册信息（name → BlockVersion 最新）；缺注册 = C0。"""
        view = {}
        for step in composition:
            name = step.get("block")
            if name is None or name in view:
                continue
            bv = (s.query(BlockVersion).join(Block, Block.id == BlockVersion.block_id)
                  .filter(Block.name == name)
                  .order_by(BlockVersion.id.desc()).first())
            view[name] = bv
        return view

    def _validate_canvas(s, composition):
        if not composition:
            raise HTTPException(status_code=422, detail="组合不能为空")
        reg = _registry_view(s, composition)
        missing = [st.get("block") for st in composition
                   if st.get("block") and reg.get(st.get("block")) is None]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"含未认证积木 {', '.join(missing)}：先完成 C1/C2 认证并注册（转正路径：录制→认证→注册）")
        # 副作用规则（M02 不变量 1 措辞：后置 confirm）：每个 side_effects 块之后
        # 存在纯交互 confirm 步即可保存；副作用块自带 confirm 标记不得自确认（终审 #4）
        confirm_at = [i for i, st in enumerate(composition)
                      if st.get("interaction") == "confirm" and st.get("block") is None]
        for i, st in enumerate(composition):
            if st.get("block") is None:
                continue
            bv = reg.get(st["block"])
            if bv is not None and bv.side_effects and not any(c > i for c in confirm_at):
                raise HTTPException(
                    status_code=422,
                    detail="副作用积木（发布/提交/支付类）后必须有 confirm 交互步才可保存")
        return reg

    # --- 块目录（第 1 步：搜积木） ------------------------------------------------

    @router.get("/creator/blocks")
    def blocks_catalog():
        with sf() as s:
            out = []
            for b in s.query(Block).order_by(Block.name).all():
                bv = (s.query(BlockVersion).filter_by(block_id=b.id)
                      .order_by(BlockVersion.id.desc()).first())
                if bv is None:
                    continue
                if bv.reliability_json is None:
                    reliability = {"label": "数据不足"}
                else:
                    reliability = dict(bv.reliability_json)
                    if reliability.get("level") == "C1":
                        reliability["c1_label"] = C1_LABEL
                out.append({"name": b.name, "version": bv.version,
                            "level": bv.certification_level,
                            "side_effects": bv.side_effects,
                            "reliability": reliability,
                            "user_rolling_note": "认证初始 · 暂无用户数据"})
            return out

    # --- 会话 -------------------------------------------------------------------

    @router.post("/creator/sessions")
    def open_session(body: dict):
        with sf() as s:
            row = CreationSession(requirement_text=body.get("requirement_text", ""),
                                  step=1, draft_json={})
            _save(s, row)
            return {"session_id": row.id, "step": 1, "steps": list(STEPS)}

    @router.get("/creator/sessions/{sid}")
    def get_session(sid: int):
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            return {"session_id": row.id, "step": row.step, "steps": list(STEPS),
                    "requirement_text": row.requirement_text,
                    "draft": row.draft_json or {},
                    "autosave_at": row.autosave_at.isoformat() if row.autosave_at else None}

    @router.post("/creator/sessions/{sid}/goto")
    def goto_step(sid: int, body: dict):
        target = body.get("step")
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            cur = row.step
            allowed = ({cur - 1, cur, cur + 1} | ({4} if cur == 2 else set())) & set(range(1, len(STEPS) + 1))
            if target not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"步骤只许相邻推进或回退（当前 {cur}，请求 {target}；2→4 为跳过可选的「缺积木」）")
            if target > 4 and not (row.draft_json or {}).get("composition"):
                raise HTTPException(status_code=422, detail="先在画布步落组合产物")
            row.step = target
            _save(s, row)
            return {"session_id": sid, "step": target}

    # --- 步产物 -----------------------------------------------------------------

    @router.put("/creator/sessions/{sid}/canvas")
    def put_canvas(sid: int, body: dict):
        composition = body.get("composition") or []
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            _validate_canvas(s, composition)
            draft = dict(row.draft_json or {})  # 拷贝再改：同对象赋值不置脏（SQLAlchemy JSON 列）
            draft["composition"] = composition
            row.draft_json = draft
            _save(s, row)
            return {"session_id": sid, "saved": True}

    @router.put("/creator/sessions/{sid}/form")
    def put_form(sid: int, body: dict):
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            draft = dict(row.draft_json or {})  # 拷贝再改：同对象赋值不置脏（SQLAlchemy JSON 列）
            draft["user_input_schema"] = body.get("user_input_schema") or {}
            row.draft_json = draft
            _save(s, row)
            return {"session_id": sid, "saved": True}

    @router.post("/creator/sessions/{sid}/dryrun")
    def dryrun(sid: int):
        with sf() as s:
            row = s.get(CreationSession, sid)
            composition = (row.draft_json or {}).get("composition") if row else None
        if not composition:
            raise HTTPException(status_code=422, detail="无画布产物可干跑")
        runner = getattr(app.state, "chain_runner", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="chain runner 未装配")
        blocks_only = [st for st in composition if st.get("block")]
        result = runner(blocks_only, {})
        return result

    @router.post("/creator/sessions/{sid}/certify")
    def certify(sid: int):
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            draft = dict(row.draft_json or {})  # 拷贝再改：同对象赋值不置脏（SQLAlchemy JSON 列）
            composition = draft.get("composition")
            if not composition:
                raise HTTPException(status_code=422, detail="无画布产物可认证")
            reg = _validate_canvas(s, composition)  # C0 兜底：会话外直改库的漏网
            levels = {st["block"]: (reg[st["block"]].certification_level
                                    if reg.get(st["block"]) else None)
                      for st in composition if st.get("block")}
            if any(lv == "C1" for lv in levels.values()):
                raise HTTPException(
                    status_code=422,
                    detail="含 C1 积木的应用须走创作者本机整链（M09 §3.3 下行）")
            if draft.get("app_id") is not None:  # 重认证：复用 App，版本递增（终审 #5）
                app_row = s.get(App, draft["app_id"])
                n_versions = s.query(AppVersion).filter_by(app_id=app_row.id).count()
                version = f"1.0.{n_versions}" if n_versions else "1.0.0"
            else:
                app_row = App(name=draft.get("app_name") or f"app-session-{sid}",
                              title=draft.get("title") or f"会话 {sid} 应用",
                              created_at=_now())
                s.add(app_row)
                s.flush()
                version = "1.0.0"
            av = AppVersion(app_id=app_row.id, version=version,
                            composition_json=composition,
                            user_input_schema_json=draft.get("user_input_schema") or {},
                            created_at=_now())
            s.add(av)
            s.flush()
            for st in composition:
                if st.get("block"):
                    s.add(AppBlockRef(app_id=app_row.id, block_name=st["block"],
                                      base_version=reg[st["block"]].version))
            draft["app_id"] = app_row.id
            draft["app_name"] = app_row.name
            draft["version"] = version
            row.draft_json = draft
            _save(s, row)  # autosave_at 变更置脏整行——JSON 列同对象赋值不触发 UPDATE
            app_id = app_row.id
        return _run_chain_cert(app_id, version)

    def _run_chain_cert(app_id: int, version: str):
        runner = getattr(app.state, "chain_runner", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="chain runner 未装配")
        with sf() as s:
            av = (s.query(AppVersion).filter_by(app_id=app_id, version=version)
                  .order_by(AppVersion.id.desc()).first())
            existing = (s.query(CertificationRun)
                        .filter_by(subject_type="app_version", subject_id=str(app_id),
                                   version=version, level="chain")
                        .order_by(CertificationRun.id.desc()).first())
            if existing is not None and existing.verdict is not None:
                return {"run_id": existing.id, "verdict": existing.verdict,
                        "n": existing.n, "statistical": False,
                        "annotation": NON_STATISTICAL, "steps": []}
            composition = av.composition_json or []
        result = runner([st for st in composition if st.get("block")], {})
        ok = bool(result.get("ok"))
        with sf() as s:
            row = CertificationRun(
                subject_type="app_version", subject_id=str(app_id), version=version,
                level="chain", n=1, pass_count=1 if ok else 0,
                live_pass_rate=1.0 if ok else 0.0, regression_pass_rate=None,
                batch_id=f"chain-{app_id}-{version}", started_at=_now(),
                finished_at=_now(), verdict="pass" if ok else "rejected")
            s.add(row)
            s.commit()
            run_id = row.id
        return {"run_id": run_id, "verdict": "pass" if ok else "rejected",
                "n": 1, "statistical": False, "annotation": NON_STATISTICAL,
                "steps": result.get("steps", [])}

    @router.get("/creator/sessions/{sid}/report")
    def report(sid: int):
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            draft = dict(row.draft_json or {})  # 拷贝再改：同对象赋值不置脏（SQLAlchemy JSON 列）
            composition = draft.get("composition") or []
            app_id = draft.get("app_id")
            blocks = []
            for st in composition:
                if not st.get("block"):
                    continue
                bv = (s.query(BlockVersion)
                      .join(Block, Block.id == BlockVersion.block_id)
                      .filter(Block.name == st["block"])
                      .order_by(BlockVersion.id.desc()).first())
                if bv is None or bv.reliability_json is None:
                    reliability = {"label": "数据不足"}
                else:
                    reliability = dict(bv.reliability_json)
                    if reliability.get("level") == "C1":
                        reliability["c1_label"] = C1_LABEL
                blocks.append({"name": st["block"], "reliability": reliability,
                               "user_rolling_note": "认证初始 · 暂无用户数据"})
            chain = None
            if app_id is not None:
                cr = (s.query(CertificationRun)
                      .filter_by(subject_type="app_version", subject_id=str(app_id),
                                 version=draft.get("version", "1.0.0"), level="chain")
                      .order_by(CertificationRun.id.desc()).first())
                if cr is not None:
                    chain = {"verdict": cr.verdict, "n": cr.n,
                             "statistical": False, "annotation": NON_STATISTICAL}
            return {"session_id": sid, "blocks": blocks, "chain": chain}

    @router.put("/creator/sessions/{sid}/publish")
    def put_publish(sid: int, body: dict):
        if not body.get("sites_compliance_confirmed"):
            raise HTTPException(status_code=422, detail="站点合规声明须确认后才可保存发布配置")
        with sf() as s:
            row = s.get(CreationSession, sid)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            draft = dict(row.draft_json or {})  # 拷贝再改：同对象赋值不置脏（SQLAlchemy JSON 列）
            draft["title"] = body.get("title") or draft.get("title")
            with_domain_meta = []
            for st in draft.get("composition") or []:
                if not st.get("block"):
                    continue
                bv = (s.query(BlockVersion)
                      .join(Block, Block.id == BlockVersion.block_id)
                      .filter(Block.name == st["block"])
                      .order_by(BlockVersion.id.desc()).first())
                with_domain_meta += list((bv.domains_json or []) if bv else [])
            draft["sites"] = sorted(set(with_domain_meta))
            draft["compliance"] = {"confirmed": True,
                                   "declaration": "本应用仅访问已声明站点的公开数据，遵守各站点服务条款"}
            row.draft_json = draft
            if draft.get("app_id"):
                a = s.get(App, draft["app_id"])
                if a is not None and draft.get("title"):
                    a.title = draft["title"]
            _save(s, row)
            return {"session_id": sid, "sites": draft["sites"]}

    @router.post("/creator/sessions/{sid}/submit")
    def submit(sid: int):
        with sf() as s:
            row = s.get(CreationSession, sid)
            draft = dict(row.draft_json or {})  # 拷贝再改：同对象赋值不置脏（SQLAlchemy JSON 列） if row else {}
            app_id = draft.get("app_id")
            if app_id is None:
                raise HTTPException(status_code=422, detail="先完成认证步（无应用可提审）")
            cr = (s.query(CertificationRun)
                  .filter_by(subject_type="app_version", subject_id=str(app_id),
                             level="chain")
                  .order_by(CertificationRun.id.desc()).first())
            if cr is None or cr.verdict != "pass" or cr.version != draft.get("version", "1.0.0"):
                raise HTTPException(status_code=422, detail="整链认证未通过，不可提审")
            av = (s.query(AppVersion).filter_by(app_id=app_id)
                  .order_by(AppVersion.id.desc()).first())
            av.status = "published"
            s.commit()
            return {"app_id": app_id, "status": "published"}

    app.include_router(router, prefix="/api/v1")
