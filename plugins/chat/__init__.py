"""DeepSeek 私聊聊天插件。"""

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from . import compress, debug, llm, sticker, store
from .config import settings
from .overrides import get_override
from .persona import load_persona

matcher = on_message()


def build_messages(session_key: str, current_message: str) -> list[dict[str, str]]:
    """组装人格、会话级注入、历史摘要、滑动历史窗口和当前用户消息。"""
    messages: list[dict[str, str]] = [{"role": "system", "content": load_persona()}]
    override = get_override(session_key)
    if override:
        messages.append({"role": "system", "content": override})
    sticker_prompt = sticker.available_prompt()
    if sticker_prompt:
        messages.append({"role": "system", "content": sticker_prompt})
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


@matcher.handle()
async def handle_private_message(bot: Bot, event: MessageEvent) -> None:
    """只处理私聊用户消息，并把回复写回会话历史。"""
    if event.message_type != "private":
        return
    if str(event.get_user_id()) == str(bot.self_id):
        return

    user_id = getattr(event, "user_id", event.get_user_id())
    session_key = f"private:{user_id}"
    user_message = str(event.get_message()).strip()
    if not user_message:
        return

    user_id_str = str(user_id)
    if user_id_str in settings.admin_users:
        reply = await debug.handle(user_id_str, session_key, user_message)
        if reply is not None:
            await matcher.finish(reply)

    store.append(session_key, "user", user_message)
    await compress.maybe_compress(session_key)
    messages = build_messages(session_key, user_message)
    response = await llm.chat(messages)
    store.append(session_key, "assistant", response)
    await matcher.finish(sticker.parse(response))

