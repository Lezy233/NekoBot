"""LLM 表达计划的解析与规范化（纯标准库，无第三方依赖）。

LLM 不直接输出 QQ 正文，而是输出一份 JSON 表达计划：

    {"messages": [
        {"type": "text", "content": "还没睡"},
        {"type": "sticker", "intent": "speechless"},
        {"type": "text", "content": "有事说事"},
    ]}

本模块是确定性的应用层边界：校验结构、拒绝非法计划、把计划规范化
为可写入历史的文本；任何情况下都不把内部 JSON 泄漏给 QQ 或会话历史。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Union

ALLOWED_INTENTS: tuple[str, ...] = ("happy", "speechless", "angry", "shy", "comfort", "awkward")

MAX_PARTS = 3
MAX_STICKERS = 1

# 模型偶发输出的角色前缀，应用层负责剥掉。
ROLE_PREFIX_PATTERN = re.compile(r"^\s*角色\s*[:：]\s*")

# 兼容模型偶发包裹的一对 ```json ... ``` 围栏；协议本身仍要求不输出围栏。
FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL)

# 模型不可用时的单条安全兜底文本。
FALLBACK_TEXT = "……让我组织一下语言，稍等一下。"


class PlanError(ValueError):
    """表达计划不合法。消息中只包含结构原因，不携带 LLM 原始正文。"""


@dataclass(frozen=True)
class TextPart:
    """一条纯文本消息。"""

    content: str


@dataclass(frozen=True)
class StickerPart:
    """一条表情消息，只携带表达意图，由应用层检索真实图片。"""

    intent: str


PlanPart = Union[TextPart, StickerPart]


@dataclass(frozen=True)
class ChatPlan:
    """一份有序的表达计划。

    私聊场景 parts 非空且长度不超过 MAX_PARTS；群聊场景允许空 parts（不参与话题）。
    """

    parts: tuple[PlanPart, ...]


def _clean_text(content: str) -> str:
    """去掉开头偶发的「角色：」前缀。"""
    return ROLE_PREFIX_PATTERN.sub("", content).strip()


def _unwrap_fence(raw: str) -> str:
    """剥掉模型偶发包裹的一对 json 代码围栏。"""
    match = FENCE_PATTERN.match(raw)
    if match:
        return match.group("body").strip()
    return raw


def _validate(data: object, allow_empty: bool = False) -> ChatPlan:
    if not isinstance(data, dict):
        raise PlanError("计划必须是 JSON 对象")
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise PlanError("计划缺少 messages 数组")
    if not messages:
        if allow_empty:
            # 群聊场景允许空计划，表示模型判断不参与本次话题。
            return ChatPlan(parts=())
        raise PlanError("messages 不能为空")
    if len(messages) > MAX_PARTS:
        raise PlanError(f"messages 必须有 1～{MAX_PARTS} 个元素")

    parts: list[PlanPart] = []
    sticker_count = 0
    for index, item in enumerate(messages):
        if not isinstance(item, dict):
            raise PlanError(f"messages[{index}] 必须是对象")
        kind = item.get("type")
        if kind == "text":
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                raise PlanError(f"messages[{index}] 的 text.content 必须是非空字符串")
            parts.append(TextPart(content=_clean_text(content)))
        elif kind == "sticker":
            intent = item.get("intent")
            if intent not in ALLOWED_INTENTS:
                raise PlanError(f"messages[{index}] 的 sticker.intent 不在允许列表内")
            sticker_count += 1
            if sticker_count > MAX_STICKERS:
                raise PlanError("一次回复最多使用一个 sticker")
            parts.append(StickerPart(intent=intent))
        else:
            raise PlanError(f"messages[{index}] 的 type 必须是 text 或 sticker")
    return ChatPlan(parts=tuple(parts))


def parse_plan(raw: str, *, allow_empty: bool = False) -> ChatPlan:
    """把 LLM 原始输出解析为 ChatPlan。

    - 合法 JSON 但结构非法时抛出 PlanError（不携带原始正文）。
    - 完全不符合 JSON 且以 { 或 [ 开头的损坏响应抛出 PlanError，
      调用方不得把这类原文发给用户。
    - 其余普通自然语言按兼容处理：返回单条文本计划。
    - allow_empty=True（群聊）时接受 {"messages":[]} 空计划，表示不发言。
    """
    text = _unwrap_fence(raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        if text.startswith(("{", "[")):
            raise PlanError("响应以 { 或 [ 开头但不是合法 JSON") from exc
        cleaned = _clean_text(text)
        if not cleaned:
            raise PlanError("响应为空") from exc
        return ChatPlan(parts=(TextPart(content=cleaned),))
    return _validate(data, allow_empty=allow_empty)


def safe_plan(raw: str) -> ChatPlan:
    """parse_plan 的非抛出版本：损坏输入回退为单条安全兜底文本。"""
    try:
        return parse_plan(raw)
    except PlanError:
        return ChatPlan(parts=(TextPart(content=FALLBACK_TEXT),))


def plan_to_transcript(plan: ChatPlan) -> str:
    """把计划规范化为写入会话历史的文本：文本段写正文，表情段写 [表情:intent]。"""
    lines: list[str] = []
    for part in plan.parts:
        if isinstance(part, TextPart):
            lines.append(part.content)
        else:
            lines.append(f"[表情:{part.intent}]")
    return "\n".join(lines)


def output_protocol_prompt() -> str:
    """生成注入给 LLM 的固定输出协议说明，由代码统一维护。"""
    intents = "、".join(ALLOWED_INTENTS)
    return (
        "你的回复必须是一个 JSON 表达计划，格式如下：\n"
        '{"messages":[{"type":"text","content":"还没睡"},'
        '{"type":"sticker","intent":"speechless"},'
        '{"type":"text","content":"有事说事"}]}\n'
        "要求：\n"
        "- messages 包含 1～3 个有序元素，每个元素是一条待发送的消息，按顺序逐条发送。\n"
        '- type 只能是 "text" 或 "sticker"。\n'
        "- text 元素的 content 必须是非空字符串。\n"
        "- sticker 元素的 intent 只能是：" + intents + "。\n"
        "- 每次回复最多使用一个 sticker。\n"
        "- 情绪明显的场景优先用 sticker 表达：吐槽、得意、无语、发火、害羞、安慰时随手带一张，"
        "熟人闲聊时多数回复都可以带一个 sticker，它是你的日常表达方式而不是稀有装饰。\n"
        "- sticker 只写 intent，不要写文件名、路径、URL 或 CQ 码；应用层会检索真实图片，"
        "找不到时会丢弃该表情。\n"
        "- 空行没有分条语义；需要分条时拆成多个 messages 元素。\n"
        "- 只输出 JSON 本身：不要 Markdown 代码围栏，不要解释，不要角色前缀。\n"
        "- 闲聊短句可以省略句末句号。"
    )
