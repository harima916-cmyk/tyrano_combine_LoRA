# シナリオCSV → Irodori-TTS 一括音声生成ツール 仕様書

## 0. この文書について

手動で用意した **シナリオCSV** を入力に、各セリフを
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)（キャラ別 LoRA）で音声化する
スタンドアロン CLI ツールの確定仕様。

TyranoBuilder（`.ks`）との直接連携は複雑なため、間に CSV を疎結合インターフェースとして挟む。
本ツールは **CSV → 音声ファイル（.wav）生成まで** を担い、`.ks` の解析・書き戻しは行わない。
ただし出力ファイル名は **TyranoScript が読み込める命名**（ゼロ埋めなし連番）にする。

---

## 1. 目的とゴール

- 手書きの CSV を入力に、対象セリフを一括で音声化する。
- CSV 内でキャラごとに **学習済み LoRA アダプタ** を定義し、切り替えて生成する。
- Irodori-TTS へは **顔文字（絵文字）付きテキスト** を送り、感情・話し方を制御する。
- CSV を修正して再実行したとき、**変わったセリフだけ** を再生成する（差分ビルド）。

### ゴール（Done の定義）

1. `build` 一発で全セリフの `.wav` が命名規則通りに出力される。
2. 同じ CSV で再実行しても再生成が走らない（冪等・キャッシュ hit）。
3. あるセリフの送信テキストを書き換えて再実行すると、その音声だけが再生成される。

---

## 2. スコープ

### 対象に含む（In Scope）

- シナリオ CSV（2 セクション構成）の読み込み・検証。
- Irodori-TTS `infer.py` のサブプロセス実行による音声生成（`--text` に顔文字付きテキスト）。
- キャラ別 LoRA アダプタ（`--lora-adapter`）の切り替え。
- `.wav` 出力・ゼロ埋めなし連番による命名・配置。
- 送信テキスト内容ハッシュによる差分再生成キャッシュ。

### 対象に含まない（Out of Scope）※将来拡張は §10

- **TyranoScript `.ks` の解析／書き戻し**（`voconfig` / `vostart` 挿入含む）。
- **LoRA の学習**。キャラ別 LoRA は *学習済みのものが用意されている前提*。
- CSV の自動生成（`.ks` からの抽出等）。CSV は手動で用意する。
- 顔文字の自動付与。感情を表す顔文字は **CSV の送信テキスト列に人手で書く**。

---

## 3. 全体アーキテクチャ

```
入力                              処理                                   出力
───────────         ─────────────────────────────────         ──────────────
config.yaml ─┐
             ├─▶ 1. 読込・検証   CSV 2セクションをパース             （エラー時は中断）
scenario.csv ┘      │             定義部↔セリフ部を参照番号で結合
                    ▼
                 2. 採番・差分   キャラ別に連番採番（1,2,3,…）
                    │            送信テキストのハッシュで差分判定
                    ▼
                 3. 生成         infer.py 実行（顔文字付きtext + LoRA）  voices/
                    │            必要な行のみ → .wav                     akane_1.wav ...
                    ▼
                 4. 記録         state を更新（出力名 → hash）           .irodori_state.json
```

---

## 4. 入力仕様：シナリオCSV（確定テンプレート）

### 4.1 全体構成（1 ファイル・2 セクション）

CSV は 1 ファイル内に **2 つのセクション** を持つ。セクションは **空行で区切る**。
各セクションは先頭に自身のヘッダ行を持ち、ヘッダの列名でセクションを識別する。

```csv
キャラ名,参照番号,LoRAフォルダ,生成ファイルヘッド
あかね,1,C:\lora\akane,akane_
ゆい,2,C:\lora\yui,yui_

参照番号,テキスト,送信テキスト
1,こんにちは。今日はいい天気ですね。,こんにちは。今日はいい天気ですね。😊
1,えっ、それ本当ですか？,えっ、それ本当ですか？😲
2,おはよう。今日もがんばろうね。,おはよう。今日もがんばろうね。☀️
```

