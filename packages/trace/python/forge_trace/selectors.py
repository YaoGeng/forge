"""selector 锻造与 dom_anchor 生成（docs/11 §3 C5）。

输入元素指纹，输出 (target_selector, dom_anchor)。纯函数层，不触浏览器。
target_selector 用于回放操作（Playwright selector 语法）；
dom_anchor 用于结构比对与锚定等待的证据载体。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 动态形态提示：连续 ≥3 位数字或 ≥12 位十六进制串 → 视为随机 id（C5 稳定性判定）
_RANDOM_ID_HINT = re.compile(r"\d{3,}|[0-9a-fA-F]{12,}")
_MAX_TEXT_CHARS = 64
_MAX_PATH_DEPTH = 6
_MAX_SELECTOR_CHARS = 200
_MAX_ANCHOR_TEXT = 24
_MAX_ANCHOR_PATH = 4


@dataclass(frozen=True)
class ElementFp:
    """元素指纹（由适配器从真实 DOM 提取；path 为根→目标有序段）。"""

    tag: str
    id: str | None = None
    classes: tuple[str, ...] = ()
    attrs: dict[str, str] = field(default_factory=dict)
    text: str | None = None
    path: tuple[str, ...] = ()


def forge_selector(fp: ElementFp) -> tuple[str, str]:
    """返回 (target_selector, dom_anchor)。优先级见 C5。"""
    return _selector(fp), _anchor(fp)


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _collapse(text: str | None) -> str:
    return " ".join((text or "").split())


def _selector(fp: ElementFp) -> str:
    if fp.id and not _RANDOM_ID_HINT.search(fp.id):
        return f"#{fp.id}"
    data_items = sorted(
        (k, v) for k, v in fp.attrs.items() if k == "data-testid" or k.startswith("data-")
    )
    for key, value in data_items:
        if key == "data-testid":
            return f'[data-testid="{_css_escape(value)}"]'
    if data_items:
        key, value = data_items[0]
        return f'[{key}="{_css_escape(value)}"]'
    aria = fp.attrs.get("aria-label")
    if aria:
        return f'[aria-label="{_css_escape(aria)}"]'
    text = _collapse(fp.text)
    if text and len(text) <= _MAX_TEXT_CHARS:
        return f'text="{_css_escape(text)}"'
    return _structural(fp)


def _structural(fp: ElementFp) -> str:
    chosen = list(fp.path[-_MAX_PATH_DEPTH:])
    sel = " > ".join(chosen)
    while len(sel) > _MAX_SELECTOR_CHARS and len(chosen) > 1:
        chosen.pop(0)
        sel = " > ".join(chosen)
    return sel


def _anchor(fp: ElementFp) -> str:
    text = _collapse(fp.text)[:_MAX_ANCHOR_TEXT]
    return f"{fp.tag}|{text}|/" + "/".join(fp.path[-_MAX_ANCHOR_PATH:])
