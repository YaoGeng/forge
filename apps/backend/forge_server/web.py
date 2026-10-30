"""商店 Web 页（docs/17 T2.20）：零依赖服务端渲染（字符串模板 + html.escape）。

渲染铁律（M03 §1 不变量）：通过率必带样本量；样本不足显示"数据不足"不出数字；
页脚声明原文一字不差；best_effort 警示首屏固定不可折叠。视觉 = 原型人民币双色系
（橄榄绿主 + 豆沙红点缀 ≤10%，static/store.css 与 docs/prototypes/prototype.html 同源）。
"""
from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth import _session_token
from .models import App
from .store import FOOTER_TEXT, trust_fields, _latest_published_version


def _nav_user(request: Request):
    """会话用户（匿名浏览可——解析失败静默按未登录）。"""
    from .models import AuthSession, User

    token = _session_token(request)
    if not token:
        return None
    try:
        with request.app.state.session_factory() as s:
            session = s.query(AuthSession).filter_by(token=token).first()
            if session is None or session.expires_at <= request.app.state.clock.now():
                return None
            return s.get(User, session.user_id)
    except Exception:  # noqa: BLE001 —— 导航态不阻塞浏览
        return None


def _nav_email(request: Request) -> str | None:
    user = _nav_user(request)
    return user.email if user else None


def _runner_info(request: Request) -> dict | None:
    from .store import runner_info_data

    return runner_info_data(request.app.state)


def _pct(rate: float, n: int, window: str) -> str:
    """M03 §3.1 格式：XX%（近 N 次，YYYY-MM）——无样本量绝不出数字。"""
    month = (window or "")[:7]
    suffix = f"，{month}" if month else ""
    return f"{round(rate * 100):.0f}%（近 {n} 次{suffix}）"


def _page(title: str, body: str, email: str | None) -> str:
    nav_right = (f'<span class="nav-email">{html.escape(email)}</span>'
                 f'<a class="btn ghost small" href="/me/library">我的应用</a>'
                 ) if email else '<a class="btn ghost small" href="/login">登录</a>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Forge 商店</title>
<link rel="stylesheet" href="/static/store.css">
</head>
<body>
<header class="topbar">
  <a class="brand" href="/store"><span class="mark">积</span>Forge 商店</a>
  <nav>{nav_right}</nav>
</header>
<main>
{body}
</main>
<footer class="page-footer"><p>{FOOTER_TEXT}</p><p class="dim">© 2026 Forge · 平台自制应用 · 免费获取</p></footer>
</body>
</html>"""


def _badge(level: str) -> str:
    return f'<span class="badge badge-{html.escape(level)}">{html.escape(level)}</span>'


_HEALTH_LABEL = {"ok": "健康", "degraded": "降级", "stale": "待复检"}


def _health_badge(health: str | None) -> str:
    if health not in _HEALTH_LABEL:
        return ""
    cls = "tag-warn" if health == "degraded" else "tag-health"  # 豆沙红仅降级用
    return f'<span class="{cls}">{_HEALTH_LABEL[health]}</span>'


def register_web_routes(app) -> None:
    router = APIRouter(include_in_schema=False)

    # ---------- 认证表单页（T2.21；逻辑与 API 同源：auth.py 助手复用） ----------

    def _auth_page(error: str = "", registered: bool = False) -> str:
        err_html = (f'<p class="form-error">{html.escape(error)}</p>' if error else "")
        login_form = f"""
<form method="post" action="/login" class="panel form-panel">
  <h2>登录</h2>{err_html if not registered else ""}
  <label>邮箱<input type="email" name="email" required></label>
  <label>密码<input type="password" name="password" required></label>
  <button type="submit" class="btn">登录</button>
</form>"""
        reg_form = f"""
<form method="post" action="/register" class="panel form-panel">
  <h2>注册</h2>{err_html if registered else ""}
  <label>邮箱<input type="email" name="email" required></label>
  <label>密码<input type="password" name="password" required minlength="8"></label>
  <button type="submit" class="btn ghost">免费注册</button>
