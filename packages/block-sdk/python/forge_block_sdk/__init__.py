"""forge-block-sdk：block.yaml v2 校验器 / lint / runtime 外观（M07；阶段 1 渐次交付）。"""
from .lint import LintContext, LintResult, Violation, lint
from .model import (
    BLOCK_FIELDS,
    BlockSpec,
    InteractionSpec,
    PermissionSpec,
    ReliabilitySpec,
    RuntimeSpec,
)
from .validate import (
    ValidationError,
    load_block,
    load_interactions,
    validate_block_dir,
)

__all__ = [
    "BLOCK_FIELDS",
    "BlockSpec",
    "InteractionSpec",
    "LintContext",
    "LintResult",
    "PermissionSpec",
    "ReliabilitySpec",
    "RuntimeSpec",
    "ValidationError",
    "Violation",
    "lint",
    "load_block",
    "load_interactions",
    "validate_block_dir",
]
