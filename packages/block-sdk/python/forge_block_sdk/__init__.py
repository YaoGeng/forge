"""forge-block-sdk：block.yaml v2 校验器 / lint / runtime 外观（M07；阶段 1 渐次交付）。"""
from .errors import (
    COMPONENT_ERROR_CODES,
    BackendNotWired,
    ComponentError,
    PermissionDenied,
)
from .lint import LintContext, LintResult, Violation, lint
from .model import (
    BLOCK_FIELDS,
    BlockSpec,
    InteractionSpec,
    PermissionSpec,
    ReliabilitySpec,
    RuntimeSpec,
)
from .runtime import CredentialHandle, RuntimeFacade, for_block
from .validate import (
    ValidationError,
    load_block,
    load_interactions,
    validate_block_dir,
)

__all__ = [
    "BLOCK_FIELDS",
    "COMPONENT_ERROR_CODES",
    "BackendNotWired",
    "BlockSpec",
    "ComponentError",
    "CredentialHandle",
    "InteractionSpec",
    "LintContext",
    "LintResult",
    "PermissionDenied",
    "PermissionSpec",
    "ReliabilitySpec",
    "RuntimeFacade",
    "RuntimeSpec",
    "ValidationError",
    "Violation",
    "for_block",
    "lint",
    "load_block",
    "load_interactions",
    "validate_block_dir",
]
