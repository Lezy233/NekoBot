"""从项目文件加载聊天人格。"""

from pathlib import Path

PERSONA_PATH = Path(__file__).resolve().parents[2] / "persona" / "default.md"
FALLBACK_PERSONA = "你是一个友善、简洁、可靠的中文助手。"


def load_persona() -> str:
    try:
        content = PERSONA_PATH.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeError):
        return FALLBACK_PERSONA
    return content or FALLBACK_PERSONA

