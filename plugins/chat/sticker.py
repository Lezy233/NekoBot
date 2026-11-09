"""表情模块：目录元数据（catalog.json）+ intent 检索。

模型只决定表达意图（intent），文件路径、图片真实性和 OneBot 图片段
生成全部由本模块控制。加载 catalog 时跳过任何无效条目，不导致启动失败。
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from .plan import ChatPlan, StickerPart, TextPart

ROOT = Path(__file__).resolve().parents[2]
STICKER_DIR = ROOT / "stickers"
CATALOG_PATH = STICKER_DIR / "catalog.json"

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


def _resolve_entry_path(raw_path: object) -> Path | None:
    """校验 catalog 中的 path：相对路径、不含 ..、位于 STICKER_DIR 内、存在且扩展名合法。

    包含性校验只做词法归一化，不跟随软链接——stickers/ 内的子目录允许是
    软链接（与 _scan 的 followlinks 行为一致），读取时由操作系统自然跟随。
    """
    if not isinstance(raw_path, str) or not raw_path:
        return None
    rel = Path(raw_path)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    candidate = Path(os.path.abspath(STICKER_DIR / rel))
    base = Path(os.path.abspath(STICKER_DIR))
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    return candidate


def _load_catalog() -> dict[str, list[Path]]:
    """读取 catalog.json 建立 intent -> 有效图片路径 索引，按 mtime 缓存。"""
    global _catalog_cache
    try:
        mtime = CATALOG_PATH.stat().st_mtime
    except OSError:
        return {}
    cache = _catalog_cache
    if cache is not None and cache[0] == mtime:
        return cache[1]

    index: dict[str, list[Path]] = {}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning(f"表情目录 catalog.json 解析失败，按无表情处理：{exc}")
        _catalog_cache = (mtime, index)
        return index
    if not isinstance(data, list):
        logger.warning("表情目录 catalog.json 顶层必须是数组，按无表情处理")
        _catalog_cache = (mtime, index)
        return index

    for entry in data:
        if not isinstance(entry, dict):
            continue
        path = _resolve_entry_path(entry.get("path"))
        if path is None:
            continue
        intents = entry.get("intents")
        if not isinstance(intents, list):
            continue
        for intent in intents:
            if isinstance(intent, str) and intent:
                index.setdefault(intent, []).append(path)
    _catalog_cache = (mtime, index)
    return index


_catalog_cache: tuple[float, dict[str, list[Path]]] | None = None


def resolve_sticker(intent: str) -> Message | None:
    """按 intent 检索 catalog 候选图片并随机选一张生成图片消息；任何失败都返回 None。

    intent 未命中 catalog 时回退按历史名称（子目录/文件名，来自 _scan）检索，
    供 <echo> 等调试入口复用同一渲染管线；模型路径的 intent 白名单由 plan 模块保证。
    未知 intent、无有效候选、图片读取失败均不抛到聊天主流程。
    """
    candidates = _load_catalog().get(intent)
    if candidates:
        path = random.choice(candidates)
    else:
        path = _scan().get(intent)
    if path is None:
        return None
    try:
        message = Message()
        message.append(_image_segment(path))
        return message
    except OSError as exc:
        logger.warning(f"表情图片读取失败：{path.name}（{exc}）")
        return None


def _append_text(parts: list, content: str) -> None:
    """把文本片段并入 parts，与相邻文本段合并；纯空白不产生消息元素。"""
    if not content.strip():
        return
    if parts and isinstance(parts[-1], TextPart):
        parts[-1] = TextPart(content=parts[-1].content + content)
    else:
        parts.append(TextPart(content=content))


def tags_to_plan(text: str) -> ChatPlan:
    """把含 [表情:名称] 标签的调试文本组装为表达计划，供 <echo> 复用渲染管线。

    能解析到图片的标签转为 sticker 段（名称检索仍由应用层负责），未知标签按原文保留。
    """
    table = _scan()
    parts: list = []
    pos = 0
    for match in TAG_PATTERN.finditer(text):
        _append_text(parts, text[pos : match.start()])
        name = match.group(1)
        if name in table:
            parts.append(StickerPart(intent=name))
        else:
            _append_text(parts, match.group(0))
        pos = match.end()
    _append_text(parts, text[pos:])
    if not parts:
        parts.append(TextPart(content=text))
    return ChatPlan(parts=tuple(parts))


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
