"""emoji_palette.tsv の読み込み（GUI_SPEC 付録 B）。

TSV 列: emoji / meaning_ja / meaning_en / category / example
（category / example は無くても動作する）
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EmojiEntry:
    emoji: str
    meaning_ja: str
    meaning_en: str
    category: str = ""
    example: str = ""


def _default_path() -> str:
    # リポジトリ直下の emoji_palette.tsv
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "emoji_palette.tsv")


def load_emoji_palette(path: str | None = None) -> list[EmojiEntry]:
    path = path or _default_path()
    entries: list[EmojiEntry] = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        cols = line.split("\t")
        if i == 0 and cols[:1] == ["emoji"]:
            continue  # ヘッダ
        emoji = cols[0] if len(cols) > 0 else ""
        ja = cols[1] if len(cols) > 1 else ""
        en = cols[2] if len(cols) > 2 else ""
        category = cols[3] if len(cols) > 3 else ""
        example = cols[4] if len(cols) > 4 else ""
        if emoji:
            entries.append(EmojiEntry(emoji, ja, en, category, example))
    return entries
