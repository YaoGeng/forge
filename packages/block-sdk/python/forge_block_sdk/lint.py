"""lint 编排：loader 短路 → adapter 门 → 十规则 → 稳定排序 → 阈值判定（C11/C12）。"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from .rules import LintContext, RULES
from .validate import ValidationError, load_block, load_interactions

WARNING_THRESHOLD = 0  # C12：v1 钉 0（R10 出现即拒），M09 联调时方可放宽

_DATA_DIR = Path(__file__).parent / "data"


class Violation(TypedDict):
    rule_id: str
    severity: str
    message: str
    file: str
    line: int


@dataclass(frozen=True)
class LintResult:
    ok: bool
    violations: tuple[Violation, ...]


def load_dependency_whitelist() -> frozenset[str]:
    """v1 白名单数据文件（占位空表）；M10 Registry 接管后换源。"""
    path = _DATA_DIR / "dependency_whitelist.txt"
    if not path.is_file():
        return frozenset()
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            names.add(line.lower())
    return frozenset(names)


def _invalid(message: str, file: str = "block.yaml", line: int = 0) -> LintResult:
    return LintResult(False, (Violation(
        rule_id="manifest_invalid", severity="error",
        message=message, file=file, line=line,
    ),))


def lint(block_dir: str | Path) -> LintResult:
    d = Path(block_dir)
    try:
        spec = load_block(d)
    except ValidationError as exc:
        return _invalid(str(exc))
    try:
        interactions = load_interactions(d / "interactions.yaml")
    except (ValidationError, OSError) as exc:
        return _invalid(f"interactions.yaml：{exc}")

    if spec.runtime.adapter != "python":
        return LintResult(False, (Violation(
            rule_id="adapter_unsupported", severity="error",
            message=f"lint v1 仅支持 python adapter（当前 {spec.runtime.adapter}，见 C10）",
            file="block.yaml", line=0,
        ),))

    py_sources: list[tuple[str, ast.Module]] = []
    for p in sorted(d.rglob("*.py")):
        rel = p.relative_to(d).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return _invalid(f"Python 语法错误：{exc}", rel, exc.lineno or 0)
        py_sources.append((rel, tree))
    entry_tree = next(
        (t for r, t in py_sources if r == spec.runtime.entry), ast.parse("")
    )

    ctx = LintContext(
        spec=spec, interactions=interactions, block_dir=d,
        entry_tree=entry_tree, py_sources=tuple(py_sources),
        whitelist=load_dependency_whitelist(),
    )
    violations: list[Violation] = [v for rule in RULES for v in rule(ctx)]
    violations.sort(key=lambda v: (v["file"], v["line"], v["rule_id"]))
    errors = sum(1 for v in violations if v["severity"] == "error")
    warnings = sum(1 for v in violations if v["severity"] == "warning")
    return LintResult(errors == 0 and warnings <= WARNING_THRESHOLD, tuple(violations))
