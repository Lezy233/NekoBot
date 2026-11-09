"""<echo> 调试指令的验收测试：验证它复用与 AI 回复相同的表达计划渲染管线。"""

import asyncio
import unittest

from nonebot.adapters.onebot.v11 import Message
from nonebot.adapters.onebot.v11.utils import unescape

from plugins.chat import debug, sticker
from plugins.chat.plan import StickerPart, TextPart


def _as_list(result) -> list[Message]:
    return result if isinstance(result, list) else [result]


class EchoCommandTest(unittest.TestCase):
    def setUp(self):
        debug._active.add("tester")
        self.addCleanup(debug._active.discard, "tester")

    def _echo(self, arg: str) -> list[Message]:
        result = asyncio.run(debug.handle("tester", "private:tester", f"<echo> {arg}"))
        self.assertIsNotNone(result)
        flat = "\n".join(str(m) for m in _as_list(result))
        self.assertNotIn("执行失败", flat), f"echo 指令失败：{result}"
        return _as_list(result)

    def test_plain_text_echoes_as_single_text(self):
        replies = self._echo("你好")
        self.assertEqual(len(replies), 1)
        self.assertEqual(str(replies[0]), "你好")

    def test_sticker_tag_renders_image(self):
        replies = self._echo("[表情:Pool Tom]")
        kinds = [seg.type for reply in replies for seg in reply]
        self.assertIn("image", kinds)
        self.assertNotIn("[表情:", "".join(str(m) for m in replies))

    def test_mixed_text_and_tag(self):
        replies = self._echo("你看 [表情:Pool Tom] 怎么样")
        kinds = [seg.type for reply in replies for seg in reply]
        self.assertEqual(kinds, ["text", "image", "text"])

    def test_unknown_tag_kept_literal(self):
        replies = self._echo("[表情:不存在的表情名]")
        self.assertEqual(len(replies), 1)
        # str(Message) 会把 [ 转义为 &#91;，还原后比较实际文本。
        self.assertEqual(unescape(str(replies[0])), "[表情:不存在的表情名]")

    def test_json_plan_renders_through_same_pipeline(self):
        replies = self._echo('{"messages":[{"type":"text","content":"hi"},'
                             '{"type":"sticker","intent":"happy"}]}')
        kinds = [seg.type for reply in replies for seg in reply]
        self.assertEqual(kinds, ["text", "image"])

    def test_multi_text_plan_returns_separate_messages(self):
        """模拟 AI 一次性分条发送多条短句：每个 text 元素是一条独立消息。"""
        replies = self._echo('{"messages":[{"type":"text","content":"A"},'
                             '{"type":"text","content":"B"},'
                             '{"type":"text","content":"C"}]}')
        self.assertEqual(len(replies), 3)
        self.assertEqual([str(m) for m in replies], ["A", "B", "C"])
        for reply in replies:
            self.assertEqual([seg.type for seg in reply], ["text"])

    def test_multiline_plain_text_stays_single_message(self):
        """空行不承担分条语义：普通文本里的换行仍是一条消息。"""
        replies = self._echo("A\nB\nC")
        self.assertEqual(len(replies), 1)


class TagsToPlanTest(unittest.TestCase):
    def test_known_tag_becomes_sticker_part(self):
        chat_plan = sticker.tags_to_plan("[表情:Pool Tom]")
        self.assertEqual(len(chat_plan.parts), 1)
        self.assertIsInstance(chat_plan.parts[0], StickerPart)
        self.assertEqual(chat_plan.parts[0].intent, "Pool Tom")

    def test_unknown_tag_stays_text(self):
        chat_plan = sticker.tags_to_plan("[表情:不存在]")
        self.assertEqual(len(chat_plan.parts), 1)
        self.assertIsInstance(chat_plan.parts[0], TextPart)
        self.assertEqual(chat_plan.parts[0].content, "[表情:不存在]")

    def test_mixed_parts_keep_order(self):
        chat_plan = sticker.tags_to_plan("前缀 [表情:Pool Tom] 后缀")
        self.assertEqual(len(chat_plan.parts), 3)
        self.assertIsInstance(chat_plan.parts[0], TextPart)
        self.assertIsInstance(chat_plan.parts[1], StickerPart)
        self.assertIsInstance(chat_plan.parts[2], TextPart)


if __name__ == "__main__":
    unittest.main()
