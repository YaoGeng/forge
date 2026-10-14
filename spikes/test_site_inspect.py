"""T0.2 验收测试：site_inspect 最小实现（礼仪校验 + 采集 + 结构报告）。

锚：docs/07-MS0执行计划.md T0.2a；TDD §7.3；M06 §3.1/§4。
live 目标为 hn.algolia.com（裁定见计划台账 2026-10-14）。
"""
import json

import pytest

from site_inspect.inspect import (
    RATE_LIMIT_PER_HOUR,
    REPORT_FIELDS,
    EtiquetteViolation,
    TransientFetchError,
    _goto_with_retry,
    _rate_guard,
    reset_rate_limiter,
    site_inspect,
)

LIVE_FRONT = "https://hn.algolia.com/"
LIVE_SEARCH = "https://hn.algolia.com/?q=python"


# ---------- 礼仪（不打网络） ----------

def test_etiquette_rejects_undeclared_domain():
    with pytest.raises(EtiquetteViolation):
        site_inspect("https://example.com/", ["news.ycombinator.com"])


def test_rate_limit_enforced():
    reset_rate_limiter()
    for _ in range(RATE_LIMIT_PER_HOUR):
        _rate_guard("news.ycombinator.com")  # 不抛
    with pytest.raises(EtiquetteViolation):
        _rate_guard("news.ycombinator.com")


# ---------- 瞬时失败重试（打桩，不依赖网络） ----------

class _FlakyPage:
    def __init__(self, fails):
        self.fails, self.calls = fails, 0

    def goto(self, *a, **k):
        self.calls += 1
        if self.calls <= self.fails:
            raise ValueError("transient")
        return "OK"


def test_retry_once_then_transient_error():
    p = _FlakyPage(fails=1)
    assert _goto_with_retry(p, "https://x/") == "OK"
    assert p.calls == 2


def test_retry_exhausted():
    p = _FlakyPage(fails=2)
    with pytest.raises(TransientFetchError):
        _goto_with_retry(p, "https://x/")
    assert p.calls == 2  # 共 2 次尝试（1 次重试）


# ---------- live 采集 ----------

def test_live_front_report(tmp_path):
    reset_rate_limiter()
    r = site_inspect(LIVE_FRONT, ["hn.algolia.com"], out_path=tmp_path / "front.json")
    assert set(r) == set(REPORT_FIELDS)
    assert r["http_status"] == 200
    assert r["robots_respected"] is True
    assert r["selector_candidates"]["story_link"]  # 200 但结构异常 → 在此失败
    assert r["captcha_detected"] is False
    assert len(r["dom_digest"]) == 64
    assert json.loads((tmp_path / "front.json").read_text(encoding="utf-8")) == r


def test_live_search_page_report(tmp_path):
    reset_rate_limiter()
    r = site_inspect(LIVE_SEARCH, ["hn.algolia.com"], out_path=tmp_path / "search.json")
    assert r["http_status"] == 200
    assert r["selector_candidates"]["result_item"]
    assert json.loads((tmp_path / "search.json").read_text(encoding="utf-8")) == r
