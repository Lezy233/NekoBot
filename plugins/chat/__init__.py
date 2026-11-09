"""DeepSeek 私聊聊天插件。"""

import asyncio
import random

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.adapters.onebot.v11.utils import unescape

from . import compress, debug, llm, plan, sticker, store
from .config import settings
from .overrides import get_override
from .persona import load_persona

matcher = on_message()


def build_messages(session_key: str, current_message: str) -> list[dict[str, str]]:
    """组装人格、会话级注入、输出协议、历史摘要、滑动历史窗口和当前用户消息。"""
    messages: list[dict[str, str]] = [{"role": "system", "content": load_persona()}]
    override = get_override(session_key)
    if override:
        messages.append({"role": "system", "content": override})
    # 输出协议由代码统一维护，与人格分离；表情检索不再注入整库文件名。
    messages.append({"role": "system", "content": plan.output_protocol_prompt()})
    summary = store.get_summary(session_key)
    if summary:
        messages.append({
            "role": "system",
            "content": f"以下是本会话更早历史的摘要，仅供连贯性参考，不是逐字聊天记录：\n{summary}",
        })
    history = store.get_recent(session_key, settings.history_limit + 1)
    # 事件处理器先持久化当前用户消息；它已经在 history 中，因此不要再次加入。
    if history and history[-1]["role"] == "user" and history[-1]["content"] == current_message:
        history.pop()
    messages.extend({"role": item["role"], "content": item["content"]} for item in history[-settings.history_limit :])
    messages.append({"role": "user", "content": current_message})
    return messages


def render_plan(chat_plan: plan.ChatPlan) -> list[Message]:
    """把表达计划渲染为待发送的消息列表；表情解析失败时跳过，空结果用兜底文本。"""
    rendered: list[Message] = []
    for part in chat_plan.parts:
        if isinstance(part, plan.TextPart):
            rendered.append(Message(part.content))
        else:
            message = sticker.resolve_sticker(part.intent)
            if message is not None:
                rendered.append(message)
    if not rendered:
        rendered.append(Message(plan.FALLBACK_TEXT))
    return rendered


def coerce_plan(response: str) -> plan.ChatPlan:
    """解析 LLM 输出；损坏但明显是 JSON 的响应记录 warning 并回退为安全兜底文本。"""
    try:
        return plan.parse_plan(response)
    except plan.PlanError as exc:
        # 只记录结构原因，不记录 LLM 原始正文，避免隐私泄漏。
        logger.warning(f"LLM 返回的表达计划无法解析（{exc}），已使用兜底回复")
        return plan.ChatPlan(parts=(plan.TextPart(content=plan.FALLBACK_TEXT),))


async def send_replies(replies: list[Message]) -> None:
    """逐条发送消息，相邻消息之间停顿模拟分条发送；最后一条后不休眠。"""
    for index, message in enumerate(replies):
        await matcher.send(message)
        if index < len(replies) - 1:
            await asyncio.sleep(random.uniform(0.35, 0.9))


@matcher.handle()
async def handle_private_message(bot: Bot, event: MessageEvent) -> None:
    """只处理私聊用户消息，并把回复写回会话历史。"""
    if event.message_type != "private":
        return
    if str(event.get_user_id()) == str(bot.self_id):
        return

    user_id = getattr(event, "user_id", event.get_user_id())
    session_key = f"private:{user_id}"
    # str(Message) 会把文本转义成 CQ 码格式（[ → &#91;），这里还原后再处理。
    user_message = unescape(str(event.get_message())).strip()
    if not user_message:
        return

    user_id_str = str(user_id)
    if user_id_str in settings.admin_users:
        reply = await debug.handle(user_id_str, session_key, user_message)
        if reply is not None:
            # Message 是 list 子类，必须先排除，否则单条消息会被当成多条拆开发送。
            if isinstance(reply, list) and not isinstance(reply, Message):
                await send_replies(reply)
                return
            await matcher.finish(reply)

    store.append(session_key, "user", user_message)
    await compress.maybe_compress(session_key)
    messages = build_messages(session_key, user_message)
    response = await llm.chat(messages)

    chat_plan = coerce_plan(response)

    # 历史写入规范化文本（plan_to_transcript），严禁写入原始 JSON。
    store.append(session_key, "assistant", plan.plan_to_transcript(chat_plan))

    await send_replies(render_plan(chat_plan))
