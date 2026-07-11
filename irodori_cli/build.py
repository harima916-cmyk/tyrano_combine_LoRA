"""差分ビルド・キャッシュ・フォルダ出力（SPEC §6-§8）。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable

from irodori_csv import Scenario, assign_numbers
from irodori_csv.naming import LineAssignment, folder_name_map, relative_output_path

from .config import Config
from .tts import TTSRunner


def line_hash(send_text: str, ref: str, lora_dir: str, tts_params: str) -> str:
    """キャッシュ鍵（SPEC §6.2）。"""
    payload = "\x00".join([send_text, ref, lora_dir, tts_params])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_state(path: str) -> dict[str, str]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(path: str, state: dict[str, str]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


@dataclass
class BuildResult:
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)  # (filename, error)


ProgressFn = Callable[[int, int, str, str], None]


class Builder:
    def __init__(self, config: Config, runner: TTSRunner):
        self.config = config
        self.runner = runner
        self.tts_params = config.tts_params_signature()

    # --- キャッシュ ---
    def _cache_path(self, h: str) -> str:
        return os.path.join(self.config.cache_dir, f"{h}.wav")

    def ensure_cached(self, assignment: LineAssignment, force: bool = False) -> str:
        """キャッシュに音声を用意し、その wav パスを返す。

        force=True のときはキャッシュがあっても infer を再実行して作り直す。
        """
        text = assignment.line.tts_text()
        h = line_hash(text, assignment.line.ref, assignment.character.lora_dir, self.tts_params)
        cache_wav = self._cache_path(h)
        if force or not os.path.exists(cache_wav):
            os.makedirs(self.config.cache_dir, exist_ok=True)
            self.runner.infer(text, assignment.character.lora_dir, cache_wav)
        return cache_wav

    def _hash_of(self, a: LineAssignment) -> str:
        return line_hash(
            a.line.tts_text(), a.line.ref, a.character.lora_dir, self.tts_params
        )

    def build(
        self,
        scenario: Scenario,
        *,
        out_dir: str | None = None,
        group_by_char: bool = False,
        force: bool = False,
        chars: set[str] | None = None,
        progress: ProgressFn | None = None,
    ) -> BuildResult:
        base_dir = out_dir or self.config.voice_out_dir
        folders = folder_name_map(scenario) if group_by_char else None

        assignments = assign_numbers(scenario)
        if chars is not None:
            assignments = [a for a in assignments if a.line.ref in chars]

        # 空テキスト行の扱い（例外は投げず、skip / 失敗記録で処理）
        work: list[tuple[LineAssignment, bool]] = []  # (assignment, is_empty_error)
        for a in assignments:
            if not a.line.tts_text().strip():
                if self.config.on_empty_text == "error":
                    work.append((a, True))
                # skip の場合は生成対象から外す（total にも含めない）
                continue
            work.append((a, False))

        state = _load_state(self.config.state_file)
        result = BuildResult()
        total = len(work)

        for done, (a, is_empty_error) in enumerate(work, start=1):
            rel = relative_output_path(a.filename, a.line.ref, group_by_char, folders)
            target = os.path.join(base_dir, *rel.split("/"))

            if is_empty_error:
                result.failed += 1
                result.failures.append((rel, "送信テキストが空です（on_empty_text=error）。"))
                if progress:
                    progress(done, total, rel, "FAILED")
                continue

            h = self._hash_of(a)
            up_to_date = (
                not force
                and os.path.exists(target)
                and state.get(rel) == h
            )
            if up_to_date:
                result.skipped += 1
                if progress:
                    progress(done, total, rel, "SKIPPED")
                continue

            try:
                cache_wav = self.ensure_cached(a, force=force)
                os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
                shutil.copyfile(cache_wav, target)
                state[rel] = h
                result.generated += 1
                if progress:
                    progress(done, total, rel, "GENERATED")
            except Exception as e:  # noqa: BLE001 - 個別行の失敗は記録して継続
                result.failed += 1
                result.failures.append((rel, str(e)))
                if progress:
                    progress(done, total, rel, "FAILED")

        _save_state(self.config.state_file, state)
        return result

    def preview(self, text: str, lora_dir: str, out_wav: str) -> str:
        """CSV/state を介さず 1 件生成（キャッシュは共有）。SPEC preview。"""
        h = line_hash(text, "", lora_dir, self.tts_params)
        cache_wav = self._cache_path(h)
        if not os.path.exists(cache_wav):
            os.makedirs(self.config.cache_dir, exist_ok=True)
            self.runner.infer(text, lora_dir, cache_wav)
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        shutil.copyfile(cache_wav, out_wav)
        return out_wav
