"""selector 锻造正反用例（docs/11 §3 C5 优先级矩阵）。"""
from forge_trace.selectors import ElementFp, forge_selector

PATH6 = [
    "html:nth-of-type(1)",
    "body:nth-of-type(1)",
    "main:nth-of-type(1)",
    "div:nth-of-type(2)",
    "div:nth-of-type(3)",
    "button:nth-of-type(1)",
]


def _fp(**kw) -> ElementFp:
    kw.setdefault("tag", "button")
    return ElementFp(
        tag=kw.get("tag", "button"),
        id=kw.get("id"),
        classes=kw.get("classes", ()),
        attrs=kw.get("attrs", {}),
        text=kw.get("text"),
        path=kw.get("path", PATH6),
    )


def test_selector_prefers_stable_attributes():
    # 稳定 id 最高优先
    assert forge_selector(_fp(id="login-button"))[0] == "#login-button"
    # 动态 id 退位到 data-testid
    assert forge_selector(_fp(id="random-873", attrs={"data-testid": "search-box"}))[0] == (
        '[data-testid="search-box"]'
    )
    # data-testid 优先于其他 data-*
    assert forge_selector(
        _fp(id="random-873", attrs={"data-testid": "s", "data-role": "main"})
    )[0] == '[data-testid="s"]'
    # 无 data-testid 退位到首个 data-*（按名排序取）
    assert forge_selector(
        _fp(id="random-873", attrs={"data-zeta": "1", "data-alpha": "2"})
    )[0] == '[data-alpha="2"]'
    # 无 data-* 退位到 aria-label
    assert forge_selector(_fp(id="random-873", attrs={"aria-label": "提交"}))[0] == (
        '[aria-label="提交"]'
    )
    # 无 aria-label 退位到可见文本
    assert forge_selector(_fp(id="random-873", text="登录"))[0] == 'text="登录"'
    # 全无 → 结构路径
    assert forge_selector(_fp(id="random-873"))[0] == " > ".join(PATH6[-6:])


def test_selector_length_caps():
    path = [f"div:nth-of-type({i})" for i in range(1, 13)] + ["span:nth-of-type(1)"]
    sel, _ = forge_selector(_fp(tag="span", id="random-987", path=path))
    assert len(sel.split(" > ")) <= 6
    assert len(sel) <= 200
    assert sel.endswith("span:nth-of-type(1)")


def test_dom_anchor_format():
    # 折叠空白后 28 字符（>24），断言截断边界取前 24 字符
    text = "  确定提交按钮请在页面加载完成后再点击这里完成整个操作流程 "
    _, anchor = forge_selector(_fp(tag="button", text=text))
    assert anchor == "button|确定提交按钮请在页面加载完成后再点击这里完成整个|/" + "/".join(PATH6[-4:])
