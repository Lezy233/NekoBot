"""聊天主流程的验收测试：build_messages / render_plan / 兜底，不访问真实 QQ / DeepSeek / chat.db。"""

import unittest
from unittest import mock

from nonebot.adapters.onebot.v11 import MessageSegment

import plugins.chat as chat_plugin
from plugins.chat import plan

DEMO_RESPONSE = (
    '{"messages":[{"type":"text","content":"还没睡"},'
    '{"type":"sticker","intent":"speechless"},'
    '{"type":"text","content":"有事说事"}]}'
)
EXPECTED_TRANSCRIPT = "还没睡\n[表情:speechless]\n有事说事"


class BuildMessagesTest(unittest.TestCase):
    def _build(self):
        with (
            mock.patch.object(chat_plugin.store, "get_summary", return_value=""),
            mock.patch.object(chat_plugin.store, "get_recent", return_value=[]),
        ):
            return chat_plugin.build_messages("private:tester", "在吗")

    def test_no_sticker_filename_dump_in_messages(self):
        messages = self._build()
        combined = "\n".join(m["content"] for m in messages)
        # 不再注入整库表情文件名（真实库中的文件名不应出现在任何消息里）。
        for filename in ("😳.png", "😂👉.jpg", "Tom 跺步", "Jerry Laugh", "花香蕉的钱只能请到猴子"):
            self.assertNotIn(filename, combined)
        self.assertNotIn("可用的表情包名称", combined)

    def test_output_protocol_is_injected(self):
        messages = self._build()
        protocol = plan.output_protocol_prompt()
        self.assertIn({"role": "system", "content": protocol}, messages)
        combined = "\n".join(m["content"] for m in messages)
        for intent in plan.ALLOWED_INTENTS:
            self.assertIn(intent, combined)

    def test_message_order_persona_protocol_user(self):
        messages = self._build()
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1], {"role": "user", "content": "在吗"})
        self.assertEqual(messages[1]["content"], plan.output_protocol_prompt())

    def test_history_and_summary_kept(self):
        history = [{"role": "user", "content": "早"}, {"role": "assistant", "content": "早呀"}]
        with (
            mock.patch.object(chat_plugin.store, "get_summary", return_value="摘要在逃"),
            mock.patch.object(chat_plugin.store, "get_recent", return_value=history),
        ):
            messages = chat_plugin.build_messages("private:tester", "在吗")
        roles = [m["role"] for m in messages]
        self.assertEqual(roles.count("user"), 2)  # 历史 1 条 + 当前消息
        self.assertTrue(any("摘要在逃" in m["content"] for m in messages))


class RenderPlanTest(unittest.TestCase):
    def test_demo_plan_renders_text_image_text(self):
        chat_plan = plan.parse_plan(DEMO_RESPONSE)
        with mock.patch.object(chat_plugin.sticker, "resolve_sticker") as resolve:
            resolve.return_value = chat_plugin.Message(MessageSegment.image(b"fake"))
            replies = chat_plugin.render_plan(chat_plan)
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0][0].type, "text")
        self.assertEqual(str(replies[0]), "还没睡")
        self.assertEqual(replies[1][0].type, "image")
        self.assertEqual(str(replies[2]), "有事说事")
        resolve.assert_called_once_with("speechless")

    def test_missing_sticker_drops_to_two_texts(self):
        chat_plan = plan.parse_plan(DEMO_RESPONSE)
        with mock.patch.object(chat_plugin.sticker, "resolve_sticker", return_value=None):
            replies = chat_plugin.render_plan(chat_plan)
        self.assertEqual(len(replies), 2)
        self.assertEqual([str(m) for m in replies], ["还没睡", "有事说事"])
        for message in replies:
            self.assertNotIn("[表情:", str(message))

    def test_empty_render_falls_back_to_safe_text(self):
        chat_plan = plan.ChatPlan(parts=(plan.StickerPart(intent="happy"),))
        with mock.patch.object(chat_plugin.sticker, "resolve_sticker", return_value=None):
            replies = chat_plugin.render_plan(chat_plan)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][0].type, "text")
        self.assertTrue(str(replies[0]).strip())


class BrokenResponseFlowTest(unittest.TestCase):
    def test_broken_response_never_reaches_user_or_history(self):
        chat_plan = chat_plugin.coerce_plan('{"messages":[')
        transcript = plan.plan_to_transcript(chat_plan)
        replies = chat_plugin.render_plan(chat_plan)
        self.assertNotIn("{", transcript)
        self.assertNotIn('"messages"', transcript)
        self.assertEqual(len(replies), 1)
        self.assertNotIn("{", str(replies[0]))
        self.assertNotIn("[表情:", str(replies[0]))

    def test_valid_response_transcript_is_normalized(self):
        chat_plan = chat_plugin.coerce_plan(DEMO_RESPONSE)
        self.assertEqual(plan.plan_to_transcript(chat_plan), EXPECTED_TRANSCRIPT)

    def test_transcript_uses_intent_not_filename(self):
        chat_plan = chat_plugin.coerce_plan(DEMO_RESPONSE)
        transcript = plan.plan_to_transcript(chat_plan)
        self.assertIn("[表情:speechless]", transcript)
        for filename in (".png", ".jpg", ".webp", "emoji/"):
            self.assertNotIn(filename, transcript)


if __name__ == "__main__":
    unittest.main()
