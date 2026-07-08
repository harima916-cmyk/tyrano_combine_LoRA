# tyrano_combine_LoRA

手動で用意した **シナリオCSV** を入力に、各行のセリフを
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)（キャラ別 LoRA）で
一括音声生成するスタンドアロン CLI ツール。

TyranoBuilder（`.ks`）との直接連携は複雑なため、間に CSV を挟んで疎結合にする方針。
本ツールは **CSV → 音声ファイル生成まで** を担当する（tyrano への組み込みはスコープ外）。

> 現状は **仕様策定フェーズ**。確定仕様は [`SPEC.md`](./SPEC.md) を参照。

## 構図

```
scenario.csv (filename, character, text)  +  config.yaml (character → LoRA)
        └──▶ 一括音声生成ツール（infer.py / 差分キャッシュ）──▶ voices/*.ogg
```

## 決定済みの方針

| 項目 | 決定 |
|---|---|
| 入力 | 手動で用意したシナリオCSV（`filename, character, text`） |
| CSV の作り方 | 手動（tyrano 解析は行わない） |
| TTS | `infer.py` をサブプロセス実行、キャラ別 `--lora-adapter` |
| LoRA | 学習済みを渡す前提（本ツールは生成のみ） |
| 感情 | 当面なし（素の生成） |
| ゴール | 音声ファイル生成まで（tyrano 組み込みはスコープ外） |
| 再生成 | 差分のみ（行内容ハッシュキャッシュ） |
| 実行形態 | スタンドアロン Python CLI |

## 想定コマンド（仕様）

```bash
irodori-tts-batch validate         # CSV/config の検証・件数確認
irodori-tts-batch build --dry-run  # 生成対象行のプレビュー
irodori-tts-batch build            # 音声生成（差分のみ）
```

- 設定例: [`config.example.yaml`](./config.example.yaml)
- CSV 例: [`scenario.example.csv`](./scenario.example.csv)

## 次のステップ

`SPEC.md` の内容で問題なければ実装に着手する。将来的に `.ks` からの CSV 自動生成や
tyrano への書き戻しを拡張として追加できる（`SPEC.md` §10）。
