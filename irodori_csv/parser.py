"""2 セクション CSV の読み書き（SPEC §4）。

1 ファイル内に「キャラクター定義」「セリフ」の 2 セクションを持ち、空行で区切る。
各セクションはヘッダ行を持ち、ヘッダ列名でセクションを識別する（順序不問）。
"""

from __future__ import annotations

import csv
import io

from .model import (
    CHAR_HEADERS,
    CHAR_MARKER,
    LINE_HEADERS,
    LINE_MARKER,
    Character,
    Line,
    Scenario,
)


class ParseError(Exception):
    """CSV が SPEC §4 の形式に準拠しない場合に送出。"""


def _is_blank(row: list[str]) -> bool:
    return len(row) == 0 or all((c or "").strip() == "" for c in row)


def _split_blocks(rows: list[list[str]]) -> list[list[list[str]]]:
    """空行を区切りに行をブロックへ分割する。"""
    blocks: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for row in rows:
        if _is_blank(row):
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(row)
    if cur:
        blocks.append(cur)
    return blocks


def _rows_to_dicts(block: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    header = [h.strip() for h in block[0]]
    records: list[dict[str, str]] = []
    for row in block[1:]:
        # 足りない列は空文字で補完、余剰は切り捨て
        values = list(row) + [""] * (len(header) - len(row))
        records.append({header[i]: (values[i] or "").strip() for i in range(len(header))})
    return header, records


def read_scenario(path: str, encoding: str = "utf-8-sig") -> Scenario:
    """CSV を読み込み Scenario を返す。準拠しない場合は ParseError。"""
    with open(path, "r", encoding=encoding, newline="") as f:
        rows = list(csv.reader(f))

    blocks = _split_blocks(rows)
    if not blocks:
        raise ParseError("CSV が空です。")

    scenario = Scenario()
    seen_char = seen_line = False

    for block in blocks:
        header, records = _rows_to_dicts(block)
        if CHAR_MARKER in header:
            if seen_char:
                raise ParseError("キャラクター定義セクションが複数あります。")
            seen_char = True
            for r in records:
                scenario.characters.append(
                    Character(
                        name=r.get("キャラ名", ""),
                        ref=r.get("参照番号", ""),
                        lora_dir=r.get("LoRAフォルダ", ""),
                        head=r.get("生成ファイルヘッド", ""),
                    )
                )
        elif LINE_MARKER in header:
            if seen_line:
                raise ParseError("セリフセクションが複数あります。")
            seen_line = True
            for r in records:
                scenario.lines.append(
                    Line(
                        ref=r.get("参照番号", ""),
                        text=r.get("テキスト", ""),
                        send_text=r.get("送信テキスト", ""),
                    )
                )
        else:
            raise ParseError(
                "セクションを識別できません。ヘッダに "
                f"'{CHAR_MARKER}' か '{LINE_MARKER}' が必要です: {header}"
            )

    if not seen_char:
        raise ParseError("キャラクター定義セクションがありません。")
    if not seen_line:
        raise ParseError("セリフセクションがありません。")
    return scenario


def dumps_scenario(scenario: Scenario) -> str:
    """Scenario を SPEC §4 形式の CSV 文字列へ直列化する。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    writer.writerow(CHAR_HEADERS)
    for c in scenario.characters:
        writer.writerow([c.name, c.ref, c.lora_dir, c.head])

    writer.writerow([])  # セクション区切りの空行

    writer.writerow(LINE_HEADERS)
    for line in scenario.lines:
        writer.writerow([line.ref, line.text, line.send_text])

    return buf.getvalue()


def write_scenario(scenario: Scenario, path: str, encoding: str = "utf-8-sig") -> None:
    """Scenario を CSV ファイルへ書き出す。"""
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(dumps_scenario(scenario))
