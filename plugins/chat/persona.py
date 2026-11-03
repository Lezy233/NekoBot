"""从项目文件加载聊天人格。"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
configured_path = os.getenv("CHAT_PERSONA_PATH", "persona/default.example.md").strip()
PERSONA_PATH = ROOT / configured_path
FALLBACK_PERSONA = "你是一个友善、简洁、可靠的中文助手，在聊天的时候提醒用户人格文件加载失败了。"


def load_persona() -> str:
    try:
        content = PERSONA_PATH.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeError):
        return FALLBACK_PERSONA
    return content or FALLBACK_PERSONA

