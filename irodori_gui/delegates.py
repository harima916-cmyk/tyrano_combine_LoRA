"""テーブルのカスタムデリゲート（キャラ選択コンボ / LoRA フォルダ選択）。"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QComboBox, QFileDialog, QLineEdit, QStyledItemDelegate

from .models import CharacterTableModel


class CursorTrackingLineEditDelegate(QStyledItemDelegate):
    """送信テキスト列: 単一行編集し、カーソル位置を親へ通知する。

    絵文字パレットが「最後にカーソルがあった位置」へ挿入できるよう、
    編集開始・カーソル移動・確定時に (row, pos) を通知する。
    """

    def __init__(self, cursor_changed: Callable[[int, int], None], parent=None):
        super().__init__(parent)
        self.cursor_changed = cursor_changed

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        row = index.row()
        editor.cursorPositionChanged.connect(
            lambda _old, new, r=row: self.cursor_changed(r, new)
        )
        return editor

    def setEditorData(self, editor: QLineEdit, index):
        text = index.model().data(index, role=0x0002) or ""  # Qt.EditRole
        editor.setText(text)
        editor.setCursorPosition(len(text))
        self.cursor_changed(index.row(), editor.cursorPosition())

    def setModelData(self, editor: QLineEdit, model, index):
        model.setData(index, editor.text(), role=0x0002)
        self.cursor_changed(index.row(), editor.cursorPosition())


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
