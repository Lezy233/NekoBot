"""事件处理链路的端到端测试：mock Bot/事件/matcher/store/llm，验证分条发送行为。"""

import asyncio
import unittest
from dataclasses import replace
from unittest import mock

from nonebot.adapters.onebot.v11 import Message
from nonebot.exception import FinishedException

import plugins.chat as chat
from plugins.chat import debug

DEMO_RESPONSE = (
    '{"messages":[{"type":"text","content":"A"},'
    '{"type":"text","content":"B"},'
    '{"type":"text","content":"C"}]}'
)
ADMIN_ID = "42"


class HandlerFlowTest(unittest.TestCase):
    def setUp(self):
        debug._active.add(ADMIN_ID)
        self.addCleanup(debug._active.discard, ADMIN_ID)

    def _run_handler(self, user_text: str, llm_response: str = DEMO_RESPONSE):
        """以管理员私聊身份跑一遍 handle_private_message，返回 (send, finish, append) mock。"""
        event = mock.Mock()
        event.message_type = "private"
        event.user_id = 42
        event.get_user_id = lambda: ADMIN_ID
        event.get_message = lambda: Message(user_text)
        bot = mock.Mock()
        bot.self_id = "999"

        send_mock = mock.AsyncMock()
        # 真实 finish 通过抛出 FinishedException 终止 handler 流程，mock 必须复现这一点，
        # 否则管理员分支执行完后流程会继续走进 LLM 主流程。
        finish_mock = mock.AsyncMock(side_effect=FinishedException())
        append_mock = mock.Mock()
        llm_mock = mock.AsyncMock(return_value=llm_response)

        with (
            mock.patch.object(chat, "settings", replace(chat.settings, admin_users=frozenset({ADMIN_ID}))),
            mock.patch.object(chat.store, "append", append_mock),
            mock.patch.object(chat.store, "get_summary", return_value=""),
            mock.patch.object(chat.store, "get_recent", return_value=[]),
            mock.patch.object(chat.compress, "maybe_compress", new=mock.AsyncMock()),
            mock.patch.object(chat.llm, "chat", llm_mock),
            mock.patch.object(chat.random, "uniform", return_value=0),
            mock.patch.object(chat.matcher, "send", send_mock),
            mock.patch.object(chat.matcher, "finish", finish_mock),
        ):
            try:
                asyncio.run(chat.handle_chat_message(bot=bot, event=event))
            except FinishedException:
                pass  # 真实 finish 的正常终止方式
        return send_mock, finish_mock, append_mock, llm_mock

    def test_echo_json_plan_sends_three_separate_messages(self):
        send, finish, append, llm = self._run_handler(f"<echo> {DEMO_RESPONSE}")
        self.assertEqual(send.call_count, 3)
        sent = [str(call.args[0]) for call in send.call_args_list]
        self.assertEqual(sent, ["A", "B", "C"])
        # 调试指令不应触发 LLM，也不应走 finish。
        llm.assert_not_called()
        finish.assert_not_called()
        # 不应触发聊天主流程的历史写入（echo 不是对话）。
        append.assert_not_called()

    def test_emoji_single_message_not_split_into_segments(self):
        """Message 是 list 子类：返回单个 Message 的指令必须整走 finish，不能被拆段。"""
        send, finish, _append, _llm = self._run_handler('<emoji> "Pool Tom"')
        send.assert_not_called()
        finish.assert_called_once()
        reply = finish.call_args.args[0]
        self.assertIsInstance(reply, Message)
        self.assertEqual([seg.type for seg in reply], ["image"])

    def test_ai_reply_sends_three_separate_messages(self):
        """非指令的管理员消息走 LLM 主流程，三条短句必须分三条发送。"""
        send, finish, append, llm = self._run_handler("随便聊聊", llm_response=DEMO_RESPONSE)
        llm.assert_called_once()
        self.assertEqual(send.call_count, 3)
        sent = [str(call.args[0]) for call in send.call_args_list]
        self.assertEqual(sent, ["A", "B", "C"])
        finish.assert_not_called()
        # assistant 历史写入规范化文本，而不是原始 JSON。
        assistant_writes = [
            call.args for call in append.call_args_list if call.args[1] == "assistant"
        ]
        self.assertEqual(assistant_writes, [("private:42", "assistant", "A\nB\nC")])

    def test_ai_single_text_reply_sends_one_message(self):
        send, _finish, _append, _llm = self._run_handler(
            "你好", llm_response='{"messages":[{"type":"text","content":"只回一句"}]}'
        )
        self.assertEqual(send.call_count, 1)
        self.assertEqual(str(send.call_args.args[0]), "只回一句")


if __name__ == "__main__":
    unittest.main()
