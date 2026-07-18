#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Irodori-TTS 常駐生成ワーカー。

モデル（ベース + codec）を **起動時に1回だけロード**し、以後は標準入力から
JSON ジョブを1行ずつ受け取って `runtime.synthesize()` で生成する。
LoRA はジョブごとに差し替えるだけでベースモデルは再ロードしない。

これにより、行数ぶん infer.py を起動して毎回モデルをロードしていた従来方式の
「毎回ロード」オーバーヘッドを解消する。

このスクリプトは **Irodori-TTS 側の venv / cwd** で実行する前提（`import irodori_tts`
が通る環境）。tyrano 側のモジュールには一切依存しない。

--- プロトコル（stdout に行単位・マーカー付きで出力）---
  起動完了            : @@IRODORI_READY@@
  1ジョブ完了/失敗    : @@IRODORI_RESULT@@ {"id":..., "ok":true/false, "out":..., "error":...}
  致命的エラーで終了  : @@IRODORI_FATAL@@ <message>
上記マーカー以外の行（モデルのログ等）はそのまま流れるので、呼び出し側は
マーカー行だけを解釈し、それ以外はログとして扱えばよい。

--- 入力ジョブ（stdin、1行1 JSON）---
  {"id": "任意", "text": "セリフ", "lora": "LoRAフォルダ or null", "out": "出力wavパス",
   "num_steps": 32(省略可), "seconds": null(省略可)}
  空行は無視。 "@@QUIT@@" という行、または EOF で終了。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

READY = "@@IRODORI_READY@@"
RESULT = "@@IRODORI_RESULT@@"
FATAL = "@@IRODORI_FATAL@@"
QUIT = "@@QUIT@@"


def _eprint(*a):
    print(*a, file=sys.stderr, flush=True)


def _emit(line: str):
    # stdout はプロトコル用。必ず flush して即座に呼び出し側へ届ける。
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _resolve_checkpoint_path(hf_checkpoint: str | None, checkpoint: str | None) -> str:
    """infer.py の _resolve_checkpoint_path と同じ解決規則。"""
    from pathlib import Path

    if checkpoint:
        p = Path(str(checkpoint)).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Checkpoint not found: {p}")
        return str(p)
    repo_id = str(hf_checkpoint or "").strip()
    if not repo_id:
        raise ValueError("--hf-checkpoint か --checkpoint のどちらかが必要です。")
    from huggingface_hub import hf_hub_download

    return str(hf_hub_download(repo_id=repo_id, filename="model.safetensors"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Irodori-TTS 常駐生成ワーカー")
    # ランタイム（起動時に1回だけ使う）
    ap.add_argument("--hf-checkpoint", default=None)
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--codec-repo", default="Aratako/Semantic-DACVAE-Japanese-32dim")
    ap.add_argument("--model-device", default=None)
    ap.add_argument("--codec-device", default=None)
    ap.add_argument("--model-precision", default="fp32", choices=["fp32", "bf16"])
    ap.add_argument("--codec-precision", default="fp32", choices=["fp32", "bf16"])
    # 生成の既定（ジョブ側で上書き可）
    ap.add_argument("--num-steps", type=int, default=32)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--no-ref", action="store_true")
    args = ap.parse_args()

    try:
        from irodori_tts.inference_runtime import (
            InferenceRuntime,
            RuntimeKey,
            SamplingRequest,
            default_runtime_device,
            save_wav,
        )
    except Exception as e:  # noqa: BLE001
        _emit(f"{FATAL} irodori_tts をインポートできません（Irodori-TTS の環境/cwd で実行してください）: {e}")
        traceback.print_exc()
        return 3

    model_device = args.model_device or default_runtime_device()
    # codec も既定でモデルと同じデバイス（GPUなら codec も GPU に載せて速くする）
    codec_device = args.codec_device or model_device

    # ---- モデルロード（1回だけ）----
    try:
        checkpoint_path = _resolve_checkpoint_path(args.hf_checkpoint, args.checkpoint)
        key = RuntimeKey(
            checkpoint=checkpoint_path,
            model_device=str(model_device),
            codec_repo=str(args.codec_repo),
            model_precision=str(args.model_precision),
            codec_device=str(codec_device),
            codec_precision=str(args.codec_precision),
        )
        _eprint(f"[worker] loading model on {model_device} (codec:{codec_device}) ...")
        runtime = InferenceRuntime.from_key(key)
    except Exception as e:  # noqa: BLE001
        _emit(f"{FATAL} モデルのロードに失敗しました: {e}")
        traceback.print_exc()
        return 4

    _eprint("[worker] ready.")
    _emit(READY)  # ← 呼び出し側はこの行を待って「準備完了」とする

    # ---- ジョブループ ----
    default_num_steps = int(args.num_steps)
    default_seconds = args.seconds
    default_no_ref = bool(args.no_ref)

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == QUIT:
            break
        job_id = None
        out_path = None
        try:
            job = json.loads(line)
            job_id = job.get("id")
            text = str(job.get("text", ""))
            lora = job.get("lora")
            out_path = job.get("out")
            if not out_path:
                raise ValueError("ジョブに 'out'（出力wavパス）がありません。")
            num_steps = int(job.get("num_steps", default_num_steps))
            seconds = job.get("seconds", default_seconds)
            no_ref = bool(job.get("no_ref", default_no_ref))

            req = SamplingRequest(
                text=text,
                no_ref=no_ref,
                num_steps=num_steps,
                seconds=None if seconds is None else float(seconds),
                lora_adapter=None if not lora else str(lora),
            )
            result = runtime.synthesize(req)
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
            saved = save_wav(out_path, result.audio, result.sample_rate)
            _emit(f"{RESULT} " + json.dumps(
                {"id": job_id, "ok": True, "out": str(saved)}, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001 - 1ジョブの失敗ではワーカーを落とさない
            _eprint("[worker] job failed:\n" + traceback.format_exc())
            _emit(f"{RESULT} " + json.dumps(
                {"id": job_id, "ok": False, "out": out_path, "error": str(e)},
                ensure_ascii=False))

    _eprint("[worker] shutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
