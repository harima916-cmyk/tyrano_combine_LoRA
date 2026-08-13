"""irodori_cli.build のテスト（fake TTS ランナーで infer.py 不要）。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from irodori_csv import Character, Line, Scenario  # noqa: E402
from irodori_cli.build import Builder, line_hash  # noqa: E402
from irodori_cli.config import Config  # noqa: E402


class FakeRunner:
    """infer 呼び出し回数を数え、ダミー wav を書き出すランナー。"""

    def __init__(self):
        self.calls = 0
        self.captions: list[str] = []

    def infer(self, text, lora_dir, out_wav, caption=""):
        self.calls += 1
        self.captions.append(caption)
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        with open(out_wav, "wb") as f:
            f.write(b"RIFFfake-wav-" + text.encode("utf-8"))


def _scenario():
    return Scenario(
        characters=[
            Character("あかね", "1", "/lora/akane", "akane_"),
            Character("ゆい", "2", "/lora/yui", "yui_"),
        ],
        lines=[
            Line("1", "こんにちは。", "こんにちは。😊"),
            Line("1", "本当ですか？", "本当ですか？😲"),
            Line("2", "おはよう。", "おはよう。☀️"),
        ],
    )


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(
            voice_out_dir=os.path.join(self.tmp, "voices"),
            cache_dir=os.path.join(self.tmp, "cache"),
            state_file=os.path.join(self.tmp, "state.json"),
        )

    def test_generates_all(self):
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        res = b.build(_scenario())
        self.assertEqual(res.generated, 3)
        self.assertEqual(runner.calls, 3)
        self.assertTrue(os.path.exists(os.path.join(self.cfg.voice_out_dir, "akane_1.wav")))
        self.assertTrue(os.path.exists(os.path.join(self.cfg.voice_out_dir, "yui_1.wav")))

    def test_incremental_skip(self):
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        b.build(_scenario())
        # 2 回目は全スキップ、infer 追加呼び出しなし
        runner2 = FakeRunner()
        b2 = Builder(self.cfg, runner2)
        res = b2.build(_scenario())
        self.assertEqual(res.skipped, 3)
        self.assertEqual(res.generated, 0)
        self.assertEqual(runner2.calls, 0)

    def test_only_changed_regenerated(self):
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        b.build(_scenario())
        # 1 行だけ送信テキストを変更
        sc = _scenario()
        sc.lines[1].send_text = "本当に？😲"
        runner2 = FakeRunner()
        b2 = Builder(self.cfg, runner2)
        res = b2.build(sc)
        self.assertEqual(res.generated, 1)
        self.assertEqual(res.skipped, 2)
        self.assertEqual(runner2.calls, 1)

    def test_force_bypasses_cache_reinfers(self):
        # --force はキャッシュがあっても infer を再実行して作り直す
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        b.build(_scenario())
        first = runner.calls
        self.assertEqual(first, 3)
        res = b.build(_scenario(), force=True)
        self.assertEqual(res.generated, 3)
        self.assertEqual(runner.calls, first + 3)  # 再生成された（コピーだけでない）

    def test_cache_hit_new_outdir(self):
        # 一度生成後、別フォルダへ出力すると infer は走らずキャッシュからコピー
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        b.build(_scenario())
        base_calls = runner.calls
        out2 = os.path.join(self.tmp, "export")
        res = b.build(_scenario(), out_dir=out2, group_by_char=True)
        self.assertEqual(res.generated, 3)
        self.assertEqual(runner.calls, base_calls)  # infer 追加なし
        self.assertTrue(os.path.exists(os.path.join(out2, "あかね", "akane_1.wav")))
        self.assertTrue(os.path.exists(os.path.join(out2, "ゆい", "yui_1.wav")))

    def test_group_by_char_dup_names(self):
        sc = Scenario(
            characters=[
                Character("あかね", "1", "/l", "a_"),
                Character("あかね", "2", "/l", "b_"),
            ],
            lines=[Line("1", "t", "t"), Line("2", "t", "t")],
        )
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        out = os.path.join(self.tmp, "ex")
        b.build(sc, out_dir=out, group_by_char=True)
        self.assertTrue(os.path.exists(os.path.join(out, "あかね_1", "a_1.wav")))
        self.assertTrue(os.path.exists(os.path.join(out, "あかね_2", "b_1.wav")))

    def test_empty_text_skip(self):
        sc = _scenario()
        sc.lines.append(Line("1", "", ""))
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        res = b.build(sc)
        self.assertEqual(res.generated, 3)  # 空行は生成されない

    def test_group_by_char_same_head_allowed(self):
        # 別キャラが同じヘッドでも group-by-char なら別サブフォルダで両方生成
        sc = Scenario(
            characters=[
                Character("あかね", "1", "/l", "line_"),
                Character("ゆい", "2", "/l", "line_"),
            ],
            lines=[Line("1", "a", "a"), Line("2", "b", "b")],
        )
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        out = os.path.join(self.tmp, "ex")
        res = b.build(sc, out_dir=out, group_by_char=True)
        self.assertEqual(res.generated, 2)
        self.assertTrue(os.path.exists(os.path.join(out, "あかね", "line_1.wav")))
        self.assertTrue(os.path.exists(os.path.join(out, "ゆい", "line_1.wav")))

    def test_group_by_char_rebuild_skips(self):
        sc = _scenario()
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        out = os.path.join(self.tmp, "ex2")
        b.build(sc, out_dir=out, group_by_char=True)
        runner2 = FakeRunner()
        b2 = Builder(self.cfg, runner2)
        res = b2.build(_scenario(), out_dir=out, group_by_char=True)
        self.assertEqual(res.skipped, 3)
        self.assertEqual(runner2.calls, 0)

    def test_empty_text_error_records_failure_no_raise(self):
        cfg = Config(
            voice_out_dir=os.path.join(self.tmp, "v"),
            cache_dir=os.path.join(self.tmp, "c"),
            state_file=os.path.join(self.tmp, "s.json"),
            on_empty_text="error",
        )
        sc = _scenario()
        sc.lines.append(Line("1", "", ""))
        b = Builder(cfg, FakeRunner())
        res = b.build(sc)  # 例外を投げないこと
        self.assertEqual(res.generated, 3)
        self.assertEqual(res.failed, 1)
        self.assertTrue(any("空" in msg for _n, msg in res.failures))

    def test_preview(self):
        runner = FakeRunner()
        b = Builder(self.cfg, runner)
        out = os.path.join(self.tmp, "prev.wav")
        p = b.preview("テスト😊", "/lora/akane", out)
        self.assertTrue(os.path.exists(p))
        self.assertEqual(runner.calls, 1)
        # state は更新されない
        self.assertFalse(os.path.exists(self.cfg.state_file))

    def test_hash_changes_with_text(self):
        h1 = line_hash("a", "1", "/l", "p")
        h2 = line_hash("b", "1", "/l", "p")
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
