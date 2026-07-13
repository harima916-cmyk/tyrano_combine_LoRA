"""検証ルール（SPEC §4.6）。CLI と GUI で共用。"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass

from .model import Scenario
from .naming import assign_numbers, sanitize_folder

# 出力名に使えない文字（ヘッド由来。パス区切りはヘッドの一部としては非対象だが
# ファイル名としては不正なのでチェックする）
_INVALID_FILENAME_CHARS = set('/\\:*?"<>|')


def _folder_map(scenario: Scenario) -> dict[str, str]:
    """group-by-char 用に、実際の出力と同じサブフォルダ名を算出する。"""
    bases = {c.ref: c.name if c.name.strip() else c.ref for c in scenario.characters}
    folder_counts = Counter(sanitize_folder(base) for base in bases.values())
    mapping: dict[str, str] = {}
    for c in scenario.characters:
        base = bases[c.ref]
        if folder_counts[sanitize_folder(base)] > 1:
            base = f"{base}_{c.ref}"
        mapping[c.ref] = sanitize_folder(base)
    return mapping


@dataclass
class Issue:
    level: str          # "error" | "warning"
    message: str
    section: str = ""   # "characters" | "lines" | ""
    index: int = -1     # セクション内の行インデックス（0 始まり、無い場合 -1）

    @property
    def is_error(self) -> bool:
        return self.level == "error"


def validate_scenario(
    scenario: Scenario,
    *,
    check_lora_exists: bool = True,
    group_by_char: bool = False,
) -> list[Issue]:
    """Scenario を検証し Issue のリストを返す（空ならエラーなし）。

    check_lora_exists: LoRA フォルダの実在をチェックするか（テスト時は False 可）。
    group_by_char:     キャラ名のサブフォルダ分割を前提に、キャラ名重複も警告するか。
    """
    issues: list[Issue] = []

    # --- キャラクター定義 ---
    seen_refs: dict[str, int] = {}
    seen_names: dict[str, int] = {}
    for i, c in enumerate(scenario.characters):
        if not c.ref.strip():
            issues.append(Issue("error", "参照番号が空です。", "characters", i))
        elif c.ref in seen_refs:
            issues.append(
                Issue("error", f"参照番号「{c.ref}」が重複しています。", "characters", i)
            )
        else:
            seen_refs[c.ref] = i

        if not c.head.strip():
            issues.append(Issue("warning", "生成ファイルヘッドが空です。", "characters", i))

        if check_lora_exists and c.lora_dir and not os.path.isdir(c.lora_dir):
            issues.append(
                Issue("warning", f"LoRAフォルダが見つかりません: {c.lora_dir}", "characters", i)
            )

        if group_by_char and c.name:
            if c.name in seen_names:
                issues.append(
                    Issue(
                        "warning",
                        f"キャラ名「{c.name}」が重複しています（サブフォルダが衝突します）。",
                        "characters",
                        i,
                    )
                )
            else:
                seen_names[c.name] = i

    # --- セリフ ---
    for i, line in enumerate(scenario.lines):
        if line.ref not in seen_refs:
            issues.append(
                Issue("error", f"参照番号「{line.ref}」は定義にありません。", "lines", i)
            )
        if not line.tts_text().strip():
            issues.append(
                Issue("error", "送信テキスト・原文がともに空です。", "lines", i)
            )

    # --- 出力名の重複・不正文字 ---
    names: dict[str, int] = {}
    folders = _folder_map(scenario) if group_by_char else {}
    for a in assign_numbers(scenario):
        if any(ch in _INVALID_FILENAME_CHARS for ch in a.filename):
            issues.append(
                Issue("error", f"出力名に不正な文字があります: {a.filename}", "lines")
            )
        name_key = os.path.join(folders[a.line.ref], a.filename) if folders else a.filename
        if name_key in names:
            issues.append(
                Issue("error", f"出力名「{name_key}」が重複しています。", "lines")
            )
        else:
            names[name_key] = 1

    return issues