</form>"""
        body = ("<h1>账号</h1>"
                f'<div class="auth-grid">{login_form}{reg_form}</div>')
        return _page("账号", body, None)

    @router.get("/login")
    def login_page():
        return HTMLResponse(_auth_page())

    @router.get("/register")
    def register_page():
        return HTMLResponse(_auth_page(registered=True))

    def _auth_submit(request: Request, email: str, password: str, *, is_register: bool):
        from .auth import _validate, hash_password, issue_session, verify_password
        from .models import User

        email = email.strip().lower()
        now = request.app.state.clock.now()
        try:
            _validate(email, password)
        except Exception as exc:  # noqa: BLE001 —— 表单错误回显而非 422 JSON
            detail = getattr(exc, "detail", None) or str(exc)
            return HTMLResponse(_auth_page(detail, registered=is_register))
        with request.app.state.session_factory() as s:
            user = s.query(User).filter_by(email=email).first()
            if is_register:
                if user is not None:
                    return HTMLResponse(_auth_page("邮箱已注册", registered=True))
                user = User(email=email, password_hash=hash_password(password),
                            created_at=now)
                s.add(user)
                s.commit()
            elif user is None or not verify_password(password, user.password_hash):
                return HTMLResponse(_auth_page("邮箱或密码错误"))
            token = issue_session(request.app.state.session_factory, user.id, now)
        resp = RedirectResponse("/store", status_code=302)
        resp.set_cookie("forge_sid", token, httponly=True, samesite="lax",
                        max_age=30 * 86400)
        return resp

    @router.post("/login")
    def login_submit(request: Request, email: str = Form(""), password: str = Form("")):
        return _auth_submit(request, email, password, is_register=False)

    @router.post("/register")
    def register_submit(request: Request, email: str = Form(""),
                        password: str = Form("")):
        return _auth_submit(request, email, password, is_register=True)

    # ---------- 商店页 ----------

    @router.get("/store", response_class=HTMLResponse)
    def store_index(request: Request, err: str = ""):
        email = _nav_email(request)
        err_html = (f'<p class="form-error">{html.escape(err)}</p>' if err else "")
        now = request.app.state.clock.now()
        cards = []
        with request.app.state.session_factory() as s:
            for app_row in s.query(App).order_by(App.id).all():
                if _latest_published_version(s, app_row) is None:
                    continue
                d = trust_fields(s, app_row, now=now)
                user_line = (f'用户运行 {_pct(d["user_pass"]["rate"], d["user_pass"]["n"], "")}'
                             if d["user_pass"] else
                             '<span class="dim">用户运行 数据不足</span>')
                best_effort = ('<span class="tag-warn">高变更</span>'
                               if d["best_effort"] else "")
                cards.append(f"""<a class="card" href="/store/app/{html.escape(d["name"])}">
  <div class="card-head"><h3>{html.escape(d["title"])}</h3>{_badge(d["level"])}{_health_badge(d.get("health"))}{best_effort}</div>
  <div class="trust-row">认证实测 <b>{_pct(d["cert_pass"]["rate"], d["cert_pass"]["n"], d["cert_pass"]["window"])}</b></div>
  <div class="trust-row">{user_line}</div>
</a>""")
        body = ("<h1>商店</h1>" + err_html
                + ('<div class="grid">' + "".join(cards) + "</div>" if cards
                   else '<p class="dim">暂无上架应用</p>'))
        return HTMLResponse(_page("商店", body, email))

    @router.get("/store/app/{name}", response_class=HTMLResponse)
    def app_detail_page(name: str, request: Request):
        email = _nav_email(request)
        now = request.app.state.clock.now()
        with request.app.state.session_factory() as s:
            app_row = s.query(App).filter_by(name=name).first()
            av = _latest_published_version(s, app_row) if app_row else None
            if app_row is None or av is None:
                return HTMLResponse(_page(
                    "未找到", "<h1>应用不存在或未上架</h1>"
                    '<p class="dim"><a href="/store">返回商店</a></p>', email),
                    status_code=404)
            d = trust_fields(s, app_row, now=now)
            comp = "".join(
                f"<li><code>{html.escape(str(step.get('block')))}</code></li>"
                for step in (av.composition_json or []))
        c1_note = ('<p class="c1-note">平台环境实测，平台抽查复核</p>'
                   if d["level"] == "C1" else "")
        user_line = (f"<b>{_pct(d['user_pass']['rate'], d['user_pass']['n'], '')}</b>"
                     if d["user_pass"] else
                     '<span class="dim">数据不足（最低 30 次真实运行）</span>')
        login_sites = (html.escape("、".join(d["login_sites"]))
                       if d["login_sites"] else "无")
        banner = ("""<div class="best-effort-banner">⚠ 高变更站点应用：站点页面频繁变化，
