"""<clear> 删除聊天记录指令的验收测试：mock store 层，不触碰真实 chat.db。"""

import asyncio
import unittest
from unittest import mock

from plugins.chat import debug

ADMIN_SESSION = "private:999"
TARGET_SESSION = "private:123"


class ClearCommandTest(unittest.TestCase):
    def setUp(self):
        debug._active.add("999")
        debug._pending_clear.clear()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        debug._active.discard("999")
        debug._pending_clear.clear()

    def _run(self, text: str):
        return asyncio.run(debug.handle("999", ADMIN_SESSION, text))

    def test_request_returns_confirm_prompt(self):
        with mock.patch.object(debug.store, "count_messages", return_value=10), \
             mock.patch.object(debug.store, "get_summary", return_value="摘"):
            reply = self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
        self.assertIn("<YES>", reply)
        self.assertIn(TARGET_SESSION, reply)
        self.assertEqual(debug._pending_clear.get(ADMIN_SESSION), TARGET_SESSION)

    def test_yes_executes_deletion(self):
        count_mock = mock.Mock(return_value=10)
        summary_mock = mock.Mock(return_value="摘")
        clear_mock = mock.Mock()
        with mock.patch.object(debug.store, "count_messages", count_mock), \
             mock.patch.object(debug.store, "get_summary", summary_mock), \
             mock.patch.object(debug.store, "clear_history", clear_mock):
            self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
            reply = self._run("<YES>")
        clear_mock.assert_called_once_with(TARGET_SESSION)
        self.assertIn("已删除", reply)
        self.assertIn("10", reply)
        self.assertIn("摘要", reply)
        self.assertNotIn(TARGET_SESSION, debug._pending_clear)

    def test_lowercase_yes_also_confirms(self):
        clear_mock = mock.Mock()
        with mock.patch.object(debug.store, "count_messages", return_value=3), \
             mock.patch.object(debug.store, "get_summary", return_value=""), \
             mock.patch.object(debug.store, "clear_history", clear_mock):
            self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
            reply = self._run("<yes>")
        clear_mock.assert_called_once_with(TARGET_SESSION)
        self.assertIn("已删除", reply)

    def test_other_input_cancels_without_deleting(self):
        clear_mock = mock.Mock()
        with mock.patch.object(debug.store, "count_messages", return_value=3), \
             mock.patch.object(debug.store, "get_summary", return_value=""), \
             mock.patch.object(debug.store, "clear_history", clear_mock):
            self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
            reply = self._run("算了")
        clear_mock.assert_not_called()
        self.assertIsNone(reply)  # 取消后消息按正常聊天处理
        self.assertNotIn(ADMIN_SESSION, debug._pending_clear)
        # 取消后再发 <YES> 不会误删。
        with mock.patch.object(debug.store, "clear_history", clear_mock):
            reply2 = self._run("<YES>")
        clear_mock.assert_not_called()
        self.assertIn("未知指令", reply2)

    def test_new_command_supersedes_pending_request(self):
        clear_mock = mock.Mock()
        with mock.patch.object(debug.store, "count_messages", return_value=3), \
             mock.patch.object(debug.store, "get_summary", return_value=""), \
             mock.patch.object(debug.store, "clear_history", clear_mock):
            self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
            reply = self._run("<help>")
        clear_mock.assert_not_called()
        self.assertIn("可用指令", reply)
        self.assertNotIn(ADMIN_SESSION, debug._pending_clear)

    def test_invalid_arg_rejected(self):
        for bad in ("group=123", "private=", "private=abc", ""):
            reply = self._run(f"<clear> {bad}".rstrip())
            self.assertIn("用法", reply, f"输入 {bad!r} 应返回用法提示")
        self.assertNotIn(ADMIN_SESSION, debug._pending_clear)

    def test_empty_session_rejected_before_confirm(self):
        with mock.patch.object(debug.store, "count_messages", return_value=0), \
             mock.patch.object(debug.store, "get_summary", return_value=""):
            reply = self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
        self.assertIn("没有聊天记录", reply)
        self.assertNotIn(ADMIN_SESSION, debug._pending_clear)

    def test_exit_admin_cancels_pending(self):
        with mock.patch.object(debug.store, "count_messages", return_value=3), \
             mock.patch.object(debug.store, "get_summary", return_value=""):
            self._run(f"<clear> private={TARGET_SESSION.split(':')[1]}")
            self._run(EXIT := "</admin>")
        self.assertNotIn(ADMIN_SESSION, debug._pending_clear)
        # 重新进入管理员模式后发 <YES> 也不会误删。
        debug._active.add("999")
        with mock.patch.object(debug.store, "clear_history") as clear_mock:
            reply = self._run("<YES>")
        clear_mock.assert_not_called()
        self.assertIn("未知指令", reply)


if __name__ == "__main__":
    unittest.main()
