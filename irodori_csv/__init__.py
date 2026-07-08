"""シナリオCSVの共有ライブラリ（CLI と GUI で共用）。

- model:    Character / Line / Scenario のデータモデル
- parser:   2 セクション CSV の読み書き
- naming:   出力ファイル名（ヘッド + 連番 + .wav）の算出
- validate: SPEC §4.6 の検証ルール
"""

from .model import Character, Line, Scenario
from .naming import (
    output_name,
    assign_numbers,
    LineAssignment,
    folder_name_map,
    relative_output_path,
    sanitize_folder,
)
from .parser import read_scenario, write_scenario, ParseError
from .validate import validate_scenario, Issue

__all__ = [
    "Character",
    "Line",
    "Scenario",
    "output_name",
    "assign_numbers",
    "LineAssignment",
    "folder_name_map",
    "relative_output_path",
    "sanitize_folder",
    "read_scenario",
    "write_scenario",
    "ParseError",
    "validate_scenario",
    "Issue",
]