- 上（`LoRAフォルダ` 列を含む方）＝ **キャラクター定義セクション**。
- 下（`送信テキスト` 列を含む方）＝ **セリフセクション**。
- セクションの順序は問わない（ヘッダ列名で判定する）。

> 補足: 2 テーブルを 1 ファイルに置くのが編集しづらい場合、定義とセリフを
> **別々の 2 ファイル** に分ける構成にも切り替え可能（§10-A）。

### 4.2 キャラクター定義セクション

| 列 | 必須 | 内容 |
|---|---|---|
| `キャラ名` | ✔ | 人間可読の表示名（ツールはログ表示に使用）。 |
| `参照番号` | ✔ | キャラの識別子。セリフ側と結合する **キー**。一意であること。 |
| `LoRAフォルダ` | ✔ | 学習済み LoRA アダプタのフォルダパス。`--lora-adapter` に渡す。 |
| `生成ファイルヘッド` | ✔ | 出力ファイル名の先頭（プレフィックス）。§4.4 参照。 |

### 4.3 セリフセクション

| 列 | 必須 | 内容 |
|---|---|---|
| `参照番号` | ✔ | 定義セクションの `参照番号` を指す。存在しない番号はエラー。 |
| `テキスト` | ✔ | 原文（人間可読・確認用）。 |
| `送信テキスト` | ✔ | Irodori-TTS へ送る **顔文字付き** テキスト。`infer.py --text` に渡す。 |

- 実際に TTS へ渡すのは **`送信テキスト`**。空の場合は `テキスト` をフォールバックに使う。
- 行の並び順が、そのキャラの音声の連番順になる（§4.4）。

### 4.4 出力ファイル名の規約

- ファイル名 = **`生成ファイルヘッド` + 連番 + `.wav`**。
- 連番は **キャラごと**に、セリフセクションの **出現順で 1 から** 振る。
- 連番は **ゼロ埋めしない**（`1, 2, …, 9, 10, 11, …`）。
  - 理由: TyranoScript の `voconfig` は `{number}` を 1,2,3… で展開するため、
    `001` のようなゼロ埋め名だと読み込めない。
- 拡張子は `.wav`（infer.py の出力が wav のため。変換は行わない）。

例: `生成ファイルヘッド = "akane_"`、あかねのセリフが 3 行
→ `akane_1.wav`, `akane_2.wav`, `akane_3.wav`

### 4.5 ファイル形式

| 項目 | 確定仕様 |
|---|---|
| 文字コード | **UTF-8**（BOM 有無どちらも読める）。既定 `utf-8-sig`。`config.csv.encoding` で `cp932`(Shift-JIS) 等に切替可（Excel 想定）。 |
| 改行 | LF / CRLF どちらも可。 |
| 区切り | カンマ `,`。 |
| クォート | 標準 CSV 規則。カンマ・改行・`"` を含む値は `"` で囲む（`"` は `""` にエスケープ）。 |
| セクション区切り | 空行。 |

### 4.6 検証ルール（`validate` / `build` で実施、違反は中断）

- 両セクションのヘッダが揃っていること（定義=`参照番号`/`LoRAフォルダ`/`生成ファイルヘッド`、
  セリフ=`参照番号`/`送信テキスト`）。
- 定義セクションの `参照番号` に **重複が無い** こと。
- セリフの `参照番号` が定義に **存在する** こと。
- `LoRAフォルダ` が実在すること。
- `生成ファイルヘッド` から生成される出力先に **重複・OS 不正文字**（`/ \ : * ? " < > |`。
  ヘッド自体のパス区切りは対象外）が無いこと。
  - フラット配置では `出力ファイル名` が重複してはならない。
  - `--group-by-char` では `サブフォルダ名/出力ファイル名` の組み合わせが重複してはならない。
    別サブフォルダで同名ファイルになることは許可する。
