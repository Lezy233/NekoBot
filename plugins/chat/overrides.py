"""按会话加载特殊身份/情感注入配置。"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_PATH = ROOT / "persona" / "overrides.local.toml"


def _load() -> dict[str, str]:
    """读取 persona/overrides.local.toml，返回 session_key -> 注入文本 的映射。"""
    try:
        data = tomllib.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, tomllib.TOMLDecodeError):
        return {}
    overrides: dict[str, str] = {}
    for scope in ("private", "group"):
        entries = data.get(scope)
        if not isinstance(entries, dict):
            continue
        for target_id, entry in entries.items():
            prompt = entry.get("prompt") if isinstance(entry, dict) else None
            if isinstance(prompt, str) and prompt.strip():
                overrides[f"{scope}:{target_id}"] = prompt.strip()
    return overrides


def get_override(session_key: str) -> str:
    """返回该会话需要追加注入的 system 文本，没有则返回空串。"""
    return _load().get(session_key, "")
