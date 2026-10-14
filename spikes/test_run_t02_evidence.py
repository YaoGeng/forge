"""评审 Finding 1 回归测试：证据归档必须拒绝空候选报告（Review Focus 1）。"""
import pytest

from run_t02_evidence import ensure_candidates


def test_empty_candidates_rejected():
    with pytest.raises(RuntimeError, match="selector candidates"):
        ensure_candidates({"selector_candidates": {}})


def test_nonempty_candidates_accepted():
    ensure_candidates({"selector_candidates": {"result_item": "article.Story"}})