- `送信テキスト`（空なら `テキスト`）が空でないこと（`config.on_empty_text` に従う）。

---

## 5. 設定ファイル（config.yaml）

キャラ定義・LoRA パスは **CSV 側** に移動したため、config は実行環境の設定のみを持つ。

```yaml
project:
  csv_file:      "scenario.csv"         # 既定の入力 CSV（--csv で上書き可）
  voice_out_dir: "voices"               # 音声(.wav)の出力先
  preview_dir:   "preview"              # お試し生成の保存先（見えるフォルダ）
  cache_dir:     ".irodori_cache"       # TTS キャッシュ
  state_file:    ".irodori_state.json"  # 差分判定の状態

csv:
  encoding: "utf-8-sig"  # UTF-8(BOM有無どちらも可)。日本語Excel保存なら cp932 も可

irodori:
  repo_dir:   "/path/to/Irodori-TTS"        # infer.py のあるディレクトリ
  runner:     "uv run --no-sync python"     # 実行コマンド前置
  checkpoint: "Aratako/Irodori-TTS-500M-v3"
  num_steps:  32
  seconds:    null
  extra_args: []

on_empty_text: "skip"  # skip | error
```

---

## 6. 音声生成（Irodori-TTS 連携）

### 6.1 呼び出し

生成が必要なセリフごとに `infer.py` をサブプロセス実行する。

```
{runner} {repo_dir}/infer.py \
  --hf-checkpoint {checkpoint} \
  --text "{送信テキスト}" \
  --lora-adapter {定義[参照番号].LoRAフォルダ} \
  {話者フラグ}                          # 既定 --no-ref（§下記）
  [--num-steps {num_steps}] [--seconds {seconds}] {extra_args} \
  --output-wav {cache_dir}/{hash}.wav
```

- **作業ディレクトリは `repo_dir`**（Irodori-TTS リポジトリ）で実行する。infer.py・LoRA・
  出力先は絶対パスで渡す（`uv`/相対 import が正しい環境を使うため）。
- **話者フラグ**（話者条件付き checkpoint は必須）は `irodori.ref_mode` で決める:
  - `no-ref`（既定）→ `--no-ref`（LoRA が声を担う）
  - `ref-wav` / `ref-embed` / `ref-latent` → `--{mode} {irodori.ref_path}`
  - `none` → 付与しない（`extra_args` で自前指定）
- **デバイス / 精度**: `irodori.device` を指定すると `--model-device {device} --codec-device {device}`、
  `irodori.precision` で `--model-precision/--codec-precision` を付与する。GPU 明示なら `device: cuda`。
  未指定（`null`）なら infer.py の既定に任せる。
- 感情・話し方は `送信テキスト` 内の顔文字（絵文字）で制御する（Irodori-TTS の絵文字スタイル制御）。
- 生成物は `.wav`。変換はしないため `voice_out_dir/{ヘッド}{連番}.wav` へコピー配置する。

### 6.2 キャッシュ鍵と差分判定

```
hash = sha256( 送信テキスト + "\0" + 参照番号 + "\0" + LoRAフォルダ + "\0" + tts_params )
```

- `tts_params` = checkpoint / num_steps / seconds / extra_args を正規化した文字列。
- `state_file` は `出力相対パス → hash` を保持する。
  - フラット配置: `akane_1.wav`。
  - `--group-by-char`: `あかね/akane_1.wav`。
- 各セリフについて:
  - `state[出力相対パス] == hash` かつ出力ファイルが存在 → **スキップ**。
  - それ以外 → 生成（cache に `{hash}.wav` があれば infer.py を省略しコピーのみ）。
- `--force` で state を無視して全生成。`--force` は「検証エラーを隠してクラッシュさせる」ためのものではなく、
  ユーザー向けエラー表示を保ったまま再生成を強制するオプションとして扱う。

