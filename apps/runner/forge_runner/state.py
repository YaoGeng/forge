"""本地状态（docs/17 T2.10）：~/.forge/state.json（FORGE_HOME 可覆盖；0600）。

持有：登录 token、TOFU 公钥钉扎、已装应用版本缓存。密码绝不落盘。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def home_dir() -> Path:
    root = os.environ.get("FORGE_HOME")
    return Path(root) if root else Path.home() / ".forge"


def apps_dir() -> Path:
    return home_dir() / "apps"


def artifacts_dir() -> Path:
    """运行产物目录（docs/17 T2.10 钉扎 ~/forge/artifacts/<app>/）。"""
    return Path.home() / "forge" / "artifacts"


def state_path() -> Path:
    return home_dir() / "state.json"


def load() -> dict:
    p = state_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先临时文件后替换，避免半写状态
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
