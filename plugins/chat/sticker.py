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

    每个文件都注册「子目录/文件名」形式的名称；文件名全库唯一时额外注册
    不带目录的短名作为别名。两种名称指向同一张图。
    """
    stems: dict[str, list[Path]] = {}
    for dirpath, _dirnames, filenames in os.walk(STICKER_DIR, followlinks=True):
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in IMAGE_SUFFIXES:
                stems.setdefault(path.stem, []).append(path)
    table: dict[str, Path] = {}
    for stem, paths in stems.items():
        for path in paths:
            table[f"{path.parent.name}/{stem}"] = path
        if len(paths) == 1:
            table[stem] = paths[0]
    return table


def _canonical_names(table: dict[str, Path]) -> list[str]:
    """注入给模型的规范名称：短名（唯一时）或 子目录/文件名（重名时），不含别名。"""
    return sorted(name for name in table if "/" not in name or name.rsplit("/", 1)[-1] not in table)


def available_prompt() -> str:
    """生成注入给模型的可用表情名称列表，没有任何表情时返回空串。"""
    names = _canonical_names(_scan())
    if not names:
        return ""
    return "当前可用的表情包名称（仅可在 [表情:名称] 标签中使用这些名称）：" + "、".join(names)


def list_dir(rel: str) -> str | None:
    """列出目录下的表情文件名，rel 相对 stickers/（找不到时回退 stickers/emoji/）。

    rel 为空时列出 stickers/ 下的子目录；目录不存在或越出 stickers/ 时返回 None。
    """
    rel_path = Path(rel)
    if ".." in rel_path.parts or rel_path.is_absolute():
        return None
    base = STICKER_DIR / rel_path if rel else STICKER_DIR
    if not base.is_dir():
        alt = STICKER_DIR / "emoji" / rel_path
        if rel and alt.is_dir():
            base = alt
        else:
            return None
    if not rel:
        return "、".join(sorted(p.name for p in base.iterdir() if p.is_dir())) or "（无子目录）"
    files = sorted(p.name for p in base.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    return "  ".join(f"'{name}'" for name in files) or "（无表情文件）"


def render(name: str) -> Message | None:
    """按名称生成仅含该表情的消息，未找到对应图片时返回 None。"""
    path = _scan().get(name)
    if path is None:
        return None
    message = Message()
    message.append(_image_segment(path))
    return message


def _image_segment(path: Path) -> MessageSegment:
    """生成图片段。NapCat 跑在 Docker 里读不到宿主机的 file:// 路径，改用 base64 内联。"""
    return MessageSegment.image(path.read_bytes())


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
            message.append(_image_segment(path))
        else:
            message.append(MessageSegment.text(match.group(0)))
        pos = match.end()
    if pos < len(text):
        message.append(MessageSegment.text(text[pos:]))
    if not message:
        message.append(MessageSegment.text(text))
    return message
