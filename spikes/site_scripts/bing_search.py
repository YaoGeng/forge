"""cn.bing.com 两连搜索（s1 搜索聚合读取；standard 档）。

v2（T1.72）：新版必应把 /search 直达重定向为 JS 外壳（2026-10-23 实证零结果容器），
改为首页填词回车触发搜索；结果抽取走快照切片。既有录制/认证不受影响
（录制步骤锚点 null 平凡通过，认证冻结不回填）。
"""


"""cn.bing.com 两连搜索（s1 搜索聚合读取；standard 档）。

v2（T1.72）：2026-10-23 实证 /search 直达被重定向为 JS 外壳（零结果容器）、且外壳
导航后表单提交落在中文严格索引（英文/中文查询均「没有与此相关的结果」）；
`ensearch=1` 直达在两种会话状态下均稳定渲染 b_algo 服务端结果——改为双 ensearch
导航。结果抽取走快照切片（title 去内联标签、/ck/a 跳转包装解 base64）。
既有录制/认证不受影响（录制步骤锚点 null 平凡通过，认证冻结不回填）。
"""


def browse(port) -> dict:
    import re
    import time
    from base64 import b64decode
    from urllib.parse import parse_qs, urlsplit

    for q in ("browser+automation", "web+recorder"):
        port.goto(f"https://www.bing.com/search?q={q}&ensearch=1")
        port.wait_selector("#b_results li.b_algo", 15_000)
        time.sleep(1.5)
    html = port.snapshot_html()
    results = []
    for chunk in html.split('class="b_algo"')[1:3]:
        a = chunk.split("<a ", 1)[1]
        url = a.split('href="', 1)[1].split('"', 1)[0]
        if "/ck/a" in url:  # bing 跳转包装：目标 URL 在 u= 参数 base64 内（补齐 padding）
            u = parse_qs(urlsplit(url.replace("&amp;", "&")).query).get("u", [""])[0]
            try:
                raw = u[2:] if u.startswith("a1") else u
                url = b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
            except Exception:
                pass
        inner = a.split(">", 1)[1].split("</a>", 1)[0]
        title = inner.split("<", 1)[0].strip()  # 锚内首文本段（ensearch 布局 cite 不混入）
        if not title:
            title = re.sub(r"<[^>]+>", "", inner).split("http", 1)[0].strip()
        results.append({"title": title, "url": url})
    return {"results": results}
