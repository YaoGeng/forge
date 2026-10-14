"""site_inspect 最小实现：礼仪校验 → 采集 → 结构报告。

锚：TDD §7.3、M06 §3.1/§4、docs/07-MS0执行计划.md T0.2a Interfaces。
Spike 裁剪（备案见计划）：「变更频率」需多点快照，单快照不实现；
robots 匹配取 `User-Agent: *` 组；dom_digest 为整页原文哈希（身份标识用）。
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from common.browser import new_page

RATE_LIMIT_PER_HOUR = 5  # 每 host 进程内频次上限（G7 检测礼仪）

REPORT_FIELDS = (
    "url",
    "fetched_at",
    "http_status",
    "dom_digest",
    "selector_candidates",
    "login_flow_shape",
    "stability",
    "robots_respected",
    "captcha_detected",
)

# 候选选择器表（live DOM 实测固化，2026-10-14 侦察，见计划台账）
_CANDIDATE_SELECTORS = {
    "result_item": "article.Story",
    "result_title": "article.Story .Story_title a",
    "result_meta": "article.Story .Story_meta",
    "story_link": "article.Story .Story_title a",
    "story_row": "article.Story",
}

_CAPTCHA_MARKERS = ("verify you are human",)


class EtiquetteViolation(Exception):
    """礼仪拒绝：未声明域 / 超频次 / robots 禁止。"""


class TransientFetchError(Exception):
    """重试 1 次后仍失败，归因 network（TDD 附录 D probe_failed 语义）。"""


class CaptchaDetected(Exception):
    """命中验证码：不重试、不代答（G8）。"""


_rate_log: dict[str, list[float]] = {}


def reset_rate_limiter() -> None:
    _rate_log.clear()


def _rate_guard(host: str) -> None:
    """为即将发生的一次访问做频次守卫：超限抛 EtiquetteViolation，否则记账。"""
    now = time.monotonic()
    window = [t for t in _rate_log.get(host, []) if now - t < 3600]
    if len(window) >= RATE_LIMIT_PER_HOUR:
        raise EtiquetteViolation(f"rate limit exceeded for {host}: {RATE_LIMIT_PER_HOUR}/hour")
    window.append(now)
    _rate_log[host] = window


def _goto_with_retry(page, url: str, attempts: int = 2, **kwargs):
    """任意瞬时异常重试 1 次；耗尽抛 TransientFetchError。"""
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            return page.goto(url, **kwargs)
        except Exception as exc:  # noqa: BLE001 —— spike 统一按瞬时处理
            last_exc = exc
    raise TransientFetchError(f"network: {url} failed after {attempts} attempts: {last_exc}")


def _check_robots(url: str) -> bool | None:
    """robots 判定：允许 True、禁止抛 EtiquetteViolation、无法判定 None。

    404/无文件视为允许；5xx/网络错误视为无法判定（记录继续）。
    """
    robots_url = urljoin(url, "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()
    try:
        with urllib.request.urlopen(robots_url, timeout=10) as resp:
            parser.parse(resp.read().decode("utf-8", errors="replace").splitlines())
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return True  # 无 robots 文件
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return parser.can_fetch("*", url)


def _collect(page, url: str, started: float, response) -> dict:
    try:
        page.wait_for_load_state("load", timeout=15_000)
    except Exception:  # noqa: BLE001 —— load 事件可能已过
        pass
    page.wait_for_timeout(1_500)  # SPA 水合稳定窗
    # 有界等待任一候选出现：搜索页的查询往返慢于水合（t0.2_evidence 观测到的扑空）
    union = ",".join(_CANDIDATE_SELECTORS.values())
    try:
        page.wait_for_function(
            "sel => document.querySelectorAll(sel).length > 0",
            arg=union,
            timeout=15_000,
        )
    except Exception:  # noqa: BLE001 —— 空结果页如实产出空候选表
        pass
    content = page.content()
    lowered = content.lower()
    captcha = (
        any(m in lowered for m in _CAPTCHA_MARKERS)
        or page.locator('iframe[src*="captcha"]').count() > 0
        or page.locator('input[name^="cf-"]').count() > 0
    )
    if captcha:
        raise CaptchaDetected(f"captcha detected on {url}")

    candidates = {
        name: sel
        for name, sel in _CANDIDATE_SELECTORS.items()
        if page.locator(sel).count() > 0
    }
    return {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status": response.status if response is not None else 0,
        "dom_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "selector_candidates": candidates,
        "login_flow_shape": {
            "login_link_present": page.locator('a[href*="login"]').count() > 0
        },
        "stability": {
            "response_ms": int((time.monotonic() - started) * 1000),
            "load_success": True,
            "page_title": page.title(),
        },
        "robots_respected": True,
        "captcha_detected": False,
    }


def site_inspect(url: str, declared_domains: list[str], out_path=None) -> dict:
    """TDD §7.3 最小实现：返回结构报告 dict；out_path 给定时同时写 JSON 并回读校验。"""
    host = urlparse(url).hostname or ""
    if not any(host == d or host.endswith("." + d) for d in declared_domains):
        raise EtiquetteViolation(f"host {host!r} not in declared domains {declared_domains}")
    _rate_guard(host)

    robots = _check_robots(url)
    if robots is False:
        raise EtiquetteViolation(f"robots.txt disallows {url}")

    started = time.monotonic()
    with new_page() as page:
        response = _goto_with_retry(page, url, wait_until="domcontentloaded", timeout=30_000)
        report = _collect(page, url, started, response)
    report["robots_respected"] = robots
    assert set(report) == set(REPORT_FIELDS)

    if out_path is not None:
        out_path = Path(out_path)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reloaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert set(reloaded) == set(REPORT_FIELDS)
    return report
