"""テーブルのカスタムデリゲート（キャラ選択コンボ / LoRA フォルダ選択）。"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QComboBox, QFileDialog, QStyledItemDelegate

from .models import CharacterTableModel


class SendTextDelegate(QStyledItemDelegate):
    """送信テキスト列: 開いている QLineEdit エディタを親へ通知する。

    絵文字パレットが「編集中セルのカーソル位置」へ直接挿入できるよう、
    編集中のエディタ参照を渡す（編集終了時は None）。
    """

    def __init__(self, on_editor: Callable, parent=None):
        super().__init__(parent)
        self._on_editor = on_editor

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)  # 既定は QLineEdit
        self._on_editor(editor)
        return editor

    def destroyEditor(self, editor, index):
        self._on_editor(None)
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
