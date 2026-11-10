"""多模态（图片/表情包识别）功能的验收测试：不访问真实 QQ、vision API 或 chat.db。"""

import asyncio
import unittest
from dataclasses import replace
from unittest import mock

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.exception import FinishedException

import plugins.chat as chat

DEMO_RESPONSE = '{"messages":[{"type":"text","content":"看到了"}]}'


def make_message(text: str = "", urls: tuple[str, ...] = ()) -> Message:
    message = Message()
    if text:
        message.append(MessageSegment.text(text))
    for url in urls:
        message.append(MessageSegment(type="image", data={"url": url, "file": "x.jpg"}))
    return message


class ExtractUserContentTest(unittest.TestCase):
    def test_text_only(self):
        history_text, content = chat.extract_user_content(make_message("在吗"))
        self.assertEqual(history_text, "在吗")
        self.assertEqual(content, "在吗")

    def test_single_image(self):
        history_text, content = chat.extract_user_content(make_message(urls=("http://a/1.jpg",)))
        self.assertEqual(history_text, "[图片]")
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "[图片]"})
        self.assertEqual(content[1], {"type": "image_url", "image_url": {"url": "http://a/1.jpg"}})

    def test_text_with_images(self):
        history_text, content = chat.extract_user_content(
            make_message("看看", ("http://a/1.jpg", "http://a/2.gif"))
        )
        self.assertEqual(history_text, "看看 [图片] [图片]")
        self.assertEqual(content[0], {"type": "text", "text": "看看"})
        self.assertEqual(len(content), 3)
        self.assertEqual(content[2]["image_url"]["url"], "http://a/2.gif")

    def test_images_capped_at_three(self):
        urls = tuple(f"http://a/{i}.jpg" for i in range(5))
        history_text, content = chat.extract_user_content(make_message(urls=urls))
        self.assertEqual(history_text.count("[图片]"), 3)
        self.assertEqual(len([part for part in content if part["type"] == "image_url"]), 3)

    def test_image_without_url_skipped(self):
        message = Message()
        message.append(MessageSegment(type="image", data={"file": "no-url.jpg"}))
        history_text, content = chat.extract_user_content(message)
        self.assertEqual(history_text, "")
        self.assertEqual(content, "")

    def test_cq_escaped_text_restored(self):
        history_text, content = chat.extract_user_content(make_message("[表情:测试]"))
        self.assertEqual(history_text, "[表情:测试]")
        self.assertEqual(content, "[表情:测试]")


class BuildMessagesVisionTest(unittest.TestCase):
    def test_multimodal_user_content_passed_through(self):
        with (
            mock.patch.object(chat.store, "get_summary", return_value=""),
            mock.patch.object(chat.store, "get_recent", return_value=[]),
        ):
            messages = chat.build_messages("private:1", "看看 [图片]", [{"type": "text", "text": "看看"}, {"type": "image_url", "image_url": {"url": "http://a/1.jpg"}}])
        self.assertEqual(messages[-1]["content"][1]["image_url"]["url"], "http://a/1.jpg")

    def test_dedup_uses_normalized_text(self):
        history = [{"role": "user", "content": "看看 [图片]"}]
        with (
            mock.patch.object(chat.store, "get_summary", return_value=""),
            mock.patch.object(chat.store, "get_recent", return_value=history),
        ):
            messages = chat.build_messages("private:1", "看看 [图片]", [{"type": "text", "text": "看看"}])
        user_msgs = [m for m in messages if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 1)  # 历史里的当前消息被去重，没有重复加入
        self.assertIsInstance(user_msgs[0]["content"], list)

    def test_default_content_matches_history_text(self):
        with (
            mock.patch.object(chat.store, "get_summary", return_value=""),
            mock.patch.object(chat.store, "get_recent", return_value=[]),
        ):
            messages = chat.build_messages("private:1", "在吗")
        self.assertEqual(messages[-1]["content"], "在吗")


class VisionHandlerFlowTest(unittest.TestCase):
    def _run_handler(self, message: Message, *, vision_api: str, vision_model: str = "vision-x"):
        event = mock.Mock()
        event.message_type = "private"
        event.user_id = 42
        event.get_user_id = lambda: "42"
        event.get_message = lambda: message
        bot = mock.Mock()
        bot.self_id = "999"

        send_mock = mock.AsyncMock()
        finish_mock = mock.AsyncMock(side_effect=FinishedException())
        llm_mock = mock.AsyncMock(return_value=DEMO_RESPONSE)
        append_mock = mock.Mock()

        with (
            mock.patch.object(
                chat,
                "settings",
                replace(chat.settings, vision_api=vision_api, vision_model=vision_model),
            ),
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
        return send_mock, llm_mock, append_mock

    def test_image_message_uses_vision_key_and_model(self):
        send, llm, append = self._run_handler(
            make_message("看看这个", ("http://a/1.jpg",)), vision_api="vision-key"
        )
        llm.assert_called_once()
        self.assertEqual(llm.call_args.kwargs, {"api_key": "vision-key", "model": "vision-x"})
        # 发给模型的当前消息包含 image_url 部分。
        user_content = llm.call_args.args[0][-1]["content"]
        self.assertEqual(user_content[1]["image_url"]["url"], "http://a/1.jpg")
        # 历史写入规范化占位文本，不含 URL。
        user_writes = [c.args for c in append.call_args_list if c.args[1] == "user"]
        self.assertEqual(user_writes, [("private:42", "user", "看看这个 [图片]")])
        send.assert_called_once()

    def test_text_message_ignores_vision_config(self):
        _send, llm, _append = self._run_handler(make_message("在吗"), vision_api="vision-key")
        llm.assert_called_once()
        self.assertEqual(llm.call_args.kwargs, {})

    def test_image_without_vision_config_falls_back_to_chat_model(self):
        _send, llm, _append = self._run_handler(
            make_message(urls=("http://a/1.jpg",)), vision_api=""
        )
        llm.assert_called_once()
        self.assertEqual(llm.call_args.kwargs, {})
        # 即使回退到文本模型，历史也应写入 [图片] 占位而不是原始 CQ 码。
        user_writes = [c.args for c in _append.call_args_list if c.args[1] == "user"]
        self.assertEqual(user_writes, [("private:42", "user", "[图片]")])


if __name__ == "__main__":
    unittest.main()
