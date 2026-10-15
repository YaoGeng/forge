"""lint 十规则（M07 §6 编码）：纯函数，LintContext 进、violations 出。

静态检查范围裁定（C5/C6，M05 防御边界同源）：AST 一层别名跟踪、不追动态
导入/getattr；防意外不防蓄意，运行时由 PermissionBroker 与出口代理兜底。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import FAMILIES, BlockSpec, InteractionSpec, has_capability

NETWORK_MODULES = {"requests", "urllib", "httpx", "socket", "http"}
BROAD_EXCEPTIONS = {"Exception", "BaseException"}
PUBLISH_VERBS = ("publish", "submit", "pay", "purchase", "checkout", "order")
EXFIL_WORDS = ("url", "uri", "body", "query", "param", "payload", "header", "token")
ASSERTIONS = ("schema", "golden_similarity")
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass(frozen=True)
class LintContext:
    spec: BlockSpec
    interactions: tuple[InteractionSpec, ...]
    block_dir: Path | None
    entry_tree: ast.Module
    py_sources: tuple[tuple[str, ast.Module], ...]
    whitelist: frozenset[str]


def _v(rule_id: str, severity: str, message: str, file: str, line: int) -> dict:
    return {"rule_id": rule_id, "severity": severity, "message": message, "file": file, "line": line}


def _dotted(node: ast.expr) -> str | None:
    """Name/Attribute 链的点串表达；其余表达式返回 None。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _collect_aliases(tree: ast.Module) -> dict[str, str]:
    """C6：仅跟踪 `X = runtime` / `X = runtime.<家族>` 一层赋值别名（含注解赋值）。"""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target = node.target
        if isinstance(target, ast.Name):
            chain = _dotted(node.value)
            if chain is not None and (chain == "runtime" or chain.startswith("runtime.")):
                aliases[target.id] = chain
    return aliases


def _resolve_chain(node: ast.expr, aliases: dict[str, str]) -> str | None:
    chain = _dotted(node)
    if chain is None:
        return None
    root, sep, rest = chain.partition(".")
    if root in aliases:
        return f"{aliases[root]}.{rest}" if sep else aliases[root]
    return chain


