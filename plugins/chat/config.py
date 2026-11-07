"""聊天插件配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# NoneBot 只把 .env 加载进自己的 Config 对象，不会写入 os.environ，
# 这里显式加载，供下方的 os.getenv 读取。
load_dotenv()


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
    chat_api: str
    chat_model: str
    summary_api: str
    summary_model: str
    temperature: float
    history_limit: int
    compress_threshold: int


settings = Settings(
    chat_api=os.getenv("CHAT_API_DEEPSEEK", "").strip(),
    chat_model=os.getenv("CHAT_MODEL_DEEPSEEK", "deepseek-flash").strip() or "deepseek-flash",
    summary_api=os.getenv("SUMMARY_API_DEEPSEEK", "").strip(),
    summary_model=os.getenv("SUMMARY_MODEL_DEEPSEEK", "").strip(),
    temperature=_float_env("DEEPSEEK_TEMPERATURE", 0.9),
    history_limit=_int_env("CHAT_HISTORY_LIMIT", 30),
    compress_threshold=_int_env("CHAT_COMPRESS_THRESHOLD", 60),
)

