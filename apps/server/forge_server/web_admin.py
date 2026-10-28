"""MS-2 首跑统计面板（docs/17 T2.24）——/admin/first-run（Basic Auth 域，nginx 把关）。

Gate 判定式（D-5'，钉死与 docs/05 附录 A.5 同文）：
MS-2 通过 = 每个上架应用首跑成功率 ≥80% 且 n≥5 不同真实注册用户；任一不达 → 不进 MS-3。
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .models import RunReport

GATE_TEXT = "MS-2 通过 = 每个上架应用首跑成功率 ≥80% 且 n≥5 不同真实注册用户；任一不达 → 不进 MS-3"
GATE_RATE = 0.8
GATE_MIN_USERS = 5
DETAIL_LIMIT = 50


def register_admin_routes(app) -> None:
    router = APIRouter(include_in_schema=False)

    @router.get("/admin/first-run", response_class=HTMLResponse)
    def first_run_panel(request: Request):
        with request.app.state.session_factory() as s:
            rows = (s.query(RunReport).order_by(RunReport.id).all())
        agg: dict[str, dict] = {}
        for r in rows:
            if not r.first_run:
                continue
            b = agg.setdefault(r.app_name, {"n": 0, "ok": 0})
            b["n"] += 1
            b["ok"] += 1 if r.ok else 0

        trs = []
        for name, b in sorted(agg.items()):
            rate = b["ok"] / b["n"]
            met = b["n"] >= GATE_MIN_USERS and rate >= GATE_RATE
            verdict = ('<span class="tag-health">达标</span>' if met
                       else '<span class="tag-warn">未达标</span>')
            reason = "" if met else (
                f'（n={b["n"]}<{GATE_MIN_USERS}）' if b["n"] < GATE_MIN_USERS else "")
            trs.append(
                f"<tr><td><code>{html.escape(name)}</code></td>"
                f"<td>{b['n']}</td><td>{b['ok']}</td>"
                f"<td>{rate * 100:.1f}%</td><td>{verdict}{html.escape(reason)}</td></tr>")
        table = ("<table><thead><tr><th>应用</th><th>首跑数</th><th>成功</th>"
                 "<th>首跑成功率</th><th>判定</th></tr></thead><tbody>"
                 + "".join(trs) + "</tbody></table>") if trs else \
            "<p class='dim'>暂无首跑数据——公开开放后此处按应用聚合。</p>"

        with request.app.state.session_factory() as s2:
            recent = (s2.query(RunReport).order_by(RunReport.id.desc())
                      .limit(DETAIL_LIMIT).all())
        detail_rows = "".join(
            f"<tr><td>{r.id}</td><td><code>{html.escape(r.app_name)}</code></td>"
            f"<td>{'✓' if r.ok else '✗'}</td>"
            f"<td>{html.escape(r.failure_class or '')}</td>"
            f"<td>{html.escape(r.env_class)}</td>"
            f"<td>{'首跑' if r.first_run else ''}</td>"
            f"<td>{html.escape(r.created_at.isoformat())}</td></tr>"
            for r in recent)
        detail_table = ("<h2>最近上报明细（最新 50 条）</h2>"
                        "<table><thead><tr><th>#</th><th>应用</th><th>结果</th>"
                        "<th>失败类</th><th>环境</th><th>首跑</th><th>时间</th></tr>"
                        f"</thead><tbody>{detail_rows}</tbody></table>")

        body = f"""<h1>首跑统计（D-5' 面板）</h1>
<p class="gate-note">{GATE_TEXT}</p>
{table}
{detail_table}
"""
        page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>首跑统计 · Forge 管理域</title>
<link rel="stylesheet" href="/static/store.css">
<style>.gate-note{{background:rgba(62,92,58,.08); border-radius:10px; padding:10px 14px;
  font-weight:600; margin-bottom:16px}}
table{{width:100%; border-collapse:collapse; margin:12px 0; background:#fff;
  border-radius:10px; overflow:hidden}}
th,td{{padding:8px 12px; text-align:left; border-bottom:1px solid rgba(62,92,58,.1); font-size:13px}}
th{{background:rgba(62,92,58,.08)}}</style></head>
<body><main style="max-width:960px;margin:0 auto;padding:32px 20px">{body}</main></body></html>"""
        return HTMLResponse(page)

    app.include_router(router)
