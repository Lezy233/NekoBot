"""群聊功能的验收测试：白名单、参与判断（空计划跳过）、管理员调试不受白名单限制。"""

import asyncio
import unittest
from dataclasses import replace
from unittest import mock

from nonebot.adapters.onebot.v11 import Message
from nonebot.exception import FinishedException

import plugins.chat as chat
from plugins.chat import debug, plan

DEMO_RESPONSE = (
    '{"messages":[{"type":"text","content":"这话题我有兴趣"},'
    '{"type":"text","content":"插一句"}]}'
)
EMPTY_PLAN = '{"messages":[]}'
GROUP_ID = 888
SESSION_KEY = f"group:{GROUP_ID}"


class EmptyPlanTest(unittest.TestCase):
    def test_empty_plan_allowed_in_group_mode(self):
        chat_plan = plan.parse_plan(EMPTY_PLAN, allow_empty=True)
        self.assertEqual(chat_plan.parts, ())
        self.assertEqual(plan.plan_to_transcript(chat_plan), "")

    def test_empty_plan_rejected_by_default(self):
        with self.assertRaises(plan.PlanError):
            plan.parse_plan(EMPTY_PLAN)


class GroupHandlerFlowTest(unittest.TestCase):
    def _run_handler(self, text: str, *, whitelisted: bool, llm_response: str = DEMO_RESPONSE, user_id: int = 7):
        event = mock.Mock()
        event.message_type = "group"
        event.group_id = GROUP_ID
        event.user_id = user_id
        event.get_user_id = lambda: str(user_id)
        event.get_message = lambda: Message(text)
        event.sender = mock.Mock(card="", nickname="阿明")
        bot = mock.Mock()
        bot.self_id = "999"

        send_mock = mock.AsyncMock()
        finish_mock = mock.AsyncMock(side_effect=FinishedException())
        llm_mock = mock.AsyncMock(return_value=llm_response)
        append_mock = mock.Mock()

        with (
            mock.patch.object(chat, "settings", replace(chat.settings, admin_users=frozenset({"42"}))),
            mock.patch.object(chat, "has_entry", return_value=whitelisted),
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
                pass
        return send_mock, finish_mock, llm_mock, append_mock

    def test_non_whitelisted_group_is_ignored(self):
        send, _finish, llm, append = self._run_handler("今天天气不错", whitelisted=False)
        llm.assert_not_called()
        send.assert_not_called()
        append.assert_not_called()

    def test_whitelisted_group_participates(self):
        send, _finish, llm, append = self._run_handler("今天天气不错", whitelisted=True)
        llm.assert_called_once()
        self.assertEqual(send.call_count, 2)
        sent = [str(c.args[0]) for c in send.call_args_list]
        self.assertEqual(sent, ["这话题我有兴趣", "插一句"])
        # 历史按群会话写入，用户消息带发送者前缀，assistant 写规范化文本。
        user_writes = [c.args for c in append.call_args_list if c.args[1] == "user"]
        self.assertEqual(user_writes, [(SESSION_KEY, "user", "阿明（7）：今天天气不错")])
        assistant_writes = [c.args for c in append.call_args_list if c.args[1] == "assistant"]
        self.assertEqual(assistant_writes, [(SESSION_KEY, "assistant", "这话题我有兴趣\n插一句")])
        # 群聊协议中包含参与判断说明。
        contents = [m["content"] for m in llm.call_args.args[0]]
        self.assertTrue(any("保持沉默" in str(c) for c in contents))

    def test_empty_plan_means_silence(self):
        send, _finish, llm, append = self._run_handler(
            "今天天气不错", whitelisted=True, llm_response=EMPTY_PLAN
        )
        llm.assert_called_once()
        send.assert_not_called()
        # 不发言时不写 assistant 历史，但用户消息仍入库。
        roles = [c.args[1] for c in append.call_args_list]
        self.assertEqual(roles, ["user"])

    def test_broken_json_in_group_falls_silent(self):
        send, _finish, llm, append = self._run_handler(
            "今天天气不错", whitelisted=True, llm_response='{"messages":['
        )
        llm.assert_called_once()
        send.assert_not_called()
        roles = [c.args[1] for c in append.call_args_list]
        self.assertEqual(roles, ["user"])

    def test_admin_debug_works_in_non_whitelisted_group(self):
        debug._active.add("42")  # 管理员先进入 <admin> 模式
        self.addCleanup(debug._active.discard, "42")
        send, finish, llm, append = self._run_handler(
            "<echo> 你好", whitelisted=False, user_id=42
        )
        llm.assert_not_called()
        append.assert_not_called()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(str(send.call_args.args[0]), "你好")
        finish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
