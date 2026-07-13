"""差分ビルド・キャッシュ・フォルダ出力（SPEC §6-§8）。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from irodori_csv import Scenario, assign_numbers
from irodori_csv.naming import LineAssignment, sanitize_folder

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


def _folder_map(scenario: Scenario) -> dict[str, str]:
    """group-by-char 用に 参照番号 -> サブフォルダ名 を作る。

    サニタイズ後のフォルダ名が重複する場合は「キャラ名_参照番号」で分離する
    （SPEC §build --group-by-char）。
    """
    bases = {c.ref: c.name if c.name.strip() else c.ref for c in scenario.characters}
    folder_counts = Counter(sanitize_folder(base) for base in bases.values())
    mapping: dict[str, str] = {}
    for c in scenario.characters:
        base = bases[c.ref]
        if folder_counts[sanitize_folder(base)] > 1:
            base = f"{base}_{c.ref}"
        mapping[c.ref] = sanitize_folder(base)
    return mapping


def _relative_output_path(a: LineAssignment, folders: dict[str, str]) -> str:
    """state / progress / failure 表示に使う出力相対パスを返す。"""
    if folders:
        return os.path.join(folders[a.line.ref], a.filename)
    return a.filename


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

    def ensure_cached(self, assignment: LineAssignment) -> str:
        """キャッシュに音声を用意し、その wav パスを返す（無ければ infer 実行）。"""
        text = assignment.line.tts_text()
        h = line_hash(text, assignment.line.ref, assignment.character.lora_dir, self.tts_params)
        cache_wav = self._cache_path(h)
        if not os.path.exists(cache_wav):
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
        folders = _folder_map(scenario) if group_by_char else {}

        assignments = assign_numbers(scenario)
        if chars is not None:
            assignments = [a for a in assignments if a.line.ref in chars]

        result = BuildResult()

        # 空テキストの扱い
        filtered: list[LineAssignment] = []
        for a in assignments:
            if not a.line.tts_text().strip():
                if self.config.on_empty_text == "error":
                    result.failed += 1
                    result.failures.append(
                        (
                            _relative_output_path(a, folders),
                            f"送信テキスト・原文がともに空です: 参照番号={a.line.ref}",
                        )
                    )
                continue  # skip
            filtered.append(a)

        state = _load_state(self.config.state_file)
        total = len(filtered)

        for done, a in enumerate(filtered, start=1):
            rel_path = _relative_output_path(a, folders)
            target = os.path.join(base_dir, rel_path)

            h = self._hash_of(a)
            up_to_date = (
                not force
                and os.path.exists(target)
                and state.get(rel_path) == h
            )
            if up_to_date:
                result.skipped += 1
                if progress:
                    progress(done, total, rel_path, "SKIPPED")
                continue

            try:
                cache_wav = self.ensure_cached(a)
                os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
                shutil.copyfile(cache_wav, target)
                state[rel_path] = h
                result.generated += 1
                if progress:
                    progress(done, total, rel_path, "GENERATED")
            except Exception as e:  # noqa: BLE001 - 個別行の失敗は記録して継続
                result.failed += 1
                result.failures.append((rel_path, str(e)))
                if progress:
                    progress(done, total, rel_path, "FAILED")

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
