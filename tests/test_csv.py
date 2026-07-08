"""irodori_csv の単体テスト（標準ライブラリ unittest）。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from irodori_csv import (  # noqa: E402
    Character,
    Line,
    Scenario,
    assign_numbers,
    read_scenario,
    validate_scenario,
    write_scenario,
)
from irodori_csv.parser import ParseError, dumps_scenario  # noqa: E402


SAMPLE = (
    "キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド\n"
    "あかね,1,/lora/akane,akane_\n"
    "ゆい,2,/lora/yui,yui_\n"
    "\n"
    "参照番号,テキスト,送信テキスト\n"
    "1,こんにちは。,こんにちは。😊\n"
    "1,本当ですか？,本当ですか？😲\n"
    "2,おはよう。,おはよう。☀️\n"
    '2,"ふふっ、それはね、ひみつ。","ふふっ、ひみつ。😏"\n'
)


def _write_tmp(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
        f.write(content)
    return path


class TestParser(unittest.TestCase):
    def test_read_basic(self):
        path = _write_tmp(SAMPLE)
        sc = read_scenario(path)
        self.assertEqual(len(sc.characters), 2)
        self.assertEqual(len(sc.lines), 4)
        self.assertEqual(sc.characters[0].name, "あかね")
        self.assertEqual(sc.characters[0].head, "akane_")
        self.assertEqual(sc.lines[3].send_text, "ふふっ、ひみつ。😏")
        os.remove(path)

    def test_section_order_independent(self):
        swapped = (
            "参照番号,テキスト,送信テキスト\n"
            "1,こんにちは。,こんにちは。😊\n"
            "\n"
            "キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド\n"
            "あかね,1,/lora/akane,akane_\n"
        )
        path = _write_tmp(swapped)
        sc = read_scenario(path)
        self.assertEqual(len(sc.characters), 1)
        self.assertEqual(len(sc.lines), 1)
        os.remove(path)

    def test_quoted_newline(self):
        content = (
            "キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド\n"
            "あかね,1,/lora/akane,akane_\n"
            "\n"
            "参照番号,テキスト,送信テキスト\n"
            '1,"1行目\n2行目","1行目\n2行目😊"\n'
        )
        path = _write_tmp(content)
        sc = read_scenario(path)
        self.assertEqual(len(sc.lines), 1)
        self.assertIn("\n", sc.lines[0].send_text)
        os.remove(path)

    def test_missing_section(self):
        content = (
            "キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド\n"
            "あかね,1,/lora/akane,akane_\n"
        )
        path = _write_tmp(content)
        with self.assertRaises(ParseError):
            read_scenario(path)
        os.remove(path)

    def test_roundtrip(self):
        path = _write_tmp(SAMPLE)
        sc = read_scenario(path)
        out = path + ".out.csv"
        write_scenario(sc, out)
        sc2 = read_scenario(out)
        self.assertEqual(dumps_scenario(sc), dumps_scenario(sc2))
        os.remove(path)
        os.remove(out)


class TestNaming(unittest.TestCase):
    def test_assign_numbers(self):
        path = _write_tmp(SAMPLE)
        sc = read_scenario(path)
        a = assign_numbers(sc)
        names = [x.filename for x in a]
        self.assertEqual(names, ["akane_1.wav", "akane_2.wav", "yui_1.wav", "yui_2.wav"])
        os.remove(path)

    def test_no_zero_padding(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_")],
            lines=[Line("1", f"t{i}", f"t{i}") for i in range(12)],
        )
        a = assign_numbers(sc)
        self.assertEqual(a[8].filename, "a_9.wav")
        self.assertEqual(a[9].filename, "a_10.wav")
        self.assertEqual(a[11].filename, "a_12.wav")


class TestValidate(unittest.TestCase):
    def test_ok(self):
        sc = read_scenario(_write_tmp(SAMPLE))
        issues = validate_scenario(sc, check_lora_exists=False)
        self.assertEqual([i for i in issues if i.is_error], [])

    def test_duplicate_ref(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_"), Character("い", "1", "/l", "i_")],
            lines=[Line("1", "t", "t")],
        )
        issues = validate_scenario(sc, check_lora_exists=False)
        self.assertTrue(any("重複" in i.message and i.is_error for i in issues))

    def test_undefined_ref(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_")],
            lines=[Line("9", "t", "t")],
        )
        issues = validate_scenario(sc, check_lora_exists=False)
        self.assertTrue(any("定義にありません" in i.message for i in issues))

    def test_empty_text(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_")],
            lines=[Line("1", "", "")],
        )
        issues = validate_scenario(sc, check_lora_exists=False)
        self.assertTrue(any("空" in i.message and i.is_error for i in issues))

    def test_dup_charname_warning_when_grouping(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_"), Character("あ", "2", "/l", "b_")],
            lines=[Line("1", "t", "t"), Line("2", "t", "t")],
        )
        issues = validate_scenario(sc, check_lora_exists=False, group_by_char=True)
        self.assertTrue(any("キャラ名" in i.message and not i.is_error for i in issues))

    def test_fallback_text(self):
        # 送信テキストが空でも原文があれば TTS テキストは非空
        line = Line("1", "原文", "")
        self.assertEqual(line.tts_text(), "原文")


if __name__ == "__main__":
    unittest.main()
