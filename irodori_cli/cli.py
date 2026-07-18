"""コマンドライン入口（SPEC §8）。"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from irodori_csv import ParseError, read_scenario, validate_scenario

from .build import Builder
from .config import Config, load_config
from .tts import InferRunner
from .worker import WorkerError, WorkerRunner


def _make_runner(cfg: Config, log=print):
    """設定に応じた TTSRunner を返す。worker 起動に失敗したら subprocess にフォールバック。

    返り値は (runner, close_fn)。close_fn は使い終わりに必ず呼ぶ。
    """
    if cfg.backend == "worker":
        w = WorkerRunner(cfg, log_fn=lambda m: log(m))
        try:
            w.start()  # モデルを1回だけロード（ここで常駐開始）
            return w, w.close
        except WorkerError as e:
            log(f"⚠ 常駐ワーカーを起動できませんでした（従来方式にフォールバック）: {e}")
    return InferRunner(cfg), (lambda: None)


def _load(args) -> Config:
    if args.config and os.path.exists(args.config):
        return load_config(args.config)
    if args.config:
        print(f"警告: 設定ファイルが見つかりません: {args.config}（既定値を使用）", file=sys.stderr)
    return Config()


def _read_scenario(cfg: Config, args):
    path = args.csv or cfg.csv_file
    return read_scenario(path, encoding=cfg.csv_encoding), path


def _print_issues(issues) -> bool:
    errors = [i for i in issues if i.is_error]
    warnings = [i for i in issues if not i.is_error]
    for i in warnings:
        loc = f"[{i.section}:{i.index}] " if i.index >= 0 else ""
        print(f"⚠ {loc}{i.message}", file=sys.stderr)
    for i in errors:
        loc = f"[{i.section}:{i.index}] " if i.index >= 0 else ""
        print(f"✖ {loc}{i.message}", file=sys.stderr)
    return len(errors) == 0


def cmd_validate(args) -> int:
    cfg = _load(args)
    try:
        scenario, path = _read_scenario(cfg, args)
    except (ParseError, OSError) as e:
        print(f"読み込みエラー: {e}", file=sys.stderr)
        return 2

    issues = validate_scenario(scenario, group_by_char=True)
    ok = _print_issues(issues)

    counts: dict[str, int] = {}
    for line in scenario.lines:
        c = scenario.character_by_ref(line.ref)
        key = c.name if c else f"(未定義:{line.ref})"
        counts[key] = counts.get(key, 0) + 1
    print(f"CSV: {path}")
    print(f"キャラ数: {len(scenario.characters)} / セリフ数: {len(scenario.lines)}")
    for name, n in counts.items():
        print(f"  {name}: {n}")
    return 0 if ok else 1


def cmd_build(args) -> int:
    cfg = _load(args)
    try:
        scenario, path = _read_scenario(cfg, args)
    except (ParseError, OSError) as e:
        print(f"読み込みエラー: {e}", file=sys.stderr)
        return 2

    issues = validate_scenario(scenario, group_by_char=args.group_by_char)
    if not _print_issues(issues) and not args.force:
        print("検証エラーがあるため中断しました（--force で無視）。", file=sys.stderr)
        return 1

    chars = set(args.chars.split(",")) if args.chars else None

    if args.dry_run:
        from irodori_csv import assign_numbers
        for a in assign_numbers(scenario):
            if chars and a.line.ref not in chars:
                continue
            print(f"[生成予定] {a.filename}  <- {a.character.name}: {a.line.tts_text()[:30]}")
        return 0

    def progress(done, total, name, status):
        if args.progress:
            print(f"PROGRESS {done}/{total} {name} {status}", flush=True)

    runner, close_runner = _make_runner(cfg, log=lambda m: print(m, flush=True))
    try:
        builder = Builder(cfg, runner)
        result = builder.build(
            scenario,
            out_dir=args.out_dir,
            group_by_char=args.group_by_char,
            force=args.force,
            chars=chars,
            progress=progress,
        )
    finally:
        close_runner()

    if args.copy_csv:
        dest_dir = args.out_dir or cfg.voice_out_dir
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(path, os.path.join(dest_dir, "scenario.csv"))

    if args.progress:
        print(
            f"DONE generated={result.generated} skipped={result.skipped} "
            f"failed={result.failed}",
            flush=True,
        )
    print(
        f"完了: 生成 {result.generated} / スキップ {result.skipped} / 失敗 {result.failed}"
    )
    for name, err in result.failures:
        print(f"  ✖ {name}: {err}", file=sys.stderr)
    return 0 if result.failed == 0 else 1


def cmd_preview(args) -> int:
    cfg = _load(args)
    # 既定はプロジェクト内の見える preview/ フォルダ（隠しフォルダを避ける）
    out = args.out or os.path.join(cfg.preview_dir, "preview.wav")
    runner, close_runner = _make_runner(cfg, log=lambda m: print(m, file=sys.stderr, flush=True))
    try:
        builder = Builder(cfg, runner)
        path = builder.preview(args.text, args.lora_dir, out)
    except Exception as e:  # noqa: BLE001
        print(f"生成エラー: {e}", file=sys.stderr)
        return 1
    finally:
        close_runner()
    print(path)
    return 0


def cmd_clean(args) -> int:
    cfg = _load(args)
    for target in (cfg.voice_out_dir, cfg.cache_dir):
        if os.path.isdir(target):
            shutil.rmtree(target)
            print(f"削除: {target}")
    if os.path.exists(cfg.state_file):
        os.remove(cfg.state_file)
        print(f"削除: {cfg.state_file}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="irodori-tts-batch", description="シナリオCSV → Irodori-TTS 一括音声生成")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("--csv", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    pv = sub.add_parser("validate", help="CSV と config を検証")
    pv.set_defaults(func=cmd_validate)

    pb = sub.add_parser("build", help="差分ビルド")
    pb.add_argument("--chars", default=None, help="対象キャラ（参照番号）をカンマ区切りで限定")
    pb.add_argument("--dry-run", action="store_true")
    pb.add_argument("--force", action="store_true")
    pb.add_argument("--progress", action="store_true", help="機械可読な進捗を出力")
    pb.add_argument("--out-dir", default=None, help="音声の出力先を上書き")
    pb.add_argument("--copy-csv", action="store_true", help="出力先へ CSV を同梱")
    pb.add_argument("--group-by-char", action="store_true", help="キャラ名のサブフォルダに分割")
    pb.set_defaults(func=cmd_build)

    pp = sub.add_parser("preview", help="1 行だけお試し生成")
    pp.add_argument("--text", required=True)
    pp.add_argument("--lora-dir", required=True)
    pp.add_argument("--out", default=None)
    pp.set_defaults(func=cmd_preview)

    pc = sub.add_parser("clean", help="出力 / キャッシュ / state を削除")
    pc.set_defaults(func=cmd_clean)

    return p


def _force_utf8_output() -> None:
    """Windows の bash 等で日本語メッセージが文字化けしないよう UTF-8 出力にする。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("中断しました。", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 - ユーザーへスタックトレースを見せない
        # 継続不能な入力・環境エラーは日本語メッセージ＋終了コードで返す。
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        print(f"エラー: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
