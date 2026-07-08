# シナリオCSV → Irodori-TTS 一括音声生成ツール 仕様書

## 0. この文書について

手動で用意した **シナリオCSV** を入力に、各行のセリフを
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)（キャラ別 LoRA）で音声化する
スタンドアロン CLI ツールの確定仕様。

当初は TyranoBuilder（TyranoScript `.ks`）との直接連携を検討したが、連携が複雑なため
**CSV を疎結合のインターフェースとして挟む**方針に変更した。本ツールは CSV → 音声ファイル生成
までを担い、TyranoScript の解析・書き戻しは **行わない**。

---

## 1. 目的とゴール

- 手書きの CSV（`filename, character, text`）を入力に、対象セリフを一括で音声化する。
- キャラごとに **学習済み LoRA アダプタ** を切り替えて生成する。
- CSV を修正して再実行したとき、**変わった行だけ** を再生成する（差分ビルド）。

### ゴール（Done の定義）

1. `build` 一発で CSV 全行の音声ファイルが `filename` 通りに出力される。
2. 同じ CSV で再実行しても再生成が走らない（冪等・キャッシュ hit）。
3. ある行の `text` を書き換えて再実行すると、その行の音声だけが再生成される。

---

## 2. スコープ

### 対象に含む（In Scope）

- シナリオ CSV の読み込み・検証（`filename, character, text`）。
- Irodori-TTS `infer.py` のサブプロセス実行による音声生成。
- キャラ別 LoRA アダプタ（`--lora-adapter`）の切り替え。
- wav → 指定フォーマット（既定 `ogg`）変換・命名・配置。
- 行内容ハッシュによる差分再生成キャッシュ。

### 対象に含まない（Out of Scope）※将来拡張は §10

- **TyranoScript `.ks` の解析／書き戻し**（`voconfig` / `vostart` 挿入含む）。CSV より後段は手動。
- **LoRA の学習**。キャラ別 LoRA は *学習済みのものが用意されている前提*。
- 感情・スタイル制御（`caption` / 絵文字）。当面は素の生成。
- CSV の自動生成（`.ks` からの抽出等）。CSV は手動で用意する。

---

## 3. 全体アーキテクチャ

```
入力                              処理                                   出力
───────────         ─────────────────────────────────         ──────────────
config.yaml ─┐
             ├─▶ 1. 読込・検証   CSV パース + config 突合          （エラー時は中断）
scenario.csv ┘      │             （character 未定義 / 重複 filename 等）
                    ▼
                 2. 差分判定     行ハッシュ = f(text, character, lora, params)
                    │            state と比較し「生成が必要な行」を選別
                    ▼
                 3. 生成         infer.py 実行 → wav → 変換              voice_out/
                    │            （必要な行のみ、キャラの LoRA を適用）    akane_001.ogg ...
                    ▼
                 4. 記録         state を更新（filename → hash）          .irodori_state.json
```

---

## 4. 入力仕様

### 4.1 シナリオCSV

- 文字コード **UTF-8**、**ヘッダ行必須**。標準 CSV クォート規則（カンマ・改行はダブルクォートで囲む）。
- 列（順不同、ヘッダ名で識別）:

| 列 | 必須 | 内容 |
|---|---|---|
| `filename` | ✔ | 出力音声のファイル名。拡張子は省略可（省略時は `audio.format` を付与）。 |
| `character` | ✔ | キャラキー。`config.characters` に定義され、LoRA を解決する。 |
| `text` | ✔ | 音声化するセリフ本文（TTS 入力・ハッシュ対象）。 |

例（`scenario.example.csv`）:

```csv
filename,character,text
akane_001,akane,こんにちは。今日はいい天気ですね。
akane_002,akane,えっ、それ本当ですか？
yui_001,yui,おはよう。今日もがんばろうね。
```

### 4.2 検証ルール（`build` / `validate` で実施、違反は中断）

- `filename` の **重複禁止**（拡張子正規化後で判定）。
- `character` が `config.characters` に **存在すること**。
- `text` が **空でないこと**（空行は警告してスキップ、設定で挙動選択可）。
- 参照する LoRA アダプタのパスが **存在すること**。
- `filename` に OS 依存の不正文字（`/ \ : * ? " < > |`）を含まないこと。

---

## 5. 設定ファイル（config.yaml）

