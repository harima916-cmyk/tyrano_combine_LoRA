"""GUI 用の常駐生成コントローラ。

モデルを1回だけロードして常駐させる WorkerRunner をバックグラウンドスレッドで保持し、
お試し生成・一括生成の両方を同じプリロード済みモデルで実行する。
すべての重い処理（モデルロード・生成）はワーカースレッド側で行い、UI は固まらない。
"""

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from irodori_cli.build import Builder
from irodori_cli.config import Config, load_config
from irodori_cli.worker import WorkerRunner
from irodori_csv import read_scenario


class _GenWorker(QObject):
    """ワーカースレッド側の実体。スロットはワーカースレッドで実行される。"""

    logged = Signal(str)
    ready = Signal()
    preload_failed = Signal(str)
    preview_done = Signal(str)
    op_failed = Signal(str)
    build_progress = Signal(int, int, str, str)
    build_done = Signal(object)

    def __init__(self, config_path: str | None):
        super().__init__()
        self._config_path = config_path
        self._runner: WorkerRunner | None = None
        self._cfg: Config | None = None

    def _load_cfg(self) -> Config:
        if self._config_path and os.path.exists(self._config_path):
            return load_config(self._config_path)
        return Config()

    def _ensure(self) -> None:
        if self._runner is None:
            self._cfg = self._load_cfg()
            self._runner = WorkerRunner(self._cfg, log_fn=self.logged.emit)
            self._runner.start()

    @Slot()
    def preload(self) -> None:
        try:
            self._ensure()
            self.ready.emit()
        except Exception as e:  # noqa: BLE001
            self._runner = None
            self.preload_failed.emit(str(e))

    @Slot(str, str, str, str)
    def run_preview(self, text: str, lora: str, out: str, caption: str) -> None:
        try:
            self._ensure()
            assert self._runner is not None
            self._runner.infer(text, lora, out, caption=caption)
            self.preview_done.emit(out)
        except Exception as e:  # noqa: BLE001
            self.op_failed.emit(str(e))

    @Slot(object)
    def run_build(self, payload: dict) -> None:
        try:
            self._ensure()
            assert self._runner is not None and self._cfg is not None
            cfg = self._cfg
            scenario = read_scenario(payload["csv_path"], encoding=cfg.csv_encoding)
            builder = Builder(cfg, self._runner)
            result = builder.build(
                scenario,
                out_dir=payload.get("out_dir"),
                group_by_char=payload.get("group_by_char", False),
                force=payload.get("force", False),
                progress=lambda d, t, n, s: self.build_progress.emit(d, t, n, s),
            )
            dest = payload.get("out_dir") or cfg.voice_out_dir
            if payload.get("copy_csv"):
                os.makedirs(dest, exist_ok=True)
                shutil.copyfile(payload["csv_path"], os.path.join(dest, "scenario.csv"))
            self.build_done.emit({
                "generated": result.generated,
                "skipped": result.skipped,
                "failed": result.failed,
                "failures": list(result.failures),
                "out_dir": dest,
            })
        except Exception as e:  # noqa: BLE001
            self.op_failed.emit(str(e))

    @Slot()
    def shutdown(self) -> None:
        if self._runner is not None:
            self._runner.close()
            self._runner = None


class GenerationController(QObject):
    """メインスレッド側の窓口。リクエストを signal 経由でワーカースレッドへ渡す。"""

    _req_preload = Signal()
    _req_preview = Signal(str, str, str, str)
    _req_build = Signal(object)

    def __init__(self, config_path: str | None, parent: QObject | None = None):
        super().__init__(parent)
        self._thread = QThread()
        self._worker = _GenWorker(config_path)
        self._worker.moveToThread(self._thread)

        # 転送先スロット（QueuedConnection でワーカースレッド実行）
        self._req_preload.connect(self._worker.preload)
        self._req_preview.connect(self._worker.run_preview)
        self._req_build.connect(self._worker.run_build)

        # 外部が接続できるよう、ワーカーの signal をそのまま公開
        self.logged = self._worker.logged
        self.ready = self._worker.ready
        self.preload_failed = self._worker.preload_failed
        self.preview_done = self._worker.preview_done
        self.op_failed = self._worker.op_failed
        self.build_progress = self._worker.build_progress
        self.build_done = self._worker.build_done

        self._thread.start()

    # --- 要求 ---
    def preload(self) -> None:
        self._req_preload.emit()

    def preview(self, text: str, lora: str, out: str, caption: str = "") -> None:
        self._req_preview.emit(text, lora, out, caption)

    def build(self, payload: dict) -> None:
        self._req_build.emit(payload)

    def stop(self) -> None:
        """ワーカーの後片付け → スレッド停止。アプリ終了時に呼ぶ。"""
        try:
            # ワーカースレッド上で同期的に close させてから抜ける
            from PySide6.QtCore import QMetaObject
            QMetaObject.invokeMethod(self._worker, "shutdown", Qt.BlockingQueuedConnection)
        except Exception:  # noqa: BLE001
            pass
        self._thread.quit()
        self._thread.wait(15000)
