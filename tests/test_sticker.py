"""表情 intent 检索的验收测试：临时目录 + mock，不触碰真实 stickers/ 与 chat.db。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plugins.chat import sticker

FAKE_IMAGE = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class StickerCatalogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.sticker_dir = root / "stickers"
        (self.sticker_dir / "emoji").mkdir(parents=True)
        self.catalog_path = self.sticker_dir / "catalog.json"
        # 位于 STICKER_DIR 之外的诱饵文件，越界路径不应读到它。
        (root / "evil.png").write_bytes(FAKE_IMAGE)
        self._patcher = mock.patch.multiple(
            sticker, STICKER_DIR=self.sticker_dir, CATALOG_PATH=self.catalog_path
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._reset_cache()

    def _reset_cache(self):
        sticker._catalog_cache = None

    def _write_catalog(self, entries, mtime=None):
        self.catalog_path.write_text(json.dumps(entries), encoding="utf-8")
        if mtime is not None:
            os.utime(self.catalog_path, (mtime, mtime))

    def _write_image(self, rel="emoji/ok.png"):
        path = self.sticker_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(FAKE_IMAGE)
        return rel

    def test_unknown_intent_returns_none(self):
        self._write_catalog([])
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_missing_image_entry_is_skipped(self):
        self._write_catalog(
            [{"id": "ghost", "path": "emoji/nope.png", "intents": ["happy"], "aliases": []}]
        )
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_traversal_path_cannot_escape_sticker_dir(self):
        self._write_catalog(
            [{"id": "evil", "path": "../evil.png", "intents": ["happy"], "aliases": []}]
        )
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_absolute_path_rejected(self):
        outside = Path(self._tmp.name) / "evil.png"
        self._write_catalog(
            [{"id": "evil", "path": str(outside), "intents": ["happy"], "aliases": []}]
        )
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_valid_entry_returns_image_message(self):
        rel = self._write_image()
        self._write_catalog(
            [{"id": "ok", "path": rel, "intents": ["happy", "speechless"], "aliases": ["好"]}]
        )
        for intent in ("happy", "speechless"):
            message = sticker.resolve_sticker(intent)
            self.assertIsNotNone(message)
            self.assertEqual(len(message), 1)
            self.assertEqual(message[0].type, "image")

    def test_missing_intents_field_entry_skipped(self):
        rel = self._write_image()
        self._write_catalog([{"id": "ok", "path": rel, "aliases": []}])
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_catalog_cache_invalidates_on_mtime_change(self):
        self._write_catalog([], mtime=1000)
        self.assertIsNone(sticker.resolve_sticker("happy"))

        rel = self._write_image()
        self._write_catalog(
            [{"id": "ok", "path": rel, "intents": ["happy"], "aliases": []}], mtime=2000
        )
        self.assertIsNotNone(sticker.resolve_sticker("happy"))

    def test_unreadable_image_returns_none(self):
        rel = self._write_image()
        self._write_catalog(
            [{"id": "ok", "path": rel, "intents": ["happy"], "aliases": []}]
        )
        (self.sticker_dir / rel).unlink()
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_broken_catalog_json_returns_none(self):
        self.catalog_path.write_text("not-json{{{", encoding="utf-8")
        self.assertIsNone(sticker.resolve_sticker("happy"))

    def test_missing_catalog_file_returns_none(self):
        self.catalog_path.unlink(missing_ok=True)
        self.assertIsNone(sticker.resolve_sticker("happy"))


if __name__ == "__main__":
    unittest.main()
