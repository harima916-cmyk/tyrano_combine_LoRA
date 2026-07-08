"""出力ファイル名の算出（SPEC §4.4）。

- ファイル名 = 生成ファイルヘッド + 連番 + ".wav"
- 連番はキャラごとに、セリフの出現順で 1 から。ゼロ埋めしない（tyrano 互換）。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .model import Character, Line, Scenario

# OS で使えない文字（サブフォルダ名などのサニタイズ用）
_INVALID_CHARS = re.compile(r'[/\\:*?"<>|]')


def output_name(head: str, seq: int) -> str:
    """出力ファイル名を返す。例: head='akane_', seq=1 -> 'akane_1.wav'。"""
    return f"{head}{seq}.wav"


def sanitize_folder(name: str) -> str:
    """サブフォルダ名から OS 不正文字を '_' に置換する（SPEC §build --group-by-char）。"""
    return _INVALID_CHARS.sub("_", name).strip() or "_"


def folder_name_map(scenario: Scenario) -> dict[str, str]:
    """--group-by-char 用に 参照番号 -> サブフォルダ名 を作る（CLI/検証で共用）。

    サブフォルダ名は原則キャラ名。キャラ名が空なら参照番号を使う。
    キャラ名が重複する場合は「キャラ名_参照番号」で分離する（SPEC §build --group-by-char）。
    """
    name_counts = Counter(c.name for c in scenario.characters)
    mapping: dict[str, str] = {}
    for c in scenario.characters:
        base = c.name if c.name.strip() else c.ref
        if c.name.strip() and name_counts[c.name] > 1:
            base = f"{base}_{c.ref}"
        mapping[c.ref] = sanitize_folder(base)
    return mapping


def relative_output_path(
    filename: str, ref: str, group_by_char: bool, folders: dict[str, str] | None
) -> str:
    """出力相対パスを返す（SPEC §6.2）。

    - フラット配置: `akane_1.wav`
    - --group-by-char: `あかね/akane_1.wav`
    state のキー・重複判定の単位に用いる（区切りは常に '/'）。
    """
    if group_by_char and folders is not None:
        return f"{folders.get(ref, '_')}/{filename}"
    return filename


@dataclass
class LineAssignment:
    """1 セリフに対する採番結果。"""

    line: Line
    character: Character
    seq: int            # キャラ内連番（1 始まり）
    filename: str       # 出力ファイル名（ヘッド + 連番 + .wav）


def assign_numbers(scenario: Scenario) -> list[LineAssignment]:
    """全セリフにキャラ別連番と出力名を割り当てる。

    定義に存在しない参照番号のセリフはスキップする（検証は validate 側の責務）。
    """
    counters: dict[str, int] = {}
    result: list[LineAssignment] = []
    for line in scenario.lines:
        char = scenario.character_by_ref(line.ref)
        if char is None:
            continue
        counters[line.ref] = counters.get(line.ref, 0) + 1
        seq = counters[line.ref]
        result.append(
            LineAssignment(
                line=line,
                character=char,
                seq=seq,
                filename=output_name(char.head, seq),
            )
        )
    return result
