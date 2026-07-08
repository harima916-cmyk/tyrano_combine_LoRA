"""irodori_gui.textutil の単体テスト（Qt 不要）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from irodori_gui.textutil import qt_cursor_to_index  # noqa: E402


class TestQtCursorToIndex(unittest.TestCase):
    def test_bmp_only(self):
        # BMP のみなら UTF-16 単位 == コードポイント index
        self.assertEqual(qt_cursor_to_index("おはよう", 0), 0)
        self.assertEqual(qt_cursor_to_index("おはよう", 2), 2)
        self.assertEqual(qt_cursor_to_index("おはよう", 4), 4)

    def test_non_bmp_emoji(self):
        # 😊 は Qt で 2 単位、Python で 1 文字
        self.assertEqual(qt_cursor_to_index("😊test", 0), 0)
        self.assertEqual(qt_cursor_to_index("😊test", 2), 1)  # 😊 の直後
        self.assertEqual(qt_cursor_to_index("😊test", 3), 2)  # 't' の直後
        self.assertEqual(qt_cursor_to_index("😊😲x", 4), 2)  # 2 つの絵文字の後

    def test_clamp(self):
        self.assertEqual(qt_cursor_to_index("ab", 999), 2)
        self.assertEqual(qt_cursor_to_index("ab", -1), 0)
        self.assertEqual(qt_cursor_to_index("", 0), 0)


if __name__ == "__main__":
    unittest.main()
