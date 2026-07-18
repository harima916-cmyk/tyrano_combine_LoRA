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
