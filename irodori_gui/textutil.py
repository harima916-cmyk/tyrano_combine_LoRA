"""Qt(QLineEdit) と Python str のカーソル位置単位の変換。

`QLineEdit.cursorPosition()` / `cursorPositionChanged` の位置は **UTF-16 コード単位**の
インデックス。非BMP絵文字（😊 U+1F60A 等）は Qt 上 2 単位、Python `str` 上 1 文字なので、
モデル文字列（Python str）へ挿入する前に **コードポイント index** へ変換する必要がある。
"""

from __future__ import annotations


def qt_cursor_to_index(text: str, qt_pos: int) -> int:
    """UTF-16 コード単位位置 qt_pos を text(Python str) のコードポイント index に変換する。

    例: text="😊test", qt_pos=2（😊 の直後）→ 1（Python では 😊 は 1 文字）。
    """
    if qt_pos <= 0:
        return 0
    units = 0
    for i, ch in enumerate(text):
        if units >= qt_pos:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)
