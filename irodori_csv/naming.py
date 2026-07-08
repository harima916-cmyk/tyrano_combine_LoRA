"""出力ファイル名の算出（SPEC §4.4）。

- ファイル名 = 生成ファイルヘッド + 連番 + ".wav"
- 連番はキャラごとに、セリフの出現順で 1 から。ゼロ埋めしない（tyrano 互換）。
"""

from __future__ import annotations

import re
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
