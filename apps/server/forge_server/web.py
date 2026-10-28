"""商店 Web 页（docs/17 T2.20）：零依赖服务端渲染（字符串模板 + html.escape）。

渲染铁律（M03 §1 不变量）：通过率必带样本量；样本不足显示"数据不足"不出数字；
页脚声明原文一字不差；best_effort 警示首屏固定不可折叠。视觉 = 原型人民币双色系
（橄榄绿主 + 豆沙红点缀 ≤10%，static/store.css 与 docs/prototypes/prototype.html 同源）。
"""
from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .auth import _session_token
from .models import App
from .store import FOOTER_TEXT, trust_fields, _latest_published_version


def _nav_email(request: Request) -> str | None:
    """导航栏登录态（匿名可浏览——session 解析失败静默按未登录）。"""
    from .models import AuthSession, User

    token = _session_token(request)
    if not token:
        return None
    try:
        with request.app.state.session_factory() as s:
            session = s.query(AuthSession).filter_by(token=token).first()
            if session is None or session.expires_at <= request.app.state.clock.now():
                return None
            user = s.get(User, session.user_id)
            return user.email if user else None
    except Exception:  # noqa: BLE001 —— 导航态不阻塞浏览
        return None


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


def register_web_routes(app) -> None:
    router = APIRouter(include_in_schema=False)

    @router.get("/store", response_class=HTMLResponse)
    def store_index(request: Request):
        email = _nav_email(request)
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
  <div class="card-head"><h3>{html.escape(d["title"])}</h3>{_badge(d["level"])}{best_effort}</div>
  <div class="trust-row">认证实测 <b>{_pct(d["cert_pass"]["rate"], d["cert_pass"]["n"], d["cert_pass"]["window"])}</b></div>
  <div class="trust-row">{user_line}</div>
</a>""")
        body = ("<h1>商店</h1>"
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
<div class="detail-head"><h1>{html.escape(d["title"])}</h1>{_badge(d["level"])}</div>
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

    app.include_router(router)


def register_static(app) -> None:
    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
