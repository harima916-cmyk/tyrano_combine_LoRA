"""irodori_gui.models の単体テスト（Qt イベントループ不要）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from irodori_csv import Character, Line  # noqa: E402
from irodori_gui.models import CharacterTableModel, LineTableModel  # noqa: E402


class TestLineTableModel(unittest.TestCase):
    def _model(self):
        chars = CharacterTableModel([Character("あ", "1", "/l", "a_")])
        return LineTableModel(chars, [Line("1", "こんにちは", "こんにちは")])

    def test_insert_emoji_at_cursor_position(self):
        model = self._model()
        model.insert_emoji(0, "😊", 2)
        self.assertEqual(model.rows[0].send_text, "こん😊にちは")
        self.assertFalse(model.linked[0])

    def test_insert_emoji_defaults_to_end_and_clamps_position(self):
        model = self._model()
        model.insert_emoji(0, "😊")
        self.assertEqual(model.rows[0].send_text, "こんにちは😊")
        model.insert_emoji(0, "☀️", 999)
        self.assertEqual(model.rows[0].send_text, "こんにちは😊☀️")

    def test_insert_emoji_at_start(self):
        model = self._model()
        model.insert_emoji(0, "🥺", 0)
        self.assertEqual(model.rows[0].send_text, "🥺こんにちは")


if __name__ == "__main__":
    unittest.main()
