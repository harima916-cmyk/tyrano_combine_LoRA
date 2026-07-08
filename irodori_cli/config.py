"""config.yaml の読み込み（SPEC §5）。"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field

import yaml


@dataclass
class IrodoriConfig:
    repo_dir: str = ""
    runner: str = "python"
    checkpoint: str = "Aratako/Irodori-TTS-500M-v3"
    num_steps: int | None = 32
    seconds: float | None = None
    # 話者の与え方（話者条件付き checkpoint は必須）。LoRA 運用は通常 "no-ref"。
    #   no-ref | ref-wav | ref-embed | ref-latent | none
    ref_mode: str = "no-ref"
    ref_path: str | None = None  # ref-wav/embed/latent のとき渡すファイル
    # 実行デバイス / 精度。None なら infer.py の既定に任せる。
    device: str | None = None      # "cuda" | "cpu" | "cuda:0" 等
    precision: str | None = None   # "bf16" | "fp32"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class Config:
    csv_file: str = "scenario.csv"
    voice_out_dir: str = "voices"
    preview_dir: str = "preview"
    cache_dir: str = ".irodori_cache"
    state_file: str = ".irodori_state.json"
    csv_encoding: str = "utf-8-sig"
    on_empty_text: str = "skip"
    irodori: IrodoriConfig = field(default_factory=IrodoriConfig)

    def tts_params_signature(self) -> str:
        """キャッシュ鍵に含める TTS パラメータの正規化文字列（SPEC §6.2）。"""
        parts = [
            self.irodori.checkpoint,
            f"steps={self.irodori.num_steps}",
            f"seconds={self.irodori.seconds}",
            "args=" + " ".join(self.irodori.extra_args),
        ]
        return "\x1f".join(parts)


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    project = data.get("project", {}) or {}
    csv_sec = data.get("csv", {}) or {}
    ir = data.get("irodori", {}) or {}

    extra = ir.get("extra_args", []) or []
    if isinstance(extra, str):
        extra = shlex.split(extra)

    return Config(
        csv_file=project.get("csv_file", "scenario.csv"),
        voice_out_dir=project.get("voice_out_dir", "voices"),
        preview_dir=project.get("preview_dir", "preview"),
        cache_dir=project.get("cache_dir", ".irodori_cache"),
        state_file=project.get("state_file", ".irodori_state.json"),
        csv_encoding=csv_sec.get("encoding", "utf-8-sig"),
        on_empty_text=data.get("on_empty_text", "skip"),
        irodori=IrodoriConfig(
            repo_dir=ir.get("repo_dir", ""),
            runner=ir.get("runner", "python"),
            checkpoint=ir.get("checkpoint", "Aratako/Irodori-TTS-500M-v3"),
            num_steps=ir.get("num_steps", 32),
            seconds=ir.get("seconds", None),
            ref_mode=ir.get("ref_mode", "no-ref"),
            ref_path=ir.get("ref_path", None),
            device=ir.get("device", None),
            precision=ir.get("precision", None),
            extra_args=list(extra),
        ),
    )


def default_config() -> Config:
    return Config()
