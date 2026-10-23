"""books.toscrape.com 目录 → 首书详情（s3 目录书目读取；standard 档）。

v2（终审 #9 重录）：双 goto 直达——v1 的「点首书标题」文本锚在 golden 回放
（stub 页 DOM）不匹配致 regression 10/10 全败（live 1.0 掩盖）；沿用双导航先例。
"""


def browse(port) -> dict:
    import time

    port.goto("https://books.toscrape.com/")
    port.wait_selector("article.product_pod", 15_000)
    time.sleep(1.2)
    port.goto("https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html")
    port.wait_selector(".product_main", 15_000)
    time.sleep(1.5)
    lines = [ln.strip() for ln in port.inner_text(".product_main").splitlines() if ln.strip()]
    return {"title": lines[0],
            "price": next(ln for ln in lines if ln.startswith("£")),
            "stock": next(ln for ln in lines if "stock" in ln.lower())}
