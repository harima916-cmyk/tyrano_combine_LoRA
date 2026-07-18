"""常駐ワーカー（irodori_worker.py）を起動・再利用するクライアント。

`InferRunner` が「1行ごとに infer.py を起動 → 毎回モデルロード」なのに対し、
`WorkerRunner` は **ワーカーを1回だけ起動してモデルを常駐**させ、以後は
JSON ジョブを送るだけで生成する。お試し生成・一括生成の両方で使える。

TTSRunner プロトコル（infer）に加え、明示的な close() を持つ。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from typing import Callable

from .config import Config

READY = "@@IRODORI_READY@@"
RESULT = "@@IRODORI_RESULT@@"
FATAL = "@@IRODORI_FATAL@@"
QUIT = "@@QUIT@@"

LogFn = Callable[[str], None]


def _worker_script() -> str:
    """リポジトリ直下の irodori_worker.py の絶対パス。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "irodori_worker.py")


class WorkerError(RuntimeError):
    pass


class WorkerRunner:
    """モデルを常駐させて複数ジョブを生成するランナー。

    最初の infer()／明示 start() でワーカーを起動しモデルをロードする。
    generation ごとの再ロードは発生しない。使い終わったら close() する。
    """

    def __init__(self, config: Config, log_fn: LogFn | None = None,
                 worker_script: str | None = None):
        self.config = config
        self.log_fn = log_fn or (lambda _m: None)
        self._script = worker_script or _worker_script()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # --- ライフサイクル ---
    def repo_cwd(self) -> str | None:
        rd = self.config.irodori.repo_dir
        return os.path.abspath(rd) if rd else None

    def _startup_command(self) -> list[str]:
        ir = self.config.irodori
        cmd = shlex.split(ir.runner) + [self._script]
        # checkpoint は SPEC 既定と同様 --hf-checkpoint 前提（ローカルなら extra 側で調整可）
        cmd += ["--hf-checkpoint", ir.checkpoint]
        if ir.device:
            cmd += ["--model-device", ir.device, "--codec-device", ir.device]
        if ir.precision:
            cmd += ["--model-precision", ir.precision, "--codec-precision", ir.precision]
        if ir.num_steps is not None:
            cmd += ["--num-steps", str(ir.num_steps)]
        if ir.seconds is not None:
            cmd += ["--seconds", str(ir.seconds)]
        mode = (ir.ref_mode or "none").strip()
        if mode == "no-ref":
            cmd += ["--no-ref"]
        return cmd

    def start(self) -> None:
        """ワーカーを起動しモデルロード完了（READY）まで待つ。既に起動済みなら何もしない。"""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            cmd = self._startup_command()
            self.log_fn("モデルを読み込み中…（初回のみ時間がかかります）")
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,  # 行バッファ
                    cwd=self.repo_cwd(),
                )
            except OSError as e:
                raise WorkerError(f"ワーカーを起動できません: {e}") from e

            # READY を待つ。それ以外の行（モデルログ）はログへ流す。
            assert self._proc.stdout is not None
            for raw in self._proc.stdout:
                line = raw.rstrip("\n")
                if line == READY:
                    self.log_fn("モデルの準備ができました。")
                    return
                if line.startswith(FATAL):
                    self._kill_current()
                    raise WorkerError(line[len(FATAL):].strip() or "ワーカーが致命的エラーで終了しました。")
                if line.strip():
                    self.log_fn(line)
            # stdout が尽きた＝READY 前に死んだ
            code = self._proc.poll()
            self._kill_current()
            raise WorkerError(f"ワーカーが準備完了前に終了しました（code={code}）。")

    def _kill_current(self) -> None:
        """_proc を終了させストリームを閉じて None にする（ロック保持前提）。"""
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        except OSError:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except (OSError, ValueError):
                pass

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # --- 生成（TTSRunner 互換）---
    def infer(self, text: str, lora_dir: str, out_wav: str) -> None:
        out_wav = os.path.abspath(out_wav)
        with self._lock:
            if not self._is_alive():
                # start() は再入不可のロック内で呼べないので、ここでは直接起動フローへ
                pass
        if not self._is_alive():
            self.start()

        with self._lock:
            if not self._is_alive():
                raise WorkerError("ワーカーが停止しています。")
            proc = self._proc
            assert proc is not None and proc.stdin is not None and proc.stdout is not None

            job = {"text": text, "lora": lora_dir or None, "out": out_wav}
            proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
            proc.stdin.flush()

            # RESULT 行を待つ。それ以外はログへ。
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if line.startswith(RESULT):
                    payload = json.loads(line[len(RESULT):].strip())
                    if not payload.get("ok"):
                        raise WorkerError(payload.get("error") or "生成に失敗しました。")
                    self._check_output(out_wav)
                    return
                if line.startswith(FATAL):
                    raise WorkerError(line[len(FATAL):].strip() or "ワーカーが致命的エラーで終了しました。")
                if line.strip():
                    self.log_fn(line)
            raise WorkerError("ワーカーが応答を返す前に終了しました。")

    @staticmethod
    def _check_output(out_wav: str) -> None:
        if not os.path.exists(out_wav):
            raise WorkerError(f"出力が生成されませんでした: {out_wav}")
        size = os.path.getsize(out_wav)
        if size < 128:
            try:
                os.remove(out_wav)
            except OSError:
                pass
            raise WorkerError(f"出力が異常に小さい（{size} bytes）。生成に失敗した可能性があります。")

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin is not None:
                try:
                    proc.stdin.write(QUIT + "\n")
                    proc.stdin.flush()
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.terminate()
        finally:
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except (OSError, ValueError):
                    pass

    def __enter__(self) -> "WorkerRunner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
