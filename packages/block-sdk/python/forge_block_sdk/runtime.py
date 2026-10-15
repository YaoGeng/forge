"""runtime 外观桩：M05 §4 十一家族命名空间 + 声明级权限门，门后统一 BackendNotWired。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .errors import BackendNotWired, PermissionDenied
from .model import BlockSpec

FAMILIES = (
    "browser", "file", "office", "ai", "code", "data",
    "api", "credential", "confirm", "interact", "probe",
)


@dataclass(frozen=True)
class CredentialHandle:
    """不透明凭证句柄（token 随机生成，不携带明文名）。"""
    token: str = field(default_factory=lambda: uuid.uuid4().hex)


def _has_capability(spec: BlockSpec, family: str) -> bool:
    return any(c == family or c.startswith(family + "_") for c in spec.capabilities)


def _declared_credentials(spec: BlockSpec) -> set[str]:
    return {p.value for p in spec.permissions if p.type == "credential"}


class RuntimeFacade:
    """积木内 `runtime` 对象：家族属性即调用面，全部先过声明级权限门。"""

    def __init__(self, spec: BlockSpec, interactions: tuple = ()):
        self._spec = spec
        self._interactions = interactions
        for family in FAMILIES:
            setattr(self, family, _FamilyEndpoint(self, family))
        self.credential = _CredentialEndpoint(self)
        self.interact = _InteractEndpoint(self)

    def _gate_family(self, family: str) -> None:
        if not _has_capability(self._spec, family):
            raise PermissionDenied(f"runtime.{family}.* 未在 capabilities 声明")

    def _declared_interaction_types(self) -> set[str]:
        return {i.type for i in self._interactions}

    def request(self, spec: dict) -> None:
        """runtime.confirm 请求面：门后未接线。"""
        self._gate_family("confirm")
        _require_mapping(spec)
        raise BackendNotWired("confirm.request 后端未接线（MS-1C 桩）")


class _FamilyEndpoint:
    __slots__ = ("_facade", "_family")

    def __init__(self, facade: RuntimeFacade, family: str):
        self._facade = facade
        self._family = family

    def __getattr__(self, method: str):
        def _call(*args, **kwargs):
            self._facade._gate_family(self._family)
            raise BackendNotWired(
                f"runtime.{self._family}.{method} 后端未接线（MS-1C 桩）"
            )
        return _call


class _CredentialEndpoint:
    __slots__ = ("_facade",)

    def __init__(self, facade: RuntimeFacade):
        self._facade = facade

    def get(self, name: str) -> CredentialHandle:
        if name not in _declared_credentials(self._facade._spec):
            raise PermissionDenied(f"credential \"{name}\" 未在 permissions 声明")
        raise BackendNotWired("credential.get 句柄发放未接线（MS-1C 桩）")


class _InteractEndpoint:
    __slots__ = ("_facade",)

    def __init__(self, facade: RuntimeFacade):
        self._facade = facade

    def ask(self, spec: dict) -> None:
        self._facade._gate_family("interact")
        _require_mapping(spec)
        itype = spec.get("type")
        if not isinstance(itype, str):
            raise TypeError("interact.ask spec 缺少字符串 type")
        if itype not in self._facade._declared_interaction_types():
            raise PermissionDenied(f"交互类型 {itype} 未在 interactions.yaml 声明")
        raise BackendNotWired("interact.ask 后端未接线（MS-1C 桩）")


def _require_mapping(spec) -> None:
    if not isinstance(spec, dict):
        raise TypeError("spec 应为 mapping")


def for_block(spec: BlockSpec, interactions: tuple = ()) -> RuntimeFacade:
    """从 BlockSpec 构造积木的 runtime 外观（宿主加载积木时调用；interactions 供 ask 门校验）。"""
    return RuntimeFacade(spec, interactions)
