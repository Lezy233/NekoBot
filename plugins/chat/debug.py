"""管理员调试模式与指令框架。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from nonebot.adapters.onebot.v11 import Message

from . import compress, sticker, store
from .persona import load_persona

Command = Callable[[str, str], Awaitable[Message | str]]

_active: set[str] = set()
_commands: dict[str, Command] = {}
COMMAND_PATTERN = re.compile(r"^<([a-zA-Z]+)>\s*(.*)$", re.DOTALL)

ENTER_MODE = "<admin>"
EXIT_MODE = "</admin>"


def command(name: str) -> Callable[[Command], Command]:
    """注册调试指令，name 为尖括号内的英文指令名。"""

    def register(func: Command) -> Command:
        _commands[name] = func
        return func

    return register


async def handle(user_id: str, session_key: str, text: str) -> Message | str | None:
    """处理管理员消息；返回 None 表示按普通聊天流程处理。

    <admin> / </admin> 控制模式开关；模式内识别 <指令> 格式，
    非指令文本（不匹配 <...> 格式）仍走正常聊天。
    """
    if text == ENTER_MODE:
        if user_id in _active:
            return "已在管理员模式"
        _active.add(user_id)
        return "已进入管理员模式，输入 <help> 查看可用指令"
    if text == EXIT_MODE:
        if user_id not in _active:
            return "当前不在管理员模式"
        _active.discard(user_id)
        return "已退出管理员模式"
    if user_id not in _active:
        return None

    match = COMMAND_PATTERN.match(text)
    if match is None:
        return None
    name, arg = match.group(1), match.group(2).strip()
    handler = _commands.get(name)
    if handler is None:
        return f"未知指令 <{name}>，输入 <help> 查看可用指令"
    try:
        return await handler(session_key, arg)
    except Exception as exc:  # 调试指令失败不应影响聊天流程
        return f"指令 <{name}> 执行失败：{exc}"


@command("help")
async def cmd_help(session_key: str, arg: str) -> str:
    lines = [f"<{name}>" for name in sorted(_commands)]
    return "可用指令：" + "、".join(lines)


@command("emoji")
async def cmd_emoji(session_key: str, arg: str) -> Message | str:
    """<emoji> 名称 — 直接发送指定表情包（支持引号包裹或 目录/名称 形式）。

    <emoji> ls [目录] — 列出目录内容；目录名含空格时用 \\ 转义或不加引号整体输入。
    """
    arg = arg.strip()
    if arg == "ls" or arg.startswith("ls "):
        rel = arg[2:].strip().replace("\\ ", " ").strip('"').strip('"').strip("'")
        listing = sticker.list_dir(rel)
        if listing is None:
            return f"目录不存在：{rel or '(根目录)'}"
        return listing
    name = arg.strip('"').strip('"').strip("'").strip()
    if not name:
        return '用法：<emoji> "表情名称" 或 <emoji> ls [目录]'
    message = sticker.render(name)
    if message is None:
        return f"未找到表情「{name}」"
    return message


@command("compact")
async def cmd_compact(session_key: str, arg: str) -> str:
    """<compact> — 立即对当前会话触发上下文压缩。"""
    before = store.get_summary(session_key)
    await compress.maybe_compress(session_key)
    after = store.get_summary(session_key)
    if after == before:
        return f"未触发压缩（当前 {store.count_messages(session_key)} 条历史）"
    return f"已压缩，当前摘要：\n{after}"


@command("persona")
async def cmd_persona(session_key: str, arg: str) -> str:
    """<persona> — 查看当前加载的人格（前 80 字）。"""
    text = load_persona()
    return f"人格已加载，长度 {len(text)}：\n{text[:80]}"


@command("history")
async def cmd_history(session_key: str, arg: str) -> str:
    """<history> — 查看当前会话历史条数与摘要状态。"""
    summary = store.get_summary(session_key)
    state = f"已有摘要（{len(summary)} 字）" if summary else "无摘要"
    return f"当前会话共 {store.count_messages(session_key)} 条历史，{state}"
