"""聊天插件配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    temperature: float
    history_limit: int


settings = Settings(
    api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat",
    temperature=_float_env("DEEPSEEK_TEMPERATURE", 0.7),
    history_limit=_int_env("CHAT_HISTORY_LIMIT", 30),
)

