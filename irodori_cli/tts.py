"""Irodori-TTS の infer.py を呼び出すランナー（SPEC §6.1）。

テスト容易性のため、実処理を行う InferRunner と、差し替え可能なプロトコルに分ける。
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Protocol

from .config import Config


class TTSRunner(Protocol):
    def infer(self, text: str, lora_dir: str, out_wav: str) -> None:
        """text を lora_dir の LoRA で音声化し out_wav（.wav）へ書き出す。失敗時は例外。"""
        ...


class InferRunner:
    """config を元に infer.py をサブプロセス実行する本番ランナー。"""

    def __init__(self, config: Config):
        self.config = config

    def repo_cwd(self) -> str | None:
        """infer.py を実行する作業ディレクトリ（Irodori-TTS リポジトリ）。

        `uv run` はカレントディレクトリのプロジェクト環境を使うため、必ず repo_dir を
        カレントにして実行する。ここが tyrano 側だと依存（huggingface_hub 等）が無く失敗する。
        """
        return os.path.abspath(self.config.irodori.repo_dir) if self.config.irodori.repo_dir else None

    def build_command(self, text: str, lora_dir: str, out_wav: str) -> list[str]:
        ir = self.config.irodori
        # cwd を repo_dir にするため、infer.py と出力先は絶対パスに固定する。
        infer_py = os.path.abspath(os.path.join(ir.repo_dir, "infer.py")) if ir.repo_dir else "infer.py"
        cmd = shlex.split(ir.runner) + [
            infer_py,
            "--hf-checkpoint", ir.checkpoint,
            "--text", text,
            "--lora-adapter", os.path.abspath(lora_dir) if lora_dir else lora_dir,
            "--output-wav", os.path.abspath(out_wav),
        ]
        # 話者の与え方（話者条件付き checkpoint は必須。LoRA 運用は通常 --no-ref）
        mode = (ir.ref_mode or "none").strip()
        if mode == "no-ref":
            cmd += ["--no-ref"]
        elif mode in ("ref-wav", "ref-embed", "ref-latent") and ir.ref_path:
            cmd += [f"--{mode}", os.path.abspath(ir.ref_path)]
        # mode == "none" の場合は付けない（extra_args で自前指定する想定）
        if ir.device:
            cmd += ["--model-device", ir.device, "--codec-device", ir.device]
        if ir.precision:
            cmd += ["--model-precision", ir.precision, "--codec-precision", ir.precision]
        if ir.num_steps is not None:
            cmd += ["--num-steps", str(ir.num_steps)]
        if ir.seconds is not None:
            cmd += ["--seconds", str(ir.seconds)]
        cmd += list(ir.extra_args)
        return cmd

    def infer(self, text: str, lora_dir: str, out_wav: str) -> None:
        out_wav = os.path.abspath(out_wav)
        os.makedirs(os.path.dirname(out_wav), exist_ok=True)
        cmd = self.build_command(text, lora_dir, out_wav)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.repo_cwd(),  # ★ Irodori-TTS リポジトリをカレントにして実行
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            hint = ""
            if "ModuleNotFoundError" in stderr or "No module named" in stderr:
                hint = (
                    "\nヒント: Irodori-TTS 側の依存が入っていない可能性があります。"
                    f"\n  1) '{self.repo_cwd()}' で通常どおり infer.py が動くか確認してください。"
                    "\n  2) その環境の起動コマンドを config.yaml の irodori.runner に設定してください"
                    "（例: 'uv run python' / '<Irodori-TTSのvenv>/Scripts/python.exe'）。"
                )
            raise RuntimeError(
                f"infer.py failed (code {proc.returncode}).\n"
                f"cmd: {' '.join(shlex.quote(c) for c in cmd)}\n"
                f"cwd: {self.repo_cwd()}\n"
                f"stderr: {stderr}{hint}"
            )
        if not os.path.exists(out_wav):
            raise RuntimeError(f"infer.py が出力を生成しませんでした: {out_wav}")
        # 壊れ/空ファイルをキャッシュしないための下限チェック（正常な wav は数KB以上）
        size = os.path.getsize(out_wav)
        if size < 128:
            try:
                os.remove(out_wav)
            except OSError:
                pass
            raise RuntimeError(
                f"infer.py の出力が異常に小さい（{size} bytes）。生成に失敗した可能性があります: {out_wav}\n"
                f"stdout: {(proc.stdout or '').strip()[-500:]}"
            )
