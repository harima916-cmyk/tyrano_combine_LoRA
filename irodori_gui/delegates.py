"""テーブルのカスタムデリゲート（キャラ選択コンボ / LoRA フォルダ選択）。"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QComboBox, QFileDialog, QStyledItemDelegate

from .models import CharacterTableModel
from .textutil import qt_cursor_to_index


class SendTextDelegate(QStyledItemDelegate):
    """送信テキスト列: 編集中エディタとカーソル位置を親へ通知する。

    絵文字パレットが「編集中セルのカーソル位置」へ挿入できるよう:
    - `on_editor(editor|None)`: 編集開始で QLineEdit を、終了で None を通知（ライブ挿入用）
    - `on_cursor(row, pos)`  : カーソル移動を通知（エディタが閉じても位置を復元できる保険）
    """

    def __init__(self, on_editor: Callable, on_cursor: Callable, parent=None):
        super().__init__(parent)
        self._on_editor = on_editor
        self._on_cursor = on_cursor

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)  # 既定は QLineEdit
        self._on_editor(editor, index.row())
        row = index.row()
        try:
            # cursorPositionChanged の位置は UTF-16 単位 → コードポイント index に変換して通知
            editor.cursorPositionChanged.connect(
                lambda _old, new, ed=editor, r=row: self._on_cursor(
                    r, qt_cursor_to_index(ed.text(), new)
                )
            )
        except AttributeError:
            pass
        return editor

    def setModelData(self, editor, model, index):
        super().setModelData(editor, model, index)
        try:
            self._on_cursor(index.row(), qt_cursor_to_index(editor.text(), editor.cursorPosition()))
        except (AttributeError, RuntimeError):
            pass

    def destroyEditor(self, editor, index):
        self._on_editor(None, None)
        super().destroyEditor(editor, index)


class CharacterComboDelegate(QStyledItemDelegate):
    """セリフの「キャラ」列: キャラ名で選ばせ、ref を保存する。"""

    def __init__(self, char_model: CharacterTableModel, parent=None):
        super().__init__(parent)
        self.char_model = char_model

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for name, ref in self.char_model.names_and_refs():
            label = name if name.strip() else f"(参照{ref})"
            combo.addItem(label, ref)
        return combo

    def setEditorData(self, editor: QComboBox, index):
        ref = index.model().data(index, role=0x0002)  # Qt.EditRole
        pos = editor.findData(ref)
        if pos >= 0:
            editor.setCurrentIndex(pos)

    def setModelData(self, editor: QComboBox, model, index):
        ref = editor.currentData()
        model.setData(index, ref, role=0x0002)


class LoraFolderDelegate(QStyledItemDelegate):
    """LoRAフォルダ列: 編集時にフォルダ選択ダイアログを開く。"""

    def createEditor(self, parent, option, index):
        current = index.model().data(index, role=0x0002) or ""
        path = QFileDialog.getExistingDirectory(parent, "LoRAフォルダを選択", current)
        if path:
            index.model().setData(index, path, role=0x0002)
        return None  # インライン編集は行わない
