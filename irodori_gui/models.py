"""Qt テーブルモデル（キャラクター定義 / セリフ）。"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from irodori_csv import Character, Line, Scenario
from irodori_csv.naming import output_name


class CharacterTableModel(QAbstractTableModel):
    HEADERS = ["キャラ名", "参照番号", "LoRAフォルダ", "生成ファイルヘッド"]

    changed = Signal()

    def __init__(self, characters: list[Character] | None = None):
        super().__init__()
        self.rows: list[Character] = characters or []

    # --- Qt overrides ---
    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        c = self.rows[index.row()]
        return [c.name, c.ref, c.lora_dir, c.head][index.column()]

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        c = self.rows[index.row()]
        value = str(value)
        col = index.column()
        if col == 0:
            c.name = value
        elif col == 1:
            c.ref = value
        elif col == 2:
            c.lora_dir = value
        elif col == 3:
            c.head = value
        self.dataChanged.emit(index, index)
        self.changed.emit()
        return True

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    # --- 操作 ---
    def add_row(self):
        ref = self._next_ref()
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(Character(name="", ref=ref, lora_dir="", head=""))
        self.endInsertRows()
        self.changed.emit()

    def remove_row(self, row: int):
        if 0 <= row < len(self.rows):
            self.beginRemoveRows(QModelIndex(), row, row)
            self.rows.pop(row)
            self.endRemoveRows()
            self.changed.emit()

    def _next_ref(self) -> str:
        used = set()
        for c in self.rows:
            try:
                used.add(int(c.ref))
            except (ValueError, TypeError):
                pass
        n = 1
        while n in used:
            n += 1
        return str(n)

    def characters(self) -> list[Character]:
        return self.rows

    def names_and_refs(self) -> list[tuple[str, str]]:
        return [(c.name, c.ref) for c in self.rows]


class LineTableModel(QAbstractTableModel):
    HEADERS = ["#", "キャラ", "テキスト", "送信テキスト", "🔗", "出力名"]
    COL_NUM, COL_CHAR, COL_TEXT, COL_SEND, COL_LINK, COL_OUT = range(6)

    changed = Signal()

    def __init__(self, char_model: CharacterTableModel, lines: list[Line] | None = None):
        super().__init__()
        self.char_model = char_model
        self.rows: list[Line] = lines or []
        # 行ごとのリンク状態（True=原文と連動 / False=送信テキスト手動編集済み）
        self.linked: list[bool] = [self._infer_linked(l) for l in self.rows]

    @staticmethod
    def _infer_linked(line: Line) -> bool:
        # 開いた直後: 送信テキストが空、または原文と一致していれば連動とみなす
        return line.send_text.strip() == "" or line.send_text == line.text

    def refresh_all(self):
        """キャラ定義変更時などに出力名・キャラ列を再描画する。"""
        if self.rows:
            top = self.index(0, 0)
            bottom = self.index(len(self.rows) - 1, self.columnCount() - 1)
            self.dataChanged.emit(top, bottom)

    # --- Qt overrides ---
    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def _seq_and_output(self, row: int) -> tuple[int, str]:
        """当該行のキャラ内連番と出力名を、上からの出現順で算出。"""
        target = self.rows[row]
        seq = 0
        for i in range(row + 1):
            if self.rows[i].ref == target.ref:
                seq += 1
        char = self.char_model_char(target.ref)
        if char is None:
            return seq, ""
        return seq, output_name(char.head, seq)

    def char_model_char(self, ref: str):
        for c in self.char_model.rows:
            if c.ref == ref:
                return c
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        line = self.rows[row]
        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == self.COL_NUM:
                return row + 1
            if col == self.COL_CHAR:
                char = self.char_model_char(line.ref)
                if role == Qt.EditRole:
                    return line.ref
                return char.name if char else f"(未定義:{line.ref})"
            if col == self.COL_TEXT:
                return line.text
            if col == self.COL_SEND:
                return line.send_text
            if col == self.COL_LINK:
                return "🔗" if self.linked[row] else "✎"
            if col == self.COL_OUT:
                return self._seq_and_output(row)[1]
        if role == Qt.ToolTipRole and col == self.COL_LINK:
            return "原文と連動中" if self.linked[row] else "送信テキストを手動編集済み"
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        row, col = index.row(), index.column()
        line = self.rows[row]
        value = str(value)
        if col == self.COL_CHAR:
            line.ref = value  # コンボは ref を渡す
        elif col == self.COL_TEXT:
            line.text = value
            # 原文 → 送信テキストの自動反映（連動中の行のみ、一方向）
            if self.linked[row]:
                line.send_text = value
        elif col == self.COL_SEND:
            line.send_text = value
            self.linked[row] = False  # 手動編集で切り離し
        else:
            return False
        self._emit_row(row)
        self.changed.emit()
        return True

    def _emit_row(self, row: int):
        left = self.index(row, 0)
        right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(left, right)

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() in (self.COL_CHAR, self.COL_TEXT, self.COL_SEND):
            return base | Qt.ItemIsEditable
        return base

    # --- 操作 ---
    def add_row(self):
        ref = self.char_model.rows[0].ref if self.char_model.rows else ""
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(Line(ref=ref, text="", send_text=""))
        self.linked.append(True)
        self.endInsertRows()
        self.changed.emit()

    def duplicate_row(self, row: int):
        if 0 <= row < len(self.rows):
            src = self.rows[row]
            self.beginInsertRows(QModelIndex(), row + 1, row + 1)
            self.rows.insert(row + 1, Line(src.ref, src.text, src.send_text))
            self.linked.insert(row + 1, self.linked[row])
            self.endInsertRows()
            self.refresh_all()
            self.changed.emit()

    def remove_row(self, row: int):
        if 0 <= row < len(self.rows):
            self.beginRemoveRows(QModelIndex(), row, row)
            self.rows.pop(row)
            self.linked.pop(row)
            self.endRemoveRows()
            self.refresh_all()
            self.changed.emit()

    def move_row(self, row: int, delta: int):
        j = row + delta
        if 0 <= row < len(self.rows) and 0 <= j < len(self.rows):
            self.beginResetModel()
            self.rows[row], self.rows[j] = self.rows[j], self.rows[row]
            self.linked[row], self.linked[j] = self.linked[j], self.linked[row]
            self.endResetModel()
            self.changed.emit()
            return j
        return row

    def relink(self, row: int):
        """✎ の行を原文で上書きして 🔗 に戻す。"""
        if 0 <= row < len(self.rows):
            self.rows[row].send_text = self.rows[row].text
            self.linked[row] = True
            self._emit_row(row)
            self.changed.emit()

    def insert_emoji(self, row: int, emoji: str, pos: int | None = None):
        """選択行の送信テキストへ絵文字を挿入（切り離し扱い）。"""
        if 0 <= row < len(self.rows):
            text = self.rows[row].send_text
            if pos is None:
                pos = len(text)
            pos = max(0, min(pos, len(text)))
            self.rows[row].send_text = text[:pos] + emoji + text[pos:]
            self.linked[row] = False
            self._emit_row(row)
            self.changed.emit()

    def lines(self) -> list[Line]:
        return self.rows