```yaml
project:
  csv_file:      "scenario.csv"         # 既定の入力 CSV（--csv で上書き可）
  voice_out_dir: "voices"               # 音声の出力先
  cache_dir:     ".irodori_cache"       # TTS キャッシュ
  state_file:    ".irodori_state.json"  # 差分判定の状態

irodori:
  repo_dir:   "/path/to/Irodori-TTS"        # infer.py のあるディレクトリ
  runner:     "uv run --no-sync python"     # 実行コマンド前置
  checkpoint: "Aratako/Irodori-TTS-500M-v3"
  num_steps:  32
  seconds:    null
  extra_args: []

audio:
  format: "ogg"       # 最終フォーマット（filename 拡張子省略時に付与）
  ffmpeg: "ffmpeg"    # wav→他形式の変換に使用

on_empty_text: "skip"  # skip | error

# 音声化するキャラの定義。character 列はここのキーと突合する。
characters:
  akane:
    lora_adapter: "/path/to/lora/akane"   # 学習済み LoRA（必須）
    ref_wav: null                         # 任意: 併用する参照音声
  yui:
    lora_adapter: "/path/to/lora/yui"
```

---

## 6. 音声生成（Irodori-TTS 連携）

### 6.1 呼び出し

生成が必要な行ごとに `infer.py` をサブプロセス実行する。

```
{runner} {repo_dir}/infer.py \
  --hf-checkpoint {checkpoint} \
  --text "{text}" \
  --lora-adapter {characters[character].lora_adapter} \
  [--ref-wav {characters[character].ref_wav}] \
  [--num-steps {num_steps}] [--seconds {seconds}] {extra_args} \
  --output-wav {cache_dir}/{hash}.wav
```

- `caption`（感情）は当面付与しない。
- 生成物は wav で受け、`audio.format` が `wav` 以外なら `ffmpeg` で変換して
  `voice_out_dir/{filename}` へ配置する。

### 6.2 キャッシュ鍵と差分判定

```
hash = sha256( text + "\0" + character + "\0" + lora_adapter + "\0" + tts_params )
```

- `tts_params` = checkpoint / num_steps / seconds / extra_args を正規化した文字列。
- `state_file` は `filename → hash` を保持する。
- 各行について:
  - `state[filename] == hash` かつ出力ファイルが存在 → **スキップ**。
  - それ以外 → 生成（cache に `{hash}.wav` があれば infer.py を省略し変換のみ）。
- `--force` で state を無視して全行再生成。

> 内容ハッシュを持つことで、行の順番入れ替えや他行の編集に影響されず、
> **実際に text/character/LoRA が変わった行だけ** が再生成される。

---

## 7. 出力仕様

| 対象 | 例 |
|---|---|
| 最終音声 | `voices/akane_001.ogg`, `voices/yui_001.ogg` |
| キャッシュ | `.irodori_cache/3f9a...c1.wav` |
| 状態 | `.irodori_state.json` |

- `filename` に拡張子があればそれを優先、なければ `audio.format` を付与。
- 出力先ディレクトリは自動作成する。

---

## 8. CLI 仕様

```
irodori-tts-batch <command> [options]

commands:
  validate  CSV と config を検証（生成しない）。件数・キャラ別内訳を表示。
  build     差分ビルド: 必要な行のみ生成 → 配置 → state 更新。
  clean     出力音声 / キャッシュ / state を削除。

common options:
  -c, --config PATH   設定ファイル（既定: ./config.yaml）
  --csv PATH          入力 CSV（既定: config.project.csv_file）
  --chars a,b         対象キャラを一時的に限定
  --dry-run           生成せず「生成/スキップ予定」の一覧だけ表示
  --force             キャッシュ・state を無視して全生成
  -v, --verbose       詳細ログ
```

### 想定フロー

```
$ irodori-tts-batch validate            # CSV/configの妥当性と件数を確認
$ irodori-tts-batch build --dry-run     # 生成対象行のプレビュー
$ irodori-tts-batch build               # 音声生成
# ... CSV を修正 ...
$ irodori-tts-batch build               # 変わった行だけ再生成
```

---

## 9. エラーハンドリング方針

- 検証エラー（未定義 character / 重複 filename / LoRA 不在）は **生成前に一括報告して中断**。
- 生成中に個別行が失敗した場合は、その行を記録してスキップし、末尾で失敗一覧を表示
  （`--fail-fast` で即中断も選べるようにする）。
- 途中中断しても、成功済みの行は state に記録され、再実行時にスキップされる。

---

## 10. 将来拡張

- **A. CSV 自動生成**: TyranoScript `.ks` から `filename, character, text` を抽出する
  補助コマンド（旧連携案の名前欄 `#name` パーサを流用）。
- **B. tyrano 組み込み**: 生成結果を `voconfig` / `vostart` で `.ks` へ書き戻す後段。
- **C. 感情・スタイル**: `caption` 列の追加と VoiceDesign チェックポイント対応。
- **D. LoRA 未整備時のフォールバック**: 参照音声（`--ref-wav`）のみでの生成。
- **E. 生成バックエンド抽象化**: `infer.py` 直叩き / Irodori-TTS-Server（OpenAI 互換 API）の切替。

---

## 付録: 参照

- Irodori-TTS 本体: https://github.com/Aratako/Irodori-TTS
- Irodori-TTS-Server（OpenAI 互換 API）: https://github.com/Aratako/Irodori-TTS-Server