运行结果具有不确定性（best-effort 场景）。失败不视为应用缺陷，以信任字段口径为准。</div>"""
                  if d["best_effort"] else "")
        body = f"""
{banner}
<div class="detail-head"><h1>{html.escape(d["title"])}</h1>{_badge(d["level"])}{_health_badge(d.get("health"))}</div>
<p class="dim">{html.escape(d["name"])} · v{html.escape(str(av.version))}</p>
<section class="panel">
  <h2>信任字段</h2>
  <dl class="trust">
    <dt>认证实测通过率</dt><dd><b>{_pct(d["cert_pass"]["rate"], d["cert_pass"]["n"], d["cert_pass"]["window"])}</b>{c1_note}</dd>
    <dt>用户运行成功率</dt><dd>{user_line}</dd>
    <dt>维护期</dt><dd>{html.escape(d["maintenance"])}</dd>
    <dt>预估 Token 成本</dt><dd>{html.escape(d["token_cost"])}</dd>
    <dt>需要登录的站点</dt><dd>{login_sites}</dd>
    <dt>人工交互</dt><dd>{html.escape(d["interactions"])}</dd>
  </dl>
</section>
<section class="panel">
  <h2>组成积木</h2>
  <ul class="blocks">{comp}</ul>
</section>
<form method="post" action="/store/app/{html.escape(d["name"])}/acquire" class="acquire">
  <button type="submit" class="btn">免费获取</button>
  <span class="dim">获取后可在「我的应用」查看运行指引</span>
</form>
"""
        return HTMLResponse(_page(d["title"], body, email))

    # ---------- My Library 与网页端获取（T2.21） ----------

    @router.post("/store/app/{name}/acquire")
    def web_acquire(name: str, request: Request):
        user = _nav_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=302)
        from .store import acquire_entitlement

        now = request.app.state.clock.now()
        with request.app.state.session_factory() as s:
            try:
                acquire_entitlement(s, user.id, name, now)
            except Exception as exc:  # noqa: BLE001 —— HTTPException detail 回显
                detail = getattr(exc, "detail", None) or "获取失败"
                return RedirectResponse(
                    f"/store?err={html.escape(detail)}", status_code=302)
        return RedirectResponse("/me/library", status_code=302)

    @router.get("/me/library", response_class=HTMLResponse)
    def library_page(request: Request):
        user = _nav_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=302)
        from .models import Entitlement

        with request.app.state.session_factory() as s:
            rows = (s.query(Entitlement).filter_by(user_id=user.id)
                    .order_by(Entitlement.id).all())
            titles = {a.name: a.title for a in s.query(App).all()}
            cards = []
            for e in rows:
                title = titles.get(e.app_name, e.app_name)
                activated = (html.escape(e.activated_at.isoformat())
                             if e.activated_at else '<span class="dim">未激活</span>')
                cards.append(f"""<div class="card lib-card">
  <div class="card-head"><h3>{html.escape(title)}</h3>
    <span class="dim"><code>{html.escape(e.app_name)}</code> v{html.escape(e.version)}</span></div>
  <div class="trust-row">获取于 {html.escape(e.acquired_at.isoformat())}</div>
  <div class="trust-row">激活：{activated}</div>
</div>""")
        runner = _runner_info(request)
        if runner:
            guide = f"""<ol class="guide">
  <li>下载运行器：<a class="btn small" href="{runner["url"]}">forge-runner-{runner["version"]}-win.exe</a></li>
  <li>命令行登录：<code>forge-runner login 你的邮箱</code></li>
  <li>运行应用：<code>forge-runner run 应用名</code>（如 <code>forge-runner run hn_weekly</code>）</li>
</ol>
<p class="dim">产物说明：应用输出的 Excel/CSV 默认写入本机临时目录 forge-blocks 文件夹；首跑结果将匿名计入应用成功率统计。</p>"""
        else:
            guide = '<p class="dim">运行器即将上线，敬请期待——上线后此处将显示下载链接与三步运行指引。</p>'
        cards_html = ('<div class="grid">' + "".join(cards) + "</div>" if cards
                      else '<p class="dim">还没有获取任何应用——<a href="/store">去商店看看</a></p>')
        body = f"<h1>我的应用</h1>{cards_html}" \
               '<section class="panel"><h2>运行指引</h2>' + guide + "</section>"
        return HTMLResponse(_page("我的应用", body, user.email))

    app.include_router(router)


def register_static(app) -> None:
    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