> 連番（出力名）は出現位置に依存するため行挿入でずれるが、キャッシュ鍵は
> **送信テキスト内容** なので、実際に内容が変わったセリフだけが再生成される。
> 位置ずれは安価なコピーだけで吸収する（生成結果は内容ハッシュで再利用）。

---

## 7. 出力仕様

| 対象 | 例 |
|---|---|
| 最終音声 | `voices/akane_1.wav`, `voices/akane_2.wav`, `voices/yui_1.wav` |
| キャッシュ | `.irodori_cache/3f9a...c1.wav` |
| 状態 | `.irodori_state.json`（`出力相対パス → hash`） |

- 出力先ディレクトリは自動作成する。

---

## 8. CLI 仕様

```
irodori-tts-batch <command> [options]

commands:
  validate  CSV と config を検証（生成しない）。キャラ別セリフ件数を表示。
  build     差分ビルド: 必要な行のみ生成 → 配置 → state 更新。
  preview   1 行だけをお試し生成（CSV/state を介さず、指定テキストで即生成）。GUI 試聴用。
  clean     出力音声 / キャッシュ / state を削除。

common options:
  -c, --config PATH   設定ファイル（既定: ./config.yaml）
  --csv PATH          入力 CSV（既定: config.project.csv_file）
  --chars a,b         対象キャラ（参照番号）を一時的に限定
  --dry-run           生成せず「生成/スキップ予定」の一覧だけ表示
  --force             キャッシュ・state を無視して全生成
  --progress          機械可読な進捗を1行1イベントで出力（GUI 連携用）
  -v, --verbose       詳細ログ

build options:
  --out-dir PATH      音声の出力先を上書き（既定: config.project.voice_out_dir）
  --copy-csv          出力先フォルダへ入力 CSV を scenario.csv としてコピー（バンドル出力）
  --group-by-char     音声をキャラ名のサブフォルダに分けて出力（一括生成の既定）

preview options:
  --text STR          送信テキスト（顔文字付き）
  --lora-dir PATH     LoRA アダプタのフォルダ
  --out PATH          出力 wav パス（既定: project.preview_dir 内。パスを stdout に出力）
```

### `build --out-dir` / `--copy-csv`（フォルダ出力・バンドル）

GUI の「一括生成（フォルダ出力）」（`GUI_SPEC.md` §5.5）から利用する。
指定フォルダに音声を書き出し、`--copy-csv` で元 CSV を同梱して**再現可能なバンドル**にする。
一括生成では `--group-by-char` により音声を **キャラごとのサブフォルダ** に分ける。

```
<出力先フォルダ>/
  scenario.csv        # 生成に使った CSV のコピー（--copy-csv 時）
  あかね/             # キャラ名のサブフォルダ（--group-by-char 時）
    akane_1.wav
    akane_2.wav
  ゆい/
    yui_1.wav
    yui_2.wav
```

- サブフォルダ名は **キャラ名**。OS 不正文字（`/ \ : * ? " < > |`）は `_` に置換する。
- `--group-by-char` を付けない場合は従来どおり出力先直下にフラット配置する。
- `--group-by-char` 時はサブフォルダが衝突しない限り、キャラ間で同じ `生成ファイルヘッド` を使ってよい。
  例: `あかね/line_1.wav` と `ゆい/line_1.wav` は別ファイルとして有効。
- キャラ名が重複すると同一フォルダに集約されてしまうため、`--group-by-char` 時は
  **キャラ名の一意性を検証**し、重複していれば警告し `キャラ名_参照番号` で分ける。
- 新しい空フォルダへ出力してもキャッシュ（内容ハッシュ）が効くため、未変更分は
  infer.py を再実行せず cache からコピーするだけで済む。

> 補足: 将来 tyrano 書き戻し（`SPEC.md` §10-B）を行う場合、サブフォルダ分割時は
> `voconfig` の `vostorage` パスにサブフォルダを含める必要がある。

### `preview`（お試し生成）

