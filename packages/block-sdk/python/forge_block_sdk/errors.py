"""ComponentError 与错误码（TDD 附录 D 编码；组件可抛子集 = C9 裁定）。"""
from __future__ import annotations

COMPONENT_ERROR_CODES = frozenset(
    {"selector_missing", "output_schema_violation", "component_timeout"}
)


class ComponentError(RuntimeError):
    """积木可抛的唯一异常类型；code 必属附录 D 组件可抛子集。

    retryable 判定归 DAG 执行器（错误码 × 副作用属性矩阵），组件侧不重复编码。
    """

    def __init__(self, code: str, message: str, detail: dict | None = None):
        if code not in COMPONENT_ERROR_CODES:
            raise ValueError(
                f"未知组件错误码：{code}（须属 {'/'.join(sorted(COMPONENT_ERROR_CODES))}）"
            )
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.detail = detail

    def __reduce__(self):
        return (self.__class__, (self.code, self.message, self.detail))


class PermissionDenied(RuntimeError):
    """PermissionBroker 域拒绝（声明级门）；运行时映射附录 D permission_denied。"""


class BackendNotWired(RuntimeError):
    """MS-1C 桩：权限门已通过、后端调用点未接线（M05 sidecar 接线后替换）。"""
