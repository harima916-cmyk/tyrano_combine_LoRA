# tyrano_combine_LoRA

手動で用意した **シナリオCSV** を入力に、各行のセリフを
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)（キャラ別 LoRA）で
一括音声生成するスタンドアロン CLI ツール。

TyranoBuilder（`.ks`）との直接連携は複雑なため、間に CSV を挟んで疎結合にする方針。
本ツールは **CSV → 音声ファイル生成まで** を担当する（tyrano への組み込みはスコープ外）。

> 現状は **仕様策定フェーズ**。確定仕様は [`SPEC.md`](./SPEC.md)（CSV→音声生成 CLI）と
> [`GUI_SPEC.md`](./GUI_SPEC.md)（CSV 作成 GUI）を参照。

## 構図

```
scenario.csv（定義部 + セリフ部）  +  config.yaml（実行環境設定）
        └──▶ 一括音声生成ツール（infer.py / 差分キャッシュ）──▶ voices/*.wav
```

## 決定済みの方針

| 項目 | 決定 |
|---|---|
| 入力 | 手動で用意したシナリオCSV（1ファイル2セクション） |
| CSV の作り方 | 手動（tyrano 解析は行わない） |
| キャラ定義 | CSV の定義セクションに `キャラ名 / 参照番号 / LoRAフォルダ / 生成ファイルヘッド` |
| TTS | `infer.py` をサブプロセス実行、キャラ別 `--lora-adapter` |
| 感情 | `送信テキスト` 列の顔文字（絵文字）で制御（人手で付与） |
| LoRA | 学習済みを渡す前提（本ツールは生成のみ） |
| 出力 | `.wav`。ファイル名は `ヘッド + ゼロ埋めなし連番`（例 `akane_1.wav`）＝tyrano 互換 |
| 再生成 | 差分のみ（送信テキスト内容ハッシュキャッシュ） |
| 実行形態 | スタンドアロン Python CLI |

## 想定コマンド（仕様）

```bash
irodori-tts-batch validate         # CSV/config の検証・件数確認
irodori-tts-batch build --dry-run  # 生成対象行のプレビュー
irodori-tts-batch build            # 音声生成（差分のみ）
```

- 設定例: [`config.example.yaml`](./config.example.yaml)
- CSV 記入例: [`scenario.example.csv`](./scenario.example.csv)
- CSV 空テンプレート: [`scenario.template.csv`](./scenario.template.csv)

### CSV テンプレート（確定）

1 ファイルに **2 セクション**（空行で区切る）。

```csv
キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド
あかね,1,C:\lora\akane,akane_
ゆい,2,C:\lora\yui,yui_

参照番号,テキスト,送信テキスト
1,こんにちは。,こんにちは。😊
2,おはよう。,おはよう。☀️
```

- **定義部**: `キャラ名 / 参照番号 / LoRAフォルダ / 生成ファイルヘッド`
- **セリフ部**: `参照番号 / テキスト（原文）/ 送信テキスト（顔文字付き・TTS入力）`
- 出力名 = `ヘッド + ゼロ埋めなし連番 + .wav`（例 `akane_1.wav`, `akane_2.wav`, … `akane_10.wav`）
- 文字コードは UTF-8（BOM 有無どちらも可）。日本語 Excel 保存なら config で `cp932` も指定可。

詳細は [`SPEC.md`](./SPEC.md) §4。

## 構成（想定）

```
irodori_csv/   共有: CSV モデル / パーサ / 検証 / 出力名算出
irodori_cli/   CLI: validate / build / clean（infer.py 実行）
irodori_gui/   GUI: CSV 作成エディタ（PySide6）
```

CSV の読み書き・検証は CLI と GUI で共有し、形式のズレを防ぐ。

## 次のステップ

`SPEC.md` / `GUI_SPEC.md` の内容で問題なければ実装に着手する。将来的に `.ks` からの
CSV 自動生成や tyrano への書き戻しを拡張として追加できる（`SPEC.md` §10）。
