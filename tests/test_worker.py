"""WorkerRunner（常駐ワーカー・クライアント）のテスト。

実モデル / GPU は使わず、プロトコルだけを模した疑似ワーカーで検証する。
"""

import os
import sys
import tempfile
import textwrap
import unittest

from irodori_cli.config import Config, IrodoriConfig
from irodori_cli.build import Builder
from irodori_cli.worker import WorkerError, WorkerRunner

FAKE_OK = textwrap.dedent("""
    import sys, json, os
    sys.stdout.write("@@IRODORI_READY@@\\n"); sys.stdout.flush()
    for raw in sys.stdin:
        line = raw.strip()
        if not line: continue
        if line == "@@QUIT@@": break
        job = json.loads(line)
        out = job["out"]
        if job.get("text") == "FAIL":
            sys.stdout.write("@@IRODORI_RESULT@@ " + json.dumps({"ok": False, "error": "boom"}) + "\\n")
            sys.stdout.flush(); continue
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "wb") as f: f.write(b"\\x00" * 256)
        sys.stdout.write("@@IRODORI_RESULT@@ " + json.dumps({"ok": True, "out": out}) + "\\n")
        sys.stdout.flush()
""")

FAKE_ECHO_LORA = textwrap.dedent("""
    import sys, json, os
    sys.stdout.write("@@IRODORI_READY@@\\n"); sys.stdout.flush()
    for raw in sys.stdin:
        line = raw.strip()
        if not line: continue
        if line == "@@QUIT@@": break
        job = json.loads(line)
        out = job["out"]
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        # 受け取った lora パスを1行目に書き出す（送信経路の文字化け検出用）。
        # 出力サイズ下限(128B)チェックに引っかからないようパディングを付ける。
        with open(out, "w", encoding="utf-8") as f:
            f.write((job.get("lora") or "") + "\\n" + "x" * 200)
        sys.stdout.write("@@IRODORI_RESULT@@ " + json.dumps({"ok": True, "out": out}) + "\\n")
        sys.stdout.flush()
""")

FAKE_FATAL = 'import sys\nsys.stdout.write("@@IRODORI_FATAL@@ boom\\n"); sys.stdout.flush(); sys.exit(4)\n'
FAKE_DIE = 'import sys\nsys.exit(1)\n'


def _write(dirpath, name, content):
    p = os.path.join(dirpath, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def _cfg(tmp):
    return Config(
        cache_dir=os.path.join(tmp, "cache"),
        state_file=os.path.join(tmp, "state.json"),
        voice_out_dir=os.path.join(tmp, "voices"),
        irodori=IrodoriConfig(repo_dir=tmp, runner=sys.executable, checkpoint="dummy/model"),
    )


class TestWorkerRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_generate_reuses_single_process(self):
        script = _write(self.tmp, "fake_ok.py", FAKE_OK)
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        w.start()
        proc1 = w._proc
        out1 = os.path.join(self.tmp, "a.wav")
        out2 = os.path.join(self.tmp, "b.wav")
        w.infer("こんにちは", "/lora/x", out1)
        w.infer("やあ", "/lora/y", out2)
        # 2回生成しても同じワーカープロセス（＝モデルは1回ロードだけ）
        self.assertIs(w._proc, proc1)
        self.assertTrue(os.path.exists(out1) and os.path.getsize(out1) >= 128)
        self.assertTrue(os.path.exists(out2) and os.path.getsize(out2) >= 128)
        w.close()
        self.assertIsNone(w._proc)

    def test_japanese_lora_path_roundtrip(self):
        # 日本語を含む LoRA パスが UTF-8 のままワーカーへ届く（文字化けしない）
        script = _write(self.tmp, "fake_echo.py", FAKE_ECHO_LORA)
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        w.start()
        lora = "/lora/元データ/ダイタクヘリオス/checkpoint_best_val_loss_0002000_0.886375"
        out = os.path.join(self.tmp, "jp.wav")
        # 内容チェック(<128B)で落ちないよう十分長いパスにしている
        w.infer("やあ", lora, out)
        with open(out, encoding="utf-8") as f:
            received = f.readline().rstrip("\n")
        self.assertEqual(received, lora)
        w.close()

    def test_caption_sent_in_job(self):
        # caption 付き infer で job に caption が入る
        script = _write(self.tmp, "fake_echo.py", FAKE_ECHO_LORA.replace('job.get("lora")', 'job.get("caption")'))
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        w.start()
        out = os.path.join(self.tmp, "cap.wav")
        w.infer("やあ", "/lora/x", out, caption="深く傷つき弱々しく話す")
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.readline().rstrip("\n"), "深く傷つき弱々しく話す")
        w.close()

    def test_job_failure_raises(self):
        script = _write(self.tmp, "fake_ok.py", FAKE_OK)
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        w.start()
        with self.assertRaises(WorkerError):
            w.infer("FAIL", "/lora/x", os.path.join(self.tmp, "c.wav"))
        w.close()

    def test_fatal_on_start_raises(self):
        script = _write(self.tmp, "fake_fatal.py", FAKE_FATAL)
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        with self.assertRaises(WorkerError):
            w.start()

    def test_die_before_ready_raises(self):
        script = _write(self.tmp, "fake_die.py", FAKE_DIE)
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        with self.assertRaises(WorkerError):
            w.start()

    def test_builder_uses_worker(self):
        # Builder が WorkerRunner を通して差分生成できる（キャッシュ経由）
        from irodori_csv import Scenario, Character, Line

        script = _write(self.tmp, "fake_ok.py", FAKE_OK)
        w = WorkerRunner(_cfg(self.tmp), worker_script=script)
        w.start()
        scenario = Scenario(
            characters=[Character(name="あかね", ref="1", lora_dir="/lora/akane", head="akane_")],
            lines=[Line(ref="1", text="a", send_text="こんにちは"),
                   Line(ref="1", text="b", send_text="やあ")],
        )
        b = Builder(_cfg(self.tmp), w)
        result = b.build(scenario, out_dir=os.path.join(self.tmp, "out"))
        self.assertEqual(result.generated, 2)
        self.assertEqual(result.failed, 0)
        w.close()


if __name__ == "__main__":
    unittest.main()
