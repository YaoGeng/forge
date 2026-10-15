"""T1.13：MS-1C gate——合规示例积木通过全链校验（validate → lint → facade 构造）。"""
from pathlib import Path

from forge_block_sdk import for_block, lint, load_interactions, validate_block_dir

CORPUS = Path(__file__).resolve().parent / "corpus" / "valid" / "demo_block"


def test_full_chain_validation():
    spec = validate_block_dir(CORPUS)
    result = lint(CORPUS)
    assert result.ok, result.violations
    assert result.violations == ()
    facade = for_block(spec, load_interactions(CORPUS / "interactions.yaml"))
    for family in ("browser", "ai", "credential", "interact"):
        assert hasattr(facade, family)
