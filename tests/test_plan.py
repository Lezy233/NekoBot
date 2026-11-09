"""表达计划解析模块的验收测试（不访问真实 QQ / DeepSeek / chat.db）。"""

import unittest

from plugins.chat import plan


DEMO_RESPONSE = (
    '{"messages":[{"type":"text","content":"还没睡"},'
    '{"type":"sticker","intent":"speechless"},'
    '{"type":"text","content":"有事说事"}]}'
)


class ParsePlanTest(unittest.TestCase):
    def test_valid_plan_parses_to_three_ordered_parts(self):
        chat_plan = plan.parse_plan(DEMO_RESPONSE)
        self.assertEqual(len(chat_plan.parts), 3)
        first, second, third = chat_plan.parts
        self.assertIsInstance(first, plan.TextPart)
        self.assertEqual(first.content, "还没睡")
        self.assertIsInstance(second, plan.StickerPart)
        self.assertEqual(second.intent, "speechless")
        self.assertIsInstance(third, plan.TextPart)
        self.assertEqual(third.content, "有事说事")

    def test_transcript_normalizes_sticker_without_json(self):
        chat_plan = plan.parse_plan(DEMO_RESPONSE)
        transcript = plan.plan_to_transcript(chat_plan)
        self.assertEqual(transcript, "还没睡\n[表情:speechless]\n有事说事")
        self.assertNotIn("{", transcript)
        self.assertNotIn("}", transcript)
        self.assertNotIn('"type"', transcript)

    def test_empty_messages_rejected(self):
        with self.assertRaises(plan.PlanError):
            plan.parse_plan('{"messages":[]}')

    def test_more_than_three_parts_rejected(self):
        items = ",".join('{"type":"text","content":"x"}' for _ in range(4))
        with self.assertRaises(plan.PlanError):
            plan.parse_plan(f'{{"messages":[{items}]}}')

    def test_two_stickers_rejected(self):
        raw = (
            '{"messages":[{"type":"sticker","intent":"happy"},'
            '{"type":"sticker","intent":"angry"}]}'
        )
        with self.assertRaises(plan.PlanError):
            plan.parse_plan(raw)

    def test_empty_text_content_rejected(self):
        with self.assertRaises(plan.PlanError):
            plan.parse_plan('{"messages":[{"type":"text","content":"  "}]}')

    def test_unknown_intent_rejected(self):
        raw = '{"messages":[{"type":"sticker","intent":"dance"}]}'
        with self.assertRaises(plan.PlanError):
            plan.parse_plan(raw)

    def test_unknown_type_rejected(self):
        with self.assertRaises(plan.PlanError):
            plan.parse_plan('{"messages":[{"type":"image","path":"a.png"}]}')

    def test_json_code_fence_is_tolerated(self):
        raw = "```json\n" + DEMO_RESPONSE + "\n```"
        chat_plan = plan.parse_plan(raw)
        self.assertEqual(len(chat_plan.parts), 3)
        self.assertEqual(plan.plan_to_transcript(chat_plan), "还没睡\n[表情:speechless]\n有事说事")

    def test_role_prefix_is_stripped(self):
        raw = '{"messages":[{"type":"text","content":"角色：还没睡"}]}'
        chat_plan = plan.parse_plan(raw)
        self.assertEqual(chat_plan.parts[0].content, "还没睡")

    def test_plain_natural_language_falls_back_to_single_text(self):
        chat_plan = plan.parse_plan("还没睡，怎么了？")
        self.assertEqual(len(chat_plan.parts), 1)
        self.assertEqual(chat_plan.parts[0].content, "还没睡，怎么了？")


class BrokenResponseTest(unittest.TestCase):
    def test_broken_json_raises_plan_error(self):
        with self.assertRaises(plan.PlanError):
            plan.parse_plan('{"messages":[')

    def test_safe_plan_never_leaks_raw_json(self):
        chat_plan = plan.safe_plan('{"messages":[')
        transcript = plan.plan_to_transcript(chat_plan)
        self.assertNotIn("{", transcript)
        self.assertNotIn('"messages"', transcript)
        self.assertTrue(transcript.strip())

    def test_safe_plan_keeps_valid_plan(self):
        chat_plan = plan.safe_plan(DEMO_RESPONSE)
        self.assertEqual(len(chat_plan.parts), 3)


class ProtocolPromptTest(unittest.TestCase):
    def test_protocol_mentions_intents_and_rules(self):
        prompt = plan.output_protocol_prompt()
        for intent in plan.ALLOWED_INTENTS:
            self.assertIn(intent, prompt)
        self.assertIn('"type":"sticker"', prompt)
        self.assertIn("代码围栏", prompt)
        self.assertIn("角色前缀", prompt)
        self.assertIn("最多使用一个 sticker", prompt)
        self.assertIn("省略句末句号", prompt)


if __name__ == "__main__":
    unittest.main()
