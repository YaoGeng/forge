"""packages/block-sdk 测试路径引导（同 proto 惯例）+ 积木目录工厂夹具。"""
import sys
from pathlib import Path

_PY = Path(__file__).resolve().parent.parent / "python"
if str(_PY) not in sys.path:
    sys.path.insert(0, str(_PY))

import textwrap

import pytest

CORPUS_BLOCK = Path(__file__).resolve().parent / "corpus" / "valid" / "demo_block"


def make_demo_block(root: Path) -> Path:
    """在 root 下落一个完整合规的 demo_block 目录（corpus 的程序化同源副本）。"""
    _copy_tree(CORPUS_BLOCK, root)
    return root


def _copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        target = dst / path.relative_to(src)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


@pytest.fixture
def demo_block_dir(tmp_path):
    """corpus demo_block 的 tmp 同源副本（lint/facade 正例基线）。"""
    d = tmp_path / "demo_block"
    return make_demo_block(d)


@pytest.fixture
def write_block(tmp_path):
    """写一个积木目录：block.yaml 缺省取 corpus 基线，可整体替换或附加文件。"""

    def _write(yaml_text: str | None = None, files: dict[str, str] | None = None, name: str = "block") -> Path:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        base = (CORPUS_BLOCK / "block.yaml").read_text(encoding="utf-8")
        (d / "block.yaml").write_text(base if yaml_text is None else textwrap.dedent(yaml_text), encoding="utf-8")
        for rel, content in (files or {}).items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(content), encoding="utf-8")
        return d

    return _write


@pytest.fixture
def drop_line():
    """删除包含 key 前缀的首个行（构造缺字段负例）。"""

    def _drop(text: str, key: str) -> str:
        return "\n".join(line for line in text.splitlines() if not line.strip().startswith(key)) + "\n"

    return _drop


@pytest.fixture
def drop_block():
    """删除 key 行及其缩进续行（构造整段缺省，如 reliability）。"""

    def _drop(text: str, key: str) -> str:
        out, dropping = [], False
        for line in text.splitlines():
            if line.strip().startswith(key):
                dropping = True
                continue
            if dropping and (line.startswith(" ") or not line.strip()):
                continue
            dropping = False
            out.append(line)
        return "\n".join(out) + "\n"

    return _drop