CSV や state を介さず、渡されたテキストと LoRA で 1 件だけ生成する。GUI が選択行の
`送信テキスト` と解決済み LoRA パスを渡し、返ってきた wav を再生して試聴する。

```
irodori-tts-batch preview --text "こんにちは。😊" --lora-dir C:\lora\akane --out tmp/preview.wav
# → 生成した wav のパスを stdout に出力
```

- キャッシュは共有する（同一 hash があれば再利用）。state は更新しない。

### 進捗出力プロトコル（`--progress`、GUI 連携用）

`build --progress` は標準出力に 1 行 1 イベントで進捗を出す。GUI（`GUI_SPEC.md` §5.5）が
これをパースして進捗バーを更新する。

```
PROGRESS <done>/<total> <出力ファイル名> <GENERATED|SKIPPED|FAILED>
DONE generated=<M> skipped=<K> failed=<F>
```

### 想定フロー

```
$ irodori-tts-batch validate            # CSV/configの妥当性と件数を確認
$ irodori-tts-batch build --dry-run     # 生成対象のプレビュー
$ irodori-tts-batch build               # 音声生成
# ... CSV を修正 ...
$ irodori-tts-batch build               # 変わったセリフだけ再生成
```

---

## 9. エラーハンドリング方針

- 検証エラー（重複参照番号 / 未定義参照 / LoRA 不在 / 出力先重複）は **生成前に一括報告して中断**。
- `--force` 指定時も、CLI は Python の未捕捉例外やスタックトレースをユーザーへ見せない。
  継続できない入力は日本語のエラーメッセージと終了コードで返す。
- 空テキスト行の扱いは `config.on_empty_text` に従う。
  - `skip`: その行を生成対象から外し、必要に応じて警告として表示する。
  - `error`: 生成前に検証エラーとして表示し、通常は中断する。`--force` で続行する場合も、
    当該行は失敗行として記録するか、ユーザー向けエラーとして終了し、未捕捉例外にはしない。
- 生成中に個別行が失敗した場合は記録してスキップし、末尾で失敗一覧を表示
  （`--fail-fast` で即中断も選べる）。
- 途中中断しても、成功済みの行は state に記録され、再実行時にスキップされる。

### 9.1 実装レビューで確認した要改善仕様

以下は実装時に必ず満たすべき回帰防止項目。

1. **`--force` と空テキストの整合性**
   - `--force` は state/キャッシュの強制再生成および検証エラーの明示的な続行に使う。
   - `on_empty_text: error` の空行で `ValueError` などが未捕捉のまま CLI 外へ漏れてはならない。
   - GUI から起動された場合も、ログに読み取れるエラーとして表示できる形式にする。
2. **`--group-by-char` 時の重複判定単位**
   - フラット配置の重複キーは `出力ファイル名`。
   - キャラ別フォルダ配置の重複キーは `サブフォルダ名/出力ファイル名`。
   - state のキーも同じ相対パス単位に揃え、同名ファイルが別フォルダにあるケースで
     誤スキップ・誤上書きが起きないようにする。

---

## 10. 将来拡張

- **A. 定義とセリフの 2 ファイル分割**: 1 ファイル 2 セクションが編集しづらい場合、
  `characters.csv` / `scenario.csv` に分割する構成へ切替。
- **B. tyrano 組み込み**: 生成結果を `voconfig` / `vostart` で `.ks` へ書き戻す後段
  （連番のゼロ埋めなし命名は既にこれに適合済み）。
- **C. CSV 自動生成**: `.ks` から定義・セリフを抽出する補助コマンド。
- **D. 顔文字の自動付与 / VoiceDesign caption 対応**。
- **E. 生成バックエンド抽象化**: `infer.py` 直叩き / Irodori-TTS-Server（OpenAI 互換 API）の切替。

---

## 付録: 参照

- Irodori-TTS 本体: https://github.com/Aratako/Irodori-TTS
- Irodori-TTS-Server（OpenAI 互換 API）: https://github.com/Aratako/Irodori-TTS-Server
