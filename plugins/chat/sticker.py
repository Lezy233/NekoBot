"""把 LLM 输出中的表情标签转换为 OneBot 消息段。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from nonebot.adapters.onebot.v11 import Message, MessageSegment

ROOT = Path(__file__).resolve().parents[2]
STICKER_DIR = ROOT / "stickers"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

TAG_PATTERN = re.compile(r"\[表情:([^\[\]]+)\]")


def _scan() -> dict[str, Path]:
    """递归扫描 stickers/（跟随软链接），返回 表情名称 -> 图片路径。

    名称默认取文件名（不含扩展名）；不同子目录下的同名文件用「子目录/文件名」区分。
    """
    stems: dict[str, list[Path]] = {}
    for dirpath, _dirnames, filenames in os.walk(STICKER_DIR, followlinks=True):
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in IMAGE_SUFFIXES:
                stems.setdefault(path.stem, []).append(path)
    table: dict[str, Path] = {}
    for stem, paths in stems.items():
        if len(paths) == 1:
            table[stem] = paths[0]
        else:
            for path in paths:
                table[f"{path.parent.name}/{stem}"] = path
    return table


def available_prompt() -> str:
    """生成注入给模型的可用表情名称列表，没有任何表情时返回空串。"""
    names = sorted(_scan())
    if not names:
        return ""
    return "当前可用的表情包名称（仅可在 [表情:名称] 标签中使用这些名称）：" + "、".join(names)


def parse(text: str) -> Message:
    """把含 [表情:名称] 标签的文本拆成文本段和图片段；未知标签按原文输出。"""
    message = Message()
    table = _scan()
    pos = 0
    for match in TAG_PATTERN.finditer(text):
        if match.start() > pos:
            message.append(MessageSegment.text(text[pos : match.start()]))
        path = table.get(match.group(1))
        if path is not None:
            message.append(MessageSegment.image(path.as_uri()))
        else:
            message.append(MessageSegment.text(match.group(0)))
        pos = match.end()
    if pos < len(text):
        message.append(MessageSegment.text(text[pos:]))
    if not message:
        message.append(MessageSegment.text(text))
    return message
