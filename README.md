# tyrano_combine_LoRA

TyranoBuilder（TyranoScript）のシナリオから **特定キャラのセリフだけ** を
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)（キャラ別 LoRA）で音声生成し、
`[voconfig]` / `[vostart]` でゲームへ自動組み込みするスタンドアロン CLI ツール。

> 現状はまだ **仕様策定フェーズ** です。確定仕様は [`SPEC.md`](./SPEC.md) を参照してください。

## 決定済みの方針

| 項目 | 決定 |
|---|---|
| 入力 | 生成済み TyranoScript `.ks` を解析 |
| 話者判定 | 名前欄 `#name` ベース |
| TTS | `infer.py` をサブプロセス実行、キャラ別 `--lora-adapter` |
| LoRA | 学習済みを渡す前提（本ツールは生成・組み込みのみ） |
| 感情 | 当面なし（素の生成） |
| 組み込み | `[voconfig]` + `[vostart]` 連番自動再生 |
| 再生成 | 差分のみ（テキストハッシュキャッシュ） |
| 実行形態 | スタンドアロン Python CLI |

## 想定コマンド（仕様）

```bash
irodori-tyrano scan             # 対象セリフ数を確認
irodori-tyrano build --dry-run  # 挿入 diff をプレビュー
irodori-tyrano build            # 生成 + 書き戻し（差分のみ）
```

設定は [`config.example.yaml`](./config.example.yaml) を参照。

## 次のステップ

`SPEC.md` §11 の未確定事項（実 `.ks` サンプルでの話者判定検証など）を潰したうえで実装に着手する。
