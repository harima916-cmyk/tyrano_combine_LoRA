"""シナリオCSV 作成 GUI メインウィンドウ（GUI_SPEC 準拠）。"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from irodori_csv import ParseError, Scenario, read_scenario, validate_scenario, write_scenario

from .delegates import (
    CharacterComboDelegate,
    EditorTrackingDelegate,
    LoraFolderDelegate,
    SendTextDelegate,
)
from .emoji import load_emoji_palette
from .models import CharacterTableModel, LineTableModel
from .textutil import qt_cursor_to_index

ENCODINGS = ["utf-8-sig", "utf-8", "cp932"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Irodori シナリオCSV エディタ")
        self.resize(1000, 720)

        self.current_path: str | None = None
        self.config_path = "config.yaml"
        self.dirty = False
        self._proc: QProcess | None = None
        self._player = None
        self._audio_out = None
        self._active_send_editor = None       # 編集中の送信テキスト QLineEdit（ライブ挿入用）
        self._active_text_editor = None       # 編集中の原文 QLineEdit（消失防止の確定用）
        self._send_edit_row: int | None = None     # 編集中の行（エディタの行）
        self._send_cursor_row: int | None = None   # 最後にカーソルがあった行
        self._send_cursor_pos: int | None = None   # 最後にカーソルがあった位置（コードポイント index）

        self.char_model = CharacterTableModel()
        self.line_model = LineTableModel(self.char_model)
        self.char_model.changed.connect(self._on_changed)
        self.line_model.changed.connect(self._on_changed)
        self.char_model.changed.connect(self.line_model.refresh_all)

        self._build_ui()
        self._new_file()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        # ツールバー（ショートカット付き）
        tb = self.addToolBar("main")
        act_new = QAction("新規", self, triggered=self._new_file)
        act_new.setShortcut(QKeySequence.StandardKey.New)          # Ctrl+N
        act_open = QAction("開く", self, triggered=self._open_file)
        act_open.setShortcut(QKeySequence.StandardKey.Open)        # Ctrl+O
        act_save = QAction("保存", self, triggered=self._save_file)
        act_save.setShortcut(QKeySequence.StandardKey.Save)        # Ctrl+S
        act_save_as = QAction("名前を付けて保存", self, triggered=self._save_as)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)   # Ctrl+Shift+S
        for a in (act_new, act_open, act_save, act_save_as):
            a.setShortcutContext(Qt.ApplicationShortcut)
            self.addAction(a)  # ツールバー非表示時もショートカットが効くように
            tb.addAction(a)
        tb.addSeparator()
        tb.addWidget(QLabel(" 文字コード: "))
        self.enc_combo = QComboBox()
        self.enc_combo.addItems(ENCODINGS)
        tb.addWidget(self.enc_combo)
        tb.addSeparator()
        tb.addAction(QAction("設定ファイル…", self, triggered=self._choose_config))
        self.gen_btn = QPushButton("▶ 一括生成…")
        self.gen_btn.clicked.connect(self._run_bulk)
        tb.addWidget(self.gen_btn)

        # メイン: タブ構成（セリフを主役に、定義・検証/ログは別タブ）
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_lines_tab(), "セリフ")
        self.tabs.addTab(self._build_chars_tab(), "キャラクター定義")
        self._checks_tab_index = self.tabs.addTab(self._build_checks_tab(), "検証 / 生成ログ")
        root.addWidget(self.tabs)

        self.setCentralWidget(central)

    # --------------------------------------------------------------- tabs
    def _build_chars_tab(self) -> QWidget:
        w = QWidget()
        cb = QVBoxLayout(w)
        self.char_view = QTableView()
        self.char_view.setModel(self.char_model)
        self.char_view.setItemDelegateForColumn(2, LoraFolderDelegate(self.char_view))
        self.char_view.setWordWrap(True)
        self.char_view.setTextElideMode(Qt.ElideNone)
        self.char_view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.char_view.horizontalHeader().setStretchLastSection(True)
        cb.addWidget(self.char_view)
        crow = QHBoxLayout()
        crow.addWidget(QPushButton("＋ 追加", clicked=self.char_model.add_row))
        crow.addWidget(QPushButton("－ 削除", clicked=self._remove_char))
        crow.addStretch()
        cb.addLayout(crow)
        return w

    def _build_lines_tab(self) -> QWidget:
        # 横スプリッタ: 左=セリフ表(主役, 可変) / 右=絵文字パレット
        splitter = QSplitter(Qt.Horizontal)

        top = QWidget()
        lb = QVBoxLayout(top)
        lb.setContentsMargins(0, 0, 0, 0)
        self.line_view = QTableView()
        self.line_view.setModel(self.line_model)
        self.line_view.setItemDelegateForColumn(
            LineTableModel.COL_CHAR, CharacterComboDelegate(self.char_model, self.line_view)
        )
        self.line_view.setItemDelegateForColumn(
            LineTableModel.COL_SEND,
            SendTextDelegate(self._set_send_editor, self._remember_send_cursor, self.line_view),
        )
        self.line_view.setItemDelegateForColumn(
            LineTableModel.COL_TEXT,
            EditorTrackingDelegate(self._set_text_editor, self.line_view),
        )
        self.line_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.line_view.setWordWrap(True)
        self.line_view.setTextElideMode(Qt.ElideNone)
        self.line_view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.line_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.line_view.horizontalHeader().setStretchLastSection(True)
        self.line_view.setColumnWidth(LineTableModel.COL_TEXT, 300)
        self.line_view.setColumnWidth(LineTableModel.COL_SEND, 320)
        lb.addWidget(self.line_view)
        lrow = QHBoxLayout()
        lrow.addWidget(QPushButton("＋ 行追加", clicked=self.line_model.add_row))
        lrow.addWidget(QPushButton("複製", clicked=lambda: self.line_model.duplicate_row(self._line_row())))
        lrow.addWidget(QPushButton("↑", clicked=lambda: self._move_line(-1)))
        lrow.addWidget(QPushButton("↓", clicked=lambda: self._move_line(1)))
        lrow.addWidget(QPushButton("削除", clicked=lambda: self.line_model.remove_row(self._line_row())))
        lrow.addWidget(QPushButton("原文で上書き(再リンク)", clicked=lambda: self.line_model.relink(self._line_row())))
        lrow.addStretch()
        preview_btn = QPushButton("🔊 お試し生成", clicked=self._run_preview)
        preview_btn.setProperty("accent", True)  # 淡アクセント（テーマの QPushButton[accent=true]）
        lrow.addWidget(preview_btn)
        lb.addLayout(lrow)
        splitter.addWidget(top)

        splitter.addWidget(self._build_emoji_panel(cols=1))
        splitter.setStretchFactor(0, 5)   # セリフ表を優先的に広く
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 210])
        return splitter

    def _build_emoji_panel(self, cols: int = 1) -> QWidget:
        box = QGroupBox("絵文字パレット（送信テキスト編集中はカーソル位置へ／未編集は末尾へ挿入）")
        box.setFocusPolicy(Qt.NoFocus)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.viewport().setFocusPolicy(Qt.NoFocus)
        scroll.setWidgetResizable(True)
        grid_w = QWidget()
        grid_w.setObjectName("emojiGrid")  # QSS の透過背景ルール対象
        grid_w.setFocusPolicy(Qt.NoFocus)
        vbox = QVBoxLayout(grid_w)
        vbox.setContentsMargins(1, 1, 1, 1)
        vbox.setSpacing(1)
        # カテゴリ別に見出しを挟んで縦に並べる（効果の分類ごとにグルーピング）
        current_cat = None
        for e in load_emoji_palette():
            if e.category and e.category != current_cat:
                current_cat = e.category
                hdr = QLabel(f"― {e.category} ―")
                hdr.setObjectName("emojiCategory")
                hdr.setFocusPolicy(Qt.NoFocus)
                vbox.addWidget(hdr)
            btn = QToolButton()
            btn.setText(f"{e.emoji}  {e.meaning_ja}")
            tip = e.meaning_en
            if e.example:
                tip = f"{e.meaning_en}\n入力例: {e.example}"
            btn.setToolTip(tip)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            # テーマ(QGroupBox QToolButton)に見た目を委ねる（インラインstyleは付けない）
            vbox.addWidget(btn)
            btn.clicked.connect(lambda _=False, em=e.emoji: self._insert_emoji(em))
        vbox.addStretch()
        scroll.setWidget(grid_w)
        outer.addWidget(scroll)
        return box

    def _build_checks_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("検証"))
        self.val_list = QListWidget()
        v.addWidget(self.val_list, 1)
        self.progress = QProgressBar()
        v.addWidget(self.progress)
        log_head = QHBoxLayout()
        log_head.addWidget(QLabel("生成ログ"))
        log_head.addStretch()
        log_head.addWidget(QPushButton("ログをコピー", clicked=self._copy_log))
        log_head.addWidget(QPushButton("ログを保存…", clicked=self._save_log))
        log_head.addWidget(QPushButton("クリア", clicked=lambda: self.log.clear()))
        v.addLayout(log_head)
        self.log = QListWidget()
        self.log.setSelectionMode(QListWidget.ExtendedSelection)
        v.addWidget(self.log, 1)
        return w

    # ------------------------------------------------------------- log utils
    def _log_text(self) -> str:
        return "\n".join(self.log.item(i).text() for i in range(self.log.count()))

    def _copy_log(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._log_text())
        self.statusBar().showMessage("ログをクリップボードにコピーしました。", 3000)

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "ログを保存", os.path.join(self._project_dir(), "irodori_log.txt"),
            "テキスト (*.txt)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._log_text() + "\n")
        except OSError as e:
            QMessageBox.critical(self, "保存エラー", str(e))
            return
        self.statusBar().showMessage(f"ログを保存しました: {path}", 5000)

    # ------------------------------------------------------------- helpers
    def _line_row(self) -> int:
        idx = self.line_view.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _move_line(self, delta: int):
        row = self._line_row()
        new = self.line_model.move_row(row, delta)
        self.line_view.selectRow(new)

    def _remove_char(self):
        idx = self.char_view.currentIndex()
        if idx.isValid():
            self.char_model.remove_row(idx.row())

    def _set_send_editor(self, editor, row=None):
        self._active_send_editor = editor
        if row is not None:
            self._send_edit_row = row

    def _remember_send_cursor(self, row: int, pos: int):
        # pos はコードポイント index（デリゲート側で UTF-16 から変換済み）
        self._send_cursor_row = row
        self._send_cursor_pos = pos

    def _set_text_editor(self, editor):
        self._active_text_editor = editor

    def _commit_open_cell_editor(self) -> bool:
        """原文セルを編集中なら、その内容を確定して閉じる。

        絵文字クリックで未確定の入力が消える事故を防ぐ。確定により原文→送信テキストの
        反映（リンク中なら）も先に行われる。確定した場合 True。
        """
        ed = self._active_text_editor
        if ed is None:
            return False
        from PySide6.QtWidgets import QAbstractItemDelegate

        try:
            self.line_view.commitData(ed)
            self.line_view.closeEditor(ed, QAbstractItemDelegate.NoHint)
            return True
        except (RuntimeError, TypeError):
            self._active_text_editor = None
            return False

    def _insert_emoji(self, emoji: str):
        # (1) 送信テキストを編集中なら、その生きたカーソル位置へ挿入（エディタは閉じない）
        ed = self._active_send_editor
        if ed is not None:
            try:
                ed.deselect()      # 全選択状態でも上書きしない
                ed.insert(emoji)   # カーソル位置へ挿入（Qt 内部＝UTF-16 で正しく挿入）
                # ライブ挿入後の位置を保険として記録（コードポイント index に変換）
                row = self._send_edit_row if self._send_edit_row is not None else self._line_row()
                self._remember_send_cursor(row, qt_cursor_to_index(ed.text(), ed.cursorPosition()))
                return
            except RuntimeError:
                self._active_send_editor = None  # 破棄済み C++ オブジェクト → フォールバックへ
        # (2) 原文など別セルを編集中なら、まず確定（消失防止＋送信テキストへ反映）してから追記
        if self._commit_open_cell_editor():
            # 反映後の送信テキスト末尾へ追記する（古いカーソル位置は無効化）
            self._send_cursor_row = None
            self._send_cursor_pos = None
        # (3) 記録済みカーソル位置（無ければ末尾）へモデル層で挿入
        row = self._line_row()
        if row < 0:
            QMessageBox.information(
                self, "絵文字挿入",
                "セルをダブルクリックして編集し、入れたい位置にカーソルを置いてから押してください。",
            )
            return
        pos = self._send_cursor_pos if self._send_cursor_row == row else None
        self.line_model.insert_emoji(row, emoji, pos)
        # 連続挿入できるよう位置を追従（すべてコードポイント index）
        self._send_cursor_row = row
        self._send_cursor_pos = (
            len(self.line_model.rows[row].send_text) if pos is None else pos + len(emoji)
        )

    def _on_changed(self):
        self.dirty = True
        self._update_title()
        self._revalidate()

    def _update_title(self):
        name = self.current_path or "(未保存)"
        star = " *" if self.dirty else ""
        self.setWindowTitle(f"Irodori シナリオCSV エディタ — {os.path.basename(name)}{star}")

    def _scenario(self) -> Scenario:
        return Scenario(self.char_model.characters(), self.line_model.lines())

    def _revalidate(self):
        self.val_list.clear()
        issues = validate_scenario(self._scenario(), check_lora_exists=True, group_by_char=True)
        for i in issues:
            mark = "✖" if i.is_error else "⚠"
            loc = f"[{i.section}:{i.index}] " if i.index >= 0 else ""
            self.val_list.addItem(f"{mark} {loc}{i.message}")
        if not issues:
            self.val_list.addItem("問題なし")
        # 検証タブが隠れていても気づけるよう、見出しに件数バッジを出す
        errors = sum(1 for i in issues if i.is_error)
        warns = len(issues) - errors
        badge = ""
        if errors:
            badge += f"  ✖{errors}"
        if warns:
            badge += f"  ⚠{warns}"
        if getattr(self, "_checks_tab_index", None) is not None:
            self.tabs.setTabText(self._checks_tab_index, "検証 / 生成ログ" + badge)

    # ------------------------------------------------------------- file ops
    def _maybe_save(self) -> bool:
        """未保存があれば 保存/破棄/キャンセル を尋ねる。続行してよいなら True。

        保存を選んで実際に保存できたら True、破棄なら True、キャンセルまたは
        保存に失敗/中止したら False（＝終了・新規・開くを中断）。
        """
        if not self.dirty:
            return True
        r = QMessageBox.warning(
            self, "未保存の変更",
            "未保存の変更があります。保存しますか？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if r == QMessageBox.StandardButton.Save:
            return self._save_file()   # 保存成功で True、名前付け保存を中止したら False
        if r == QMessageBox.StandardButton.Discard:
            return True
        return False  # Cancel

    def _clear_send_editor_state(self):
        """モデルリセット前に、破棄されうる編集中エディタ参照を無効化する。"""
        self._active_send_editor = None
        self._active_text_editor = None
        self._send_edit_row = None
        self._send_cursor_row = None
        self._send_cursor_pos = None

    def _new_file(self):
        if not self._maybe_save():
            return
        self._clear_send_editor_state()
        self.char_model.beginResetModel(); self.char_model.rows = []; self.char_model.endResetModel()
        self.line_model.beginResetModel(); self.line_model.rows = []; self.line_model.linked = []; self.line_model.endResetModel()
        self.char_model.add_row()
        self.line_model.add_row()
        self.current_path = None
        self.dirty = False
        self._update_title()
        self._revalidate()

    def _open_file(self):
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "CSV を開く", "", "CSV (*.csv)")
        if not path:
            return
        enc = self.enc_combo.currentText()
        try:
            sc = read_scenario(path, encoding=enc)
        except (ParseError, OSError, UnicodeDecodeError) as e:
            QMessageBox.critical(self, "読み込みエラー", str(e))
            return
        self._load_scenario(sc, path)

    def _load_scenario(self, sc: Scenario, path: str | None):
        self._clear_send_editor_state()
        self.char_model.beginResetModel(); self.char_model.rows = sc.characters; self.char_model.endResetModel()
        self.line_model.beginResetModel()
        self.line_model.rows = sc.lines
        self.line_model.linked = [LineTableModel._infer_linked(l) for l in sc.lines]
        self.line_model.endResetModel()
        self.current_path = path
        self.dirty = False
        self._update_title()
        self._revalidate()
        self.line_view.resizeRowsToContents()
        self.char_view.resizeRowsToContents()

    def _save_file(self) -> bool:
        if self.current_path is None:
            return self._save_as()
        return self._write(self.current_path)

    def _save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "名前を付けて保存", "scenario.csv", "CSV (*.csv)")
        if not path:
            return False
        return self._write(path)

    def _write(self, path: str) -> bool:
        try:
            write_scenario(self._scenario(), path, encoding=self.enc_combo.currentText())
        except OSError as e:
            QMessageBox.critical(self, "保存エラー", str(e))
            return False
        self.current_path = path
        self.dirty = False
        self._update_title()
        return True

    def _choose_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "設定ファイルを選択", "", "YAML (*.yaml *.yml)")
        if path:
            self.config_path = path

    # ------------------------------------------------------------- generation
    def _python(self) -> str:
        return sys.executable or "python3"

    def _project_dir(self) -> str:
        """プロジェクトの基準フォルダ（config.yaml のある場所 → CSV の場所 → cwd）。"""
        if self.config_path and os.path.exists(self.config_path):
            return os.path.dirname(os.path.abspath(self.config_path))
        if self.current_path:
            return os.path.dirname(os.path.abspath(self.current_path))
        return os.getcwd()

    def _config_args(self) -> list[str]:
        return ["--config", self.config_path] if self.config_path else []

    def _run_bulk(self):
        if self.dirty or self.current_path is None:
            if not self._save_file():
                return
        issues = validate_scenario(self._scenario(), group_by_char=True)
        if any(i.is_error for i in issues):
            r = QMessageBox.question(
                self, "検証エラー", "検証エラーがあります。続行しますか？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return
        out_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if not out_dir:
            return
        # 進捗・ログが見えるよう検証/ログタブへ切り替える
        if getattr(self, "_checks_tab_index", None) is not None:
            self.tabs.setCurrentIndex(self._checks_tab_index)
        args = [
            "-m", "irodori_cli", *self._config_args(), "--csv", self.current_path,
            "build", "--out-dir", out_dir, "--copy-csv", "--group-by-char", "--progress",
        ]
        self._start_process(args, on_done=lambda code: self._bulk_done(code, out_dir))

    def _bulk_done(self, code: int, out_dir: str):
        self.log.addItem(f"完了 (code={code}) → {out_dir}")

    def _run_preview(self):
        row = self._line_row()
        if row < 0:
            QMessageBox.information(self, "お試し生成", "生成するセリフ行を選択してください。")
            return
        line = self.line_model.rows[row]
        char = self.line_model.char_model_char(line.ref)
        if char is None:
            QMessageBox.warning(self, "お試し生成", "このセリフのキャラが未定義です。")
            return
        # 隠し temp ではなく、プロジェクト内の見える preview/ フォルダへ保存
        out = os.path.join(self._project_dir(), "preview", f"row{row + 1}.wav")
        args = [
            "-m", "irodori_cli", *self._config_args(),
            "preview", "--text", line.tts_text(), "--lora-dir", char.lora_dir, "--out", out,
        ]
        self._start_process(args, on_done=lambda code: self._preview_done(code, out))

    def _preview_done(self, code: int, out: str):
        if code == 0 and os.path.exists(out):
            self._play(out)
        else:
            QMessageBox.warning(self, "お試し生成", "生成に失敗しました。ログを確認してください。")

    def _play(self, path: str):
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtCore import QUrl
        except ImportError:
            self.log.addItem(f"再生不可（QtMultimedia なし）: {path}")
            return
        self._player = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        self.log.addItem(f"▶ 再生: {path}")

    def _start_process(self, args: list[str], on_done):
        if self._proc is not None:
            QMessageBox.information(self, "実行中", "別の生成処理が実行中です。")
            return
        self.progress.setValue(0)
        self.log.addItem("$ " + self._python() + " " + " ".join(args))
        proc = QProcess(self)
        proc.setProgram(self._python())
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: self._read_proc(proc))
        proc.finished.connect(lambda code, _st: self._proc_finished(code, on_done))
        self._proc = proc
        self.gen_btn.setEnabled(False)
        proc.start()

    def _read_proc(self, proc: QProcess):
        text = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("PROGRESS"):
                parts = line.split()
                if len(parts) >= 3 and "/" in parts[1]:
                    done, total = parts[1].split("/")
                    try:
                        self.progress.setMaximum(int(total))
                        self.progress.setValue(int(done))
                    except ValueError:
                        pass
            self.log.addItem(line)
        self.log.scrollToBottom()

    def _proc_finished(self, code: int, on_done):
        self._proc = None
        self.gen_btn.setEnabled(True)
        on_done(code)

    def closeEvent(self, event):
        if self._maybe_save():
            event.accept()
        else:
            event.ignore()


def main():
    from PySide6.QtWidgets import QApplication

    from .theme import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app)  # ライトテーマ（style.qss）を適用
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
