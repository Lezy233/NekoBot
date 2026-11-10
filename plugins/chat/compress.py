"""会话历史的上下文压缩。"""

from __future__ import annotations

import re

from nonebot import logger

from . import llm, store
from .config import settings

FILLER_MESSAGES = {"嗯", "哦", "啊", "呃", "草", "6", "?", "？", "!", "！"}
MEDIA_PATTERN = re.compile(r"(\[表情:[^\[\]]+\]|\[图片\]|\[CQ:[^\]]+\])")


def _is_meaningless(content: str) -> bool:
    """语气词、纯标点等不携带信息的消息。"""
    if content in FILLER_MESSAGES:
        return True
    return len(content) <= 3 and not re.search(r"[0-9A-Za-z一-鿿]", content)


def _preprocess(candidates: list[dict]) -> list[dict[str, str]]:
    """压缩前本地折叠低信息量消息，减少摘要接口的输入 token。

    - 同一发送者连续重复的消息折叠为「连发N次」；
    - 连续的纯表情/图片消息折叠为一条计数记录；
    - 语气词与纯标点消息直接丢弃。
    折叠只影响摘要输入，原始消息与压缩水位线不受影响。
    """
    entries: list[dict] = []
    for msg in candidates:
        role = msg["role"]
        content = msg["content"].strip()
        if not content or _is_meaningless(content):
            continue
        if not MEDIA_PATTERN.sub("", content).strip():
            kind, text = "media", ""
        else:
            kind, text = "text", content
        last = entries[-1] if entries else None
        if last and last["role"] == role and last["kind"] == kind and last["content"] == text:
            last["count"] += 1
        else:
            entries.append({"role": role, "kind": kind, "content": text, "count": 1})

    result: list[dict[str, str]] = []
    for entry in entries:
        count = entry["count"]
        if entry["kind"] == "media":
            text = f"发送了{count}条纯表情/图片消息"
        elif count > 1:
            text = f"连发{count}次「{entry['content']}」"
        else:
            text = entry["content"]
        result.append({"role": entry["role"], "content": text})
    return result


async def maybe_compress(session_key: str) -> None:
    """历史超过阈值时，把滑动窗口之外的消息批量压缩为摘要。

    窗口外的消息攒够一个窗口大小才压缩一批，避免每条消息都调一次摘要接口。
    摘要生成失败时跳过本次压缩，不影响正常聊天。
    """
    if store.count_messages(session_key) <= settings.compress_threshold:
        return
    candidates = store.get_compressible(session_key, settings.history_limit)
    if len(candidates) < settings.history_limit:
        return
    existing = store.get_summary(session_key)
    try:
        summary = await llm.summarize(existing, _preprocess(candidates))
    except Exception as exc:
        logger.warning(f"会话摘要生成失败，本次跳过压缩：{exc}")
        return
    store.save_summary(session_key, summary, candidates[-1]["id"])
    logger.info(f"会话 {session_key} 已压缩 {len(candidates)} 条历史消息")
