"""golden 采集与值脱敏 + golden 回放路由（docs/11 §3 C8 占位符规范）。

占位符 = ⟦R:n⟧（同值同 n，映射仅存本机 redaction_maps/，不入 golden、不上传）。
脱敏位置：steps[].value、URL query 值（键保留）、请求/响应体的字符串标量
（JSON 递归；非 JSON 整体单占位符）。golden mock 匹配键 =
(method, host, path, sorted(query keys))，不含值——stub 匹配不受占位符影响。
validate_golden_no_raw 与服务端（docs/12 T1.33 golden_gate）同规则、独立实现（双保险）。
"""
from __future__ import annotations

import json
import re
import typing as t
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from forge_proto.format import write_ndjson
from forge_proto.trace import NetworkEntry, load_network, load_steps

PLACEHOLDER_RE = re.compile(r"^⟦R:\d+⟧$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RedactionMap:
    """值 → 占位符序号（同值同 n；不同值不同 n）。"""

    def __init__(self) -> None:
        self._index: dict[str, int] = {}

    def placeholder(self, value: str) -> str:
        n = self._index.setdefault(value, len(self._index))
        return f"⟦R:{n}⟧"

    def to_json(self) -> dict[str, int]:
        return dict(self._index)

    @classmethod
    def from_json(cls, doc: dict[str, int]) -> "RedactionMap":
        m = cls()
        m._index = dict(doc)
        return m


def redact(value: str, mapping: RedactionMap) -> str:
    """整值占位符化（steps[].value 非 nav 位）。"""
    return mapping.placeholder(value)


def redact_url(url: str, mapping: RedactionMap) -> str:
    """URL query 值占位符化（键/空值保留；scheme/host/path 不动）。

    占位符原样写入不做 percent 编码：脱敏 URL 只作比对数据，golden 路由
    匹配仅用键不含值（C8），原样形态保证跨文件同值同占位符可比对。
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    out: list[str] = []
    for pair in parts.query.split("&"):
        key_raw, sep, value_raw = pair.partition("=")
        value = unquote_plus(value_raw)
        if sep and value:
            out.append(f"{key_raw}={mapping.placeholder(value)}")
        else:
            out.append(pair)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(out), parts.fragment))


def redact_body(body: str, mapping: RedactionMap) -> str:
    """体脱敏：JSON 递归（字符串标量占位符化，键/数字/布尔/null 保留）；非 JSON 整体单占位符。"""
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        return mapping.placeholder(body)
    return json.dumps(_walk(doc, mapping), ensure_ascii=False)


def _walk(node, mapping: RedactionMap):
    if isinstance(node, str):
        return mapping.placeholder(node) if node else node
    if isinstance(node, dict):
        return {k: _walk(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, mapping) for v in node]
    return node


def collect_golden(
    trace_ref: str,
    *,
    store: RecordingsStore,
    environment_fingerprint: str,
    source_cert_run_id: str | None = None,
) -> Path:
    """trace → golden 三件套（值脱敏）+ 本机映射表。返回 golden 目录。"""
    rec = store.get(trace_ref)
    steps = load_steps(rec.trace_dir / "steps.ndjson")
    network = load_network(rec.trace_dir / "network.json")
    mapping = RedactionMap()

    golden_rows: list[dict] = []
    for s in steps:
        if s.value is None:
            value = None
        elif s.action == "nav":
            value = redact_url(s.value, mapping)
        else:
            value = redact(s.value, mapping)
        golden_rows.append({
            "seq": s.seq,
            "action": s.action,
            "target_selector": s.target_selector,
            "dom_anchor": s.dom_anchor,
            "value": value,
            "wait_condition": s.wait_condition,
            "ts_offset": s.ts_offset,
        })

    golden_entries: list[dict] = []
    for e in network.entries:
        golden_entries.append({
            "url": redact_url(e.url, mapping),
            "method": e.method,
            "status": e.status,
            "mime_type": e.mime_type,
            "request_body": redact_body(e.request_body, mapping) if e.request_body else None,
            "response_body": redact_body(e.response_body, mapping) if e.response_body else None,
        })

    golden_dir = store.root / "golden" / trace_ref
    golden_dir.mkdir(parents=True, exist_ok=True)
    (golden_dir / "run_meta.json").write_text(
        json.dumps({
            "environment_fingerprint": environment_fingerprint,
            "captured_at": _utc_now_iso(),
            "source_cert_run_id": source_cert_run_id,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    write_ndjson(golden_dir / "expected_steps.ndjson", golden_rows)
    (golden_dir / "network_stubs.json").write_text(
        json.dumps({"captured_at": network.captured_at, "entries": golden_entries},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    (store.redaction_dir / f"{trace_ref}.json").write_text(
        json.dumps(mapping.to_json(), ensure_ascii=False),
        encoding="utf-8",
    )
    from forge_proto.golden import validate_golden_dir

    errors = validate_golden_dir(golden_dir)
    if errors:
        raise ValueError("golden 目录自检失败: " + "; ".join(errors))
    return golden_dir


def load_stubs(golden_dir: str | Path) -> tuple[dict, ...]:
    doc = json.loads((Path(golden_dir) / "network_stubs.json").read_text(encoding="utf-8"))
    return tuple(doc["entries"])


def stub_match_key(method: str, url: str) -> tuple:
    """golden mock 匹配键：(method, host, path, sorted(query keys))——不含值（C8）。"""
    parts = urlsplit(url)
    keys = tuple(sorted(unquote_plus(p.partition("=")[0]) for p in parts.query.split("&") if p))
    return (method.upper(), parts.netloc, parts.path, keys)


def stub_matcher(stubs: t.Sequence[dict]) -> t.Callable[[NetworkEntry, str, str], dict | None]:
    """构建 golden 路由匹配器：(entry, method, url) -> stub | None。"""
    by_key = {stub_match_key(s["method"], s["url"]): s for s in stubs}

    def match(entry: NetworkEntry, method: str, url: str) -> dict | None:
        return by_key.get(stub_match_key(method, url))

    return match


def validate_golden_no_raw(golden_dir: str | Path) -> list[str]:
    """服务端同规则视角：C8 位置出现自由文本即报错（指出位置）；空列表 = 通过。"""
    d = Path(golden_dir)
    errors: list[str] = []

    steps_path = d / "expected_steps.ndjson"
    if steps_path.exists():
        for lineno, line in enumerate(steps_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            value = row.get("value")
            if value is None:
                continue
            if row.get("action") == "nav":
                errors.extend(_check_url(value, f"expected_steps.ndjson:{lineno}"))
            elif not PLACEHOLDER_RE.match(value):
                errors.append(f"expected_steps.ndjson:{lineno} seq={row.get('seq')}: value 未脱敏")

    stubs_path = d / "network_stubs.json"
    if stubs_path.exists():
        doc = json.loads(stubs_path.read_text(encoding="utf-8"))
        for i, entry in enumerate(doc.get("entries", [])):
            where = f"network_stubs.json:entries[{i}]"
            errors.extend(_check_url(entry.get("url", ""), where))
            for field in ("request_body", "response_body"):
                body = entry.get(field)
                if body is None:
                    continue
                errors.extend(_check_body(body, f"{where}.{field}"))
    return errors


def _check_url(url: str, where: str) -> list[str]:
    errors: list[str] = []
    parts = urlsplit(url)
    for pair in parts.query.split("&"):
        if not pair:
            continue
        _, sep, value_raw = pair.partition("=")
        if sep and value_raw and not PLACEHOLDER_RE.match(unquote_plus(value_raw)):
            errors.append(f"{where}: url query 值未脱敏（{key_of(pair)}）")
    return errors


def key_of(pair: str) -> str:
    return pair.partition("=")[0]


def _check_body(body: str, where: str) -> list[str]:
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        if not PLACEHOLDER_RE.match(body):
            return [f"{where}: 非 JSON body 未脱敏"]
        return []

    def walk(node, path):
        out: list[str] = []
        if isinstance(node, str):
            if node and not PLACEHOLDER_RE.match(node):
                out.append(f"{where}: body 字符串标量未脱敏（{path}）")
        elif isinstance(node, dict):
            for k, v in node.items():
                out.extend(walk(v, f"{path}.{k}"))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                out.extend(walk(v, f"{path}[{i}]"))
        return out

    return walk(doc, "$")


def apply_routes(port, store_root: Path, trace_ref: str) -> None:
    """replay mode=golden：把 golden stubs 装配进端口 golden 面。"""
    golden_dir = Path(store_root) / "golden" / trace_ref
    if not golden_dir.is_dir():
        raise ValueError(f"golden 未采集: {golden_dir}")
    port.set_routes(stub_matcher(load_stubs(golden_dir)))
