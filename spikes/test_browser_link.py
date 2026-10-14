"""T0.1 验收测试：Patchright 直驱标准站点打开/读取/截图。

锚：docs/07-MS0执行计划.md T0.1a；docs/05-开发计划.md §4 阶段 0 T0.1。
live 目标为 hn.algolia.com（HN 官方搜索域）：本网络直连 news.ycombinator.com
不可达（裁定见计划台账 2026-10-14）；网络恢复后仅需回改 URL 常量。
"""
import pytest

from common.browser import new_page, resolve_chromium_executable

LIVE_FRONT = "https://hn.algolia.com/"


def _goto_with_retry(page, url, **kwargs):
    """瞬时网络抖动重试 1 次（TDD 附录 D probe_failed 同语义）。"""
    try:
        return page.goto(url, **kwargs)
    except Exception:
        return page.goto(url, **kwargs)


def test_patchright_open_read_screenshot(tmp_path):
    with new_page(headless=True) as page:
        _goto_with_retry(page, LIVE_FRONT, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_function(
            "document.querySelectorAll('article.Story').length >= 10", timeout=20_000
        )
        stories = page.locator("article.Story")
        assert stories.count() >= 10, f"selector_missing: article.Story count={stories.count()}"
        shot = tmp_path / "front.png"
        page.screenshot(path=str(shot))
        print(f"screenshot: {shot} bytes={shot.stat().st_size}")
        assert shot.stat().st_size > 10_000


def test_chromium_missing_raises_environment_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "empty"))
    with pytest.raises(RuntimeError, match="not installed"):
        resolve_chromium_executable()
