"""v4 キャプション機能のテスト（CSV往復・フォールバック・キャッシュ鍵・コマンド生成）。"""

import os
import tempfile
import unittest

from irodori_csv import (
    Character,
    Line,
    Scenario,
    assign_numbers,
    effective_caption,
    read_scenario,
    write_scenario,
)
from irodori_cli.build import Builder, line_hash
from irodori_cli.config import Config, IrodoriConfig
from irodori_cli.tts import InferRunner


class _Rec:
    """infer 呼び出しの caption を記録するダミーランナー。"""

    def __init__(self):
        self.calls = []

    def infer(self, text, lora_dir, out_wav, caption=""):
        self.calls.append((text, caption))
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        with open(out_wav, "wb") as f:
            f.write(b"RIFFfake" + text.encode())


class TestCaptionModel(unittest.TestCase):
    def test_effective_caption_fallback(self):
        char = Character("あ", "1", "/l", "a_", caption="落ち着いた女性")
        # 行が空 → キャラ既定
        self.assertEqual(effective_caption(Line("1", "x", "x"), char), "落ち着いた女性")
        # 行が指定 → 行優先
        self.assertEqual(
            effective_caption(Line("1", "x", "x", caption="怒って"), char), "怒って"
        )
        # 両方空 → ""
        self.assertEqual(effective_caption(Line("1", "x", "x"), Character("あ", "1", "/l", "a_")), "")
        # キャラ None
        self.assertEqual(effective_caption(Line("1", "x", "x", caption="囁く"), None), "囁く")

    def test_assignment_caption(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_", caption="低い声")],
            lines=[Line("1", "a", "a"), Line("1", "b", "b", caption="叫ぶ")],
        )
        a = assign_numbers(sc)
        self.assertEqual(a[0].caption(), "低い声")   # 行空→キャラ既定
        self.assertEqual(a[1].caption(), "叫ぶ")     # 行優先


class TestCaptionCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_roundtrip_with_caption(self):
        sc = Scenario(
            characters=[Character("あかね", "1", "/l/akane", "akane_", caption="明るい少女")],
            lines=[Line("1", "やあ", "やあ😊", caption="元気よく")],
        )
        path = os.path.join(self.tmp, "s.csv")
        write_scenario(sc, path)
        got = read_scenario(path)
        self.assertEqual(got.characters[0].caption, "明るい少女")
        self.assertEqual(got.lines[0].caption, "元気よく")

    def test_old_csv_without_caption_column(self):
        # キャプション列が無い旧CSVでも読める（caption=""）
        old = (
            "キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド\n"
            "あ,1,/l,a_\n\n"
            "参照番号,テキスト,送信テキスト\n"
            "1,こんにちは,こんにちは\n"
        )
        path = os.path.join(self.tmp, "old.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(old)
        got = read_scenario(path)
        self.assertEqual(got.characters[0].caption, "")
        self.assertEqual(got.lines[0].caption, "")


class TestCaptionCacheAndFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _cfg(self):
        return Config(
            cache_dir=os.path.join(self.tmp, "c"),
            state_file=os.path.join(self.tmp, "s.json"),
            irodori=IrodoriConfig(repo_dir=self.tmp, checkpoint="x/y"),
        )

    def test_caption_changes_hash(self):
        base = ("こんにちは", "1", "/l", "sig")
        self.assertNotEqual(
            line_hash(*base, "怒って"), line_hash(*base, "優しく")
        )
        self.assertNotEqual(line_hash(*base, ""), line_hash(*base, "囁く"))

    def test_builder_passes_effective_caption(self):
        sc = Scenario(
            characters=[Character("あ", "1", "/l", "a_", caption="低い声")],
            lines=[Line("1", "a", "a"), Line("1", "b", "b", caption="叫ぶ")],
        )
        runner = _Rec()
        Builder(self._cfg(), runner).build(sc, out_dir=os.path.join(self.tmp, "o"))
        caps = {c for _t, c in runner.calls}
        self.assertIn("低い声", caps)  # 行空→キャラ既定
        self.assertIn("叫ぶ", caps)    # 行優先


class TestCaptionCommand(unittest.TestCase):
    def _runner(self, cfg_caption=None):
        cfg = Config(
            irodori=IrodoriConfig(repo_dir="/repo", runner="python", checkpoint="x/y",
                                  cfg_scale_caption=cfg_caption)
        )
        return InferRunner(cfg)

    def test_caption_added_to_command(self):
        cmd = self._runner().build_command("やあ", "/lora", "/out.wav", caption="優しく囁く")
        self.assertIn("--caption", cmd)
        self.assertIn("優しく囁く", cmd)

    def test_no_caption_flag_when_empty(self):
        cmd = self._runner().build_command("やあ", "/lora", "/out.wav", caption="")
        self.assertNotIn("--caption", cmd)

    def test_cfg_scale_caption_when_configured(self):
        cmd = self._runner(cfg_caption=4.0).build_command("やあ", "/lora", "/o.wav", caption="怒り")
        self.assertIn("--cfg-scale-caption", cmd)
        self.assertIn("4.0", cmd)


if __name__ == "__main__":
    unittest.main()