def _iter_runtime_calls(tree: ast.Module, aliases: dict[str, str]):
    """产出 (family, call, chain)：解析为 runtime.* 的全部调用点。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = _resolve_chain(node.func, aliases)
            if chain and chain.startswith("runtime."):
                segs = chain.split(".")
                yield segs[1] if len(segs) > 1 else "", node, chain


# ---- R1 禁止裸调用 ----


def rule_no_direct_network(ctx: LintContext) -> list[dict]:
    out: list[dict] = []
    for rel, tree in ctx.py_sources:
        banned: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in NETWORK_MODULES:
                        out.append(_v("no_direct_network", "error",
                                      f"禁止直连 {alias.name}（网络须经 runtime 外观）", rel, node.lineno))
                        banned.add(alias.asname or root)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] in NETWORK_MODULES:
                    out.append(_v("no_direct_network", "error",
                                  f"禁止从 {node.module} 导入（网络须经 runtime 外观）", rel, node.lineno))
                    for alias in node.names:
                        banned.add(alias.asname or alias.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                chain = _dotted(node.func)
                if chain and chain.split(".")[0] in banned:
                    out.append(_v("no_direct_network", "error",
                                  "禁止直连网络库调用（须经 runtime 外观）", rel, node.lineno))
    return out


# ---- R2 白名单依赖 ----


def rule_dependency_whitelist(ctx: LintContext) -> list[dict]:
    out: list[dict] = []
    if ctx.block_dir is None:
        return out
    req = ctx.block_dir / "requirements.txt"
    if not req.is_file():
        return out
    for lineno, raw in enumerate(req.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _REQUIREMENT_NAME.match(line)
        name = re.sub(r"[-_.]+", "-", (m.group(1) if m else line)).lower()
        if name not in ctx.whitelist:
            out.append(_v("dependency_whitelist", "error", f"依赖不在白名单：{line}", "requirements.txt", lineno))
    return out


# ---- R3 必须生成测试 ----


def rule_require_tests(ctx: LintContext) -> list[dict]:
    if ctx.block_dir is None:
        return []
    tests = ctx.block_dir / "tests" / "test.yaml"
    if not tests.is_file():
        return [_v("require_tests", "error", "缺少 tests/test.yaml（断言未声明）", "tests/test.yaml", 0)]
    try:
        data = yaml.safe_load(tests.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [_v("require_tests", "error", f"test.yaml 解析失败：{exc}", "tests/test.yaml", 0)]
    assertion = data.get("assertion") if isinstance(data, dict) else None
    if assertion not in ASSERTIONS:
        return [_v("require_tests", "error",
                   f"assertion 必须为 {'/'.join(ASSERTIONS)} 之一", "tests/test.yaml", 0)]
    return []


# ---- R4 能力声明一致 ----


def rule_capability_consistency(ctx: LintContext) -> list[dict]:
    out: list[dict] = []
    for rel, tree in ctx.py_sources:
        aliases = _collect_aliases(tree)
        for family, call, _chain in _iter_runtime_calls(tree, aliases):
            if family not in FAMILIES:
                continue
            # credential 家族由 permissions{type:credential} 把门（TDD §2.1 示例即无 credential capability）
            if family != "credential" and not has_capability(ctx.spec, family):
                out.append(_v("capability_consistency", "error",
                              f"runtime.{family}.* 调用未在 capabilities 声明", rel, call.lineno))
            if family == "credential":
                for arg in call.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        declared = any(
                            p.type == "credential" and p.value == arg.value
                            for p in ctx.spec.permissions
                        )
                        if not declared:
                            out.append(_v("capability_consistency", "error",
                                          f"credential \"{arg.value}\" 未在 permissions 声明", rel, call.lineno))
    return out


# ---- R5 交互声明一致 ----


def rule_interaction_consistency(ctx: LintContext) -> list[dict]:
    declared = {i.type for i in ctx.interactions}
    out: list[dict] = []
    for rel, tree in ctx.py_sources:
        aliases = _collect_aliases(tree)
        for family, call, chain in _iter_runtime_calls(tree, aliases):
            if family != "interact" or not chain.endswith(".ask"):
                continue
            arg = call.args[0] if call.args else None
            literal_type = None
            if isinstance(arg, ast.Dict):
                for k, v in zip(arg.keys, arg.values):
                    if isinstance(k, ast.Constant) and k.value == "type":
                        if isinstance(v, ast.Constant) and isinstance(v.value, str):
                            literal_type = v.value
                        break
            if literal_type is None:
                for kw in call.keywords:
                    if kw.arg == "type" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        literal_type = kw.value.value
                        break
            if literal_type is None:
                out.append(_v("interaction_consistency", "error",
                              "interact.ask spec 非字面量或缺少字面量 type，无法静态判定", rel, call.lineno))
            elif literal_type not in declared:
                out.append(_v("interaction_consistency", "error",
                              f"交互类型 {literal_type} 未在 interactions.yaml 声明", rel, call.lineno))
    return out


# ---- R6 发布类必须 confirm ----


def rule_publish_requires_confirm(ctx: LintContext) -> list[dict]:
    if any(i.type == "confirm" for i in ctx.interactions):
        return []
    for rel, tree in ctx.py_sources:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                verb = next((w for w in PUBLISH_VERBS if w in node.value.lower()), None)
                if verb:
                    return [_v("publish_requires_confirm", "error",
                               f"发布类动作（{verb}）缺少 confirm 交互声明", rel, node.lineno)]
    return []


# ---- R7 副作用幂等键 ----


def rule_side_effect_idempotency_key(ctx: LintContext) -> list[dict]:
    if not ctx.spec.side_effects:
        return []
    for node in ctx.entry_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "idempotency_key":
            return []
    return [_v("side_effect_idempotency_key", "error",
               "副作用积木缺少模块级 idempotency_key 钩子", ctx.spec.runtime.entry, 0)]


# ---- R8 凭证外传 ----


def _is_credential_call(node: ast.expr, aliases: dict[str, str]) -> bool:
    return isinstance(node, ast.Call) and (
        _resolve_chain(node.func, aliases) or ""
    ).startswith("runtime.credential.")


def _collect_handles(tree: ast.Module, aliases: dict[str, str]) -> set[str]:
    """登记承接 runtime.credential.* 结果的变量名（含注解赋值/元组解包/walrus/多目标）。"""
    handles: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not (
            isinstance(node, ast.AnnAssign) and node.value is None
        ):
            value = node.value
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if _is_credential_call(value, aliases):
                for t in targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            handles.add(n.id)
            elif isinstance(value, ast.Tuple) and isinstance(targets[0], ast.Tuple):
                for t, elem in zip(targets[0].elts, value.elts):
                    if _is_credential_call(elem, aliases) and isinstance(t, ast.Name):
                        handles.add(t.id)
        elif isinstance(node, ast.NamedExpr) and _is_credential_call(node.value, aliases):
            if isinstance(node.target, ast.Name):
                handles.add(node.target.id)
    return handles


def rule_credential_exfiltration(ctx: LintContext) -> list[dict]:
    out: list[dict] = []
    for rel, tree in ctx.py_sources:
        aliases = _collect_aliases(tree)
        handles = _collect_handles(tree, aliases)
        if not handles:
            continue

        def has_handle(node: ast.expr) -> bool:
            return any(
                isinstance(n, ast.Name) and n.id in handles for n in ast.walk(node)
            )

        for node in ast.walk(tree):
            template = None
            payload: list[ast.expr] = []
            if isinstance(node, ast.JoinedStr):
                template = "".join(
                    v.value for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                payload = list(node.values)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    template = node.left.value
                payload = [node.right]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                if isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str):
                    template = node.func.value.value
                payload = list(node.args) + [kw.value for kw in node.keywords]
            if template is not None:
                if any(w in template.lower() for w in EXFIL_WORDS) and any(has_handle(p) for p in payload):
                    out.append(_v("credential_exfiltration", "error",
                                  "凭证句柄经格式化进入 URL/请求语义模板", rel, node.lineno))
                continue
            if not isinstance(node, ast.Call):
                continue
            chain = _resolve_chain(node.func, aliases)
            if chain and (chain.startswith("runtime.api.") or chain.startswith("runtime.browser.")):
                if any(has_handle(arg) for arg in list(node.args) + [kw.value for kw in node.keywords]):
                    out.append(_v("credential_exfiltration", "error",
                                  "凭证句柄流入 runtime 网络/浏览器调用实参", rel, node.lineno))
    return out


# ---- R9 超时声明 ----


def rule_timeout_declared(ctx: LintContext) -> list[dict]:
    t = ctx.spec.runtime.timeout_sec
    if isinstance(t, int) and not isinstance(t, bool) and t >= 1:
        return []
    return [_v("timeout_declared", "error",
               "runtime.timeout_sec 缺失或必须为 ≥1 整数", ctx.spec.runtime.entry, 0)]


# ---- R10 异常处理 ----


def rule_bare_except(ctx: LintContext) -> list[dict]:
    out: list[dict] = []
    for rel, tree in ctx.py_sources:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                is_broad = True
            else:
                exc_names = {
                    n.attr if isinstance(n, ast.Attribute) else n.id
                    for n in ast.walk(node.type)
                    if isinstance(n, (ast.Name, ast.Attribute))
                }
                is_broad = bool(exc_names & BROAD_EXCEPTIONS)
            if is_broad and not any(isinstance(n, ast.Raise) for n in ast.walk(node)):
                out.append(_v("bare_except", "warning",
                              "裸/宽 except 且未重新抛出（异常须转 ComponentError 上抛）", rel, node.lineno))
    return out


RULES = (
    rule_no_direct_network,
    rule_dependency_whitelist,
    rule_require_tests,
    rule_capability_consistency,
    rule_interaction_consistency,
    rule_publish_requires_confirm,
    rule_side_effect_idempotency_key,
    rule_credential_exfiltration,
    rule_timeout_declared,
    rule_bare_except,
)
