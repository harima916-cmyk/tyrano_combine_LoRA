"""絵文字挿入（アプリ層）の回帰テスト。offscreen で実行。

ライブ挿入（編集中エディタ）は自動テストしづらいため、
「エディタが閉じた/未編集」経路（＝過去に末尾追加へ退行した経路）を固定する。
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    from irodori_csv import Character, Line  # noqa: E402
    from irodori_gui.app import MainWindow  # noqa: E402
    from irodori_gui.models import LineTableModel as L  # noqa: E402

    HAVE_QT = True
except Exception:  # noqa: BLE001
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6/offscreen が使えない環境ではスキップ")
class TestEmojiInsertApp(unittest.TestCase):
    def _win(self) -> "MainWindow":
        w = MainWindow()
        w.line_model.setData(w.line_model.index(0, L.COL_CHAR), "1", role=2)
        w.line_model.setData(w.line_model.index(0, L.COL_TEXT), "おはよう", role=2)
        w.line_view.setCurrentIndex(w.line_model.index(0, L.COL_SEND))
        return w

    def test_fallback_inserts_at_tracked_cursor(self):
        """エディタが閉じていても、記録したカーソル位置へ挿入（末尾追加でない）。"""
        w = self._win()
        w._active_send_editor = None
        w._remember_send_cursor(0, 2)
        w._insert_emoji("😊")
        self.assertEqual(w.line_model.rows[0].send_text, "おは😊よう")
        self.assertFalse(w.line_model.linked[0])

    def test_fallback_consecutive_advances(self):
        w = self._win()
        w._active_send_editor = None
        w._remember_send_cursor(0, 2)
        w._insert_emoji("😲")
        w._insert_emoji("🥺")
        self.assertEqual(w.line_model.rows[0].send_text, "おは😲🥺よう")

    def test_append_when_untracked(self):
        w = self._win()
        w._active_send_editor = None
        w._send_cursor_row = None
        w._send_cursor_pos = None
        w._insert_emoji("😊")
        self.assertEqual(w.line_model.rows[0].send_text, "おはよう😊")

    def test_fallback_into_cell_with_existing_emoji(self):
        """既に絵文字がある行でも、コードポイント index で正しい位置に挿入（Finding 1）。"""
        w = self._win()
        # 送信テキストを「😊test」にし、😊 の直後（コードポイント index 1）に挿入
        w.line_model.setData(w.line_model.index(0, L.COL_SEND), "😊test", role=2)
        w._active_send_editor = None
        w._remember_send_cursor(0, 1)  # デリゲートが変換した後の index
        w._insert_emoji("🎉")
        self.assertEqual(w.line_model.rows[0].send_text, "😊🎉test")


if __name__ == "__main__":
    unittest.main()
