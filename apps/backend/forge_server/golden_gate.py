"""C8 golden 拒收规则（docs/11 §3 C8 消费侧；独立实现，不 import forge_trace 校验器）。

规则：steps[].value、URL query 值、bodies 全部字符串标量必须为 ⟦R:n⟧ 或空；
URL userinfo 段一并拒收（C8-R1② 的 trace 侧 validate 缺口在服务端闭合）。
target_selector 文本通道豁免 = C8-R1① 协同修订登记缓办，本实现不扩大不缩小。
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit

PLACEHOLDER_RE = re.compile(r"⟦R:\d+⟧")


def inspect(golden_dir) -> list[str]:
    """golden 目录三位置检查；空列表 = 通过，非空逐条指出位置。"""
    d = Path(golden_dir)
    errors: list[str] = []

    steps_path = d / "expected_steps.ndjson"
    if steps_path.exists():
        for lineno, line in enumerate(steps_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            value = row.get("value")
            if not value:  # None / 空串放行（C8-R1③「或为空」）
                continue
            where = f"expected_steps.ndjson:{lineno}"
            if row.get("action") == "nav":
                errors.extend(_check_url(value, where))
            elif not PLACEHOLDER_RE.fullmatch(value):
                errors.append(f"{where} seq={row.get('seq')}: value 未脱敏")

    stubs_path = d / "network_stubs.json"
    if stubs_path.exists():
        doc = json.loads(stubs_path.read_text(encoding="utf-8"))
        for i, entry in enumerate(doc.get("entries", [])):
            where = f"network_stubs.json:entries[{i}]"
            errors.extend(_check_url(entry.get("url", ""), where))
            for field in ("request_body", "response_body"):
                body = entry.get(field)
                if not body:
                    continue
                errors.extend(_check_body(body, f"{where}.{field}"))
    return errors


def _check_url(url: str, where: str) -> list[str]:
    errors: list[str] = []
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None:
        errors.append(f"{where}: url userinfo 未剥离")
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key, sep, value_raw = pair.partition("=")
        if sep and value_raw and not PLACEHOLDER_RE.fullmatch(unquote_plus(value_raw)):
            errors.append(f"{where}: url query 值未脱敏（{key}）")
    return errors


def _check_body(body: str, where: str) -> list[str]:
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        if not PLACEHOLDER_RE.fullmatch(body):
            return [f"{where}: 非 JSON body 未脱敏"]
        return []

    errors: list[str] = []

    def _walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            if node and not PLACEHOLDER_RE.fullmatch(node):
                errors.append(f"{where}{path}: body 字符串标量未脱敏")

    _walk(doc, "")
    return errors
