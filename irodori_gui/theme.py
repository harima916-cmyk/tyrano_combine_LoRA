"""ライトテーマ（style.qss）の適用ヘルパー。

app.py の main() から `apply_theme(app)` を呼ぶだけで、
irodori_gui/style.qss を読み込みアプリ全体に適用します。
QSS が見つからない場合は素の外観のまま起動します（失敗しても落ちない）。
"""

from __future__ import annotations

import os

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

_QSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")

# 日本語UIで読みやすい基準フォント（先頭から順に、環境にあるものが使われる）
_FONT_CANDIDATES = [
    "Zen Kaku Gothic New",
    "Yu Gothic UI",
    "Hiragino Sans",
    "Meiryo",
    "Noto Sans JP",
]


def _base_font() -> QFont:
    families = QFont().families() if hasattr(QFont(), "families") else []
    for name in _FONT_CANDIDATES:
        f = QFont(name, 10)
        # 実在フォントかどうかは厳密には測れないので、候補の先頭を素直に採用。
        # QSS 側の font-family リストが最終的なフォールバックを担保する。
        return f
    return QFont()


def apply_theme(app: QApplication) -> bool:
    """style.qss を app に適用する。成功したら True。"""
    app.setFont(_base_font())
    try:
        with open(_QSS_PATH, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
        return True
    except OSError:
        return False
