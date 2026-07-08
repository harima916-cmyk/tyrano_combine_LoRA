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

    def build_command(self, text: str, lora_dir: str, out_wav: str) -> list[str]:
        ir = self.config.irodori
        infer_py = os.path.join(ir.repo_dir, "infer.py") if ir.repo_dir else "infer.py"
        cmd = shlex.split(ir.runner) + [
            infer_py,
            "--hf-checkpoint", ir.checkpoint,
            "--text", text,
            "--lora-adapter", lora_dir,
            "--output-wav", out_wav,
        ]
        if ir.num_steps is not None:
            cmd += ["--num-steps", str(ir.num_steps)]
        if ir.seconds is not None:
            cmd += ["--seconds", str(ir.seconds)]
        cmd += list(ir.extra_args)
        return cmd

    def infer(self, text: str, lora_dir: str, out_wav: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        cmd = self.build_command(text, lora_dir, out_wav)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"infer.py failed (code {proc.returncode}).\n"
                f"cmd: {' '.join(shlex.quote(c) for c in cmd)}\n"
                f"stderr: {proc.stderr.strip()}"
            )
        if not os.path.exists(out_wav):
            raise RuntimeError(f"infer.py が出力を生成しませんでした: {out_wav}")
