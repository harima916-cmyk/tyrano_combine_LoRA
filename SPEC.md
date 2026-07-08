# TyranoBuilder × Irodori-TTS 連携ツール 仕様書

## 0. この文書について

TyranoBuilder（TyranoScript）で作成したノベルゲームの **特定キャラのセリフだけ** を
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) で音声生成し、ゲームに自動で組み込む
スタンドアロン CLI ツールの仕様を定義する。

本文書は「実装前に方針を固める」ことを目的とした **確定仕様のたたき台** であり、
未確定事項は §11 に明示する。

---

## 1. 目的とゴール

- シナリオ（`.ks`）を入力に、対象キャラのセリフを抽出し Irodori-TTS で音声化する。
- 生成した音声を TyranoScript のボイス管理タグ（`[voconfig]` / `[vostart]`）で
  ゲームに自動で組み込む。
- シナリオ修正後は **変更されたセリフだけ** を再生成する（差分ビルド）。

### ゴール（Done の定義）

1. `build` コマンド一発で「対象キャラのセリフ音声生成 → `.ks` へ再生タグ挿入」まで完了する。
2. 同じ入力で再実行しても結果が変わらない（冪等）。二重挿入・重複生成をしない。
3. セリフ本文を1つ書き換えて再実行すると、そのセリフの音声だけが再生成される。

---

## 2. スコープ

### 対象に含む（In Scope）

- 生成済み TyranoScript `.ks` の解析（名前欄 `#name` ベースの話者判定）。
- Irodori-TTS `infer.py` のサブプロセス実行による音声生成。
- **キャラ別 LoRA アダプタ**（`--lora-adapter`）の切り替え。
- 生成音声の `.ogg` 変換・命名・配置。
- `[voconfig]` / `[vostart]` の `.ks` への挿入（冪等）。
- テキストハッシュによる差分再生成キャッシュ。

### 対象に含まない（Out of Scope）※将来拡張は §11

- **LoRA の学習**。キャラ別 LoRA アダプタは *学習済みのものが用意されている前提* とする。
  本ツールは受け取ったアダプタを使って推論するのみ。
- 感情・スタイル制御（`caption` / 絵文字）。当面は **素の生成** とする。
- TyranoBuilder プロジェクト独自形式（`.ttb` 等）の直接解析。入力は `.ks` に限定。
- TyranoBuilder 上の GUI / プラグイン化。実行形態はスタンドアロン CLI に限定。

---

## 3. 用語

| 用語 | 意味 |
|---|---|
| `.ks` | TyranoScript のシナリオファイル。KAG 系タグ記法。 |
| 名前欄 (`#name`) | 行頭 `#` で話者名を表示する TyranoScript の記法。 |
| セリフ | 名前欄の直後〜改ページ（`[p]` / `[l][r]`）までの本文テキスト。 |
| LoRA アダプタ | Irodori-TTS の話者を特定キャラ声に寄せる学習済みアダプタ。 |
| voconfig / vostart | TyranoScript のボイス管理タグ。キャラ名にボイスを紐付け連番自動再生する。 |
| 差分ビルド | 前回から変わったセリフだけを再生成すること。 |

---

## 4. 全体アーキテクチャ

```
入力                          処理パイプライン                         出力
────────         ───────────────────────────────────────         ────────
config.yaml ─┐
             ├─▶ 1. パース    .ks 走査 → 発話ユニット抽出
scenario/*.ks┘   （#name → セリフ本文・行範囲）
                    │
                    ▼
                 2. フィルタ  config.characters に居る対象キャラだけ残す
                    │
                    ▼
                 3. 割り当て  キャラ → LoRA アダプタ / 出力prefix を解決
                    │
                    ▼
                 4. 生成      テキストハッシュでキャッシュ照合
                    │         miss のみ infer.py 実行 → wav → キャッシュ格納
                    ▼
                 5. 配置      キャラ別に位置ベースの連番採番            data/voice/
                    │         cache(wav) → akane_{N}.ogg へ変換コピー   akane_1.ogg ...
                    ▼
                 6. 書き戻し  冒頭に voconfig、各セリフ前に vostart 挿入  voiced *.ks
                              （サンプルコメントで冪等化）
```

各ステップは疎結合とし、`scan`（解析のみ）/ `build`（全工程）/ `clean` で呼び分ける。

---

## 5. 入力仕様

### 5.1 話者判定（名前欄 `#name` ベース）

TyranoScript の標準的な名前欄記法を話者の根拠とする。

- 行頭が `#` で始まる行を **名前欄行** とみなす。
  - `#あかね` → 表示名 `あかね`
  - `#akane|あかね` → キー `akane`、表示名 `あかね`（`|` 前をキーとして扱う）
  - `#`（単独） → 名前欄クリア（＝以降は地の文／ナレーション扱い、対象外）
- 名前欄行の **直後から改ページまで** を、その話者のセリフ本文とする。
  - 改ページ判定: `[p]`, `[l]`, `[r]`, 次の名前欄行 `#...`, `[cm]`, `[er]`, ラベル `*label`, タグ単独行。
  - 本文中に含まれるインラインタグ（`[ruby]` 等）は **TTS 用テキストからは除去**し、
    書き戻し位置の特定には元の行範囲を使う。
- 名前欄のキー（`akane` / `あかね`）を `config.characters` の `names` と突き合わせて
  キャラを同定する（表記ゆれ吸収）。

> 話者判定は `.ks` の書き方に依存する。TyranoBuilder の実出力サンプルが手に入り次第、
> 上記ルールを実サンプルで検証・調整する（§11-A）。

### 5.2 発話ユニット（内部データ）

パーサは各セリフを次の構造に正規化する。

```jsonc
{
  "file": "scenario/ch01.ks",   // 相対パス
  "char_key": "akane",          // config で解決したキャラキー
  "display_name": "あかね",
  "text_raw":  "こんにちは。[ruby text=きょう]今日[endruby]はいい天気ですね。",
  "text_tts":  "こんにちは。今日はいい天気ですね。",  // タグ除去後（TTS入力・ハッシュ対象）
  "line_start": 42,             // 名前欄行 or セリフ開始行（0始まり）
  "line_end":   43              // セリフ末尾行
}
```

---

## 6. 設定ファイル（config.yaml）

```yaml
project:
  ks_dir:        "data/scenario"     # .ks を再帰探索するルート
  voice_out_dir: "data/voice"        # 音声の最終出力先（ゲームが参照）
  cache_dir:     ".irodori_cache"    # TTS キャッシュ（コミット任意）
  state_file:    ".irodori_state.json"  # 差分・書き戻し状態

irodori:
  repo_dir:   "/path/to/Irodori-TTS" # infer.py のあるディレクトリ
  runner:     "uv run --no-sync python"  # 実行コマンド前置
  checkpoint: "Aratako/Irodori-TTS-500M-v3"
  num_steps:  32                     # infer.py --num-steps
  seconds:    null                   # 任意: 出力長固定
  extra_args: []                     # infer.py への追加引数

audio:
  format:   "ogg"                    # 最終フォーマット（voconfig に合わせ ogg）
  ffmpeg:   "ffmpeg"                 # wav→ogg 変換に使用

tyrano:
  voice_sebuf:   2                   # ボイス用 SE バッファ番号
  insert_voconfig: true             # 冒頭 voconfig 自動挿入の有無
  # 挿入マーカー（冪等化用サンプルコメント）
  marker: "; @irodori-tts"

# 対象キャラのホワイトリスト（ここに無いキャラは音声化しない）
characters:
  akane:
    names: ["akane", "あかね"]        # .ks 名前欄の表記ゆれを吸収
    lora_adapter: "/path/to/lora/akane"  # 学習済み LoRA（必須）
    ref_wav: null                    # 任意: LoRA と併用する参照音声
    file_prefix: "akane"             # → akane_{number}.ogg
  yui:
    names: ["yui", "ゆい"]
    lora_adapter: "/path/to/lora/yui"
    file_prefix: "yui"
```

- `characters` に列挙したキャラ **のみ** 音声化する（＝「特定キャラだけ」の実現方法）。
- `names` は名前欄キー・表示名のどちらとも一致判定する。

---

## 7. 音声生成（Irodori-TTS 連携）

### 7.1 呼び出し

各キャッシュミスのセリフごとに `infer.py` をサブプロセス実行する。

```
{runner} {repo_dir}/infer.py \
  --hf-checkpoint {checkpoint} \
  --text "{text_tts}" \
  --lora-adapter {characters[k].lora_adapter} \
  [--ref-wav {characters[k].ref_wav}] \
  [--num-steps {num_steps}] [--seconds {seconds}] {extra_args} \
  --output-wav {cache_dir}/{hash}.wav
```

- 感情 `caption` は当面付与しない（§2 Out of Scope）。
- 生成物は一旦 **wav** で受け、`ffmpeg` で `audio.format`（既定 `ogg`）へ変換する。

### 7.2 キャッシュ鍵（差分再生成の中核）

```
hash = sha256( text_tts + "\0" + char_key + "\0" + lora_adapter + "\0" + tts_params )
```

- `tts_params` = checkpoint / num_steps / seconds / extra_args を正規化した文字列。
- キャッシュは `cache_dir/{hash}.wav`。**hit なら infer.py を実行しない**。
- セリフ本文・キャラ・LoRA・生成パラメータのいずれかが変われば hash が変わり再生成される。

---

## 8. ファイル命名・配置と連番（キャッシュとの分離）

`[vostart]` は **キャラ単位で連番を自動インクリメント** して `akane_1.ogg`,
`akane_2.ogg`, … を順に再生する。しかし連番はシナリオ上の *出現順（位置）* に依存するため、
セリフを1行挿入すると以降の番号が全てずれる。これを素朴に採番するとキャッシュが総崩れになる。

そこで **2層に分離** する。

1. **TTS キャッシュ層（内容ベース）**: `cache_dir/{hash}.wav`
   - 鍵はテキスト内容（§7.2）。位置に依存しない。高コストな推論結果を保持。
2. **配置層（位置ベース）**: `voice_out_dir/{prefix}_{N}.ogg`
   - `N` はキャラごとにシナリオ出現順で 1 から採番。
   - 各セリフについて「対応する `hash` のキャッシュ wav を `{prefix}_{N}.ogg` へ変換コピー」する。

これにより、行挿入で番号がずれても **再コピー（安価）だけで済み、推論（高コスト）は
内容が変わったセリフのみ** となる。配置層は毎ビルドで作り直してよい。

### 命名規則

| 対象 | 例 |
|---|---|
| キャッシュ | `.irodori_cache/3f9a...c1.wav` |
| 最終音声 | `data/voice/akane_1.ogg`, `data/voice/akane_2.ogg` |
| vostorage テンプレート | `akane_{number}.ogg` |

---

## 9. 書き戻し（TyranoScript への挿入）

### 9.1 挿入内容

- **冒頭（または各キャラ初出直前）に一度** voconfig を挿入:

  ```
  [voconfig sebuf=2 name="akane" vostorage="akane_{number}.ogg" number=1]
  ```

- **各対象セリフの名前欄直後に** vostart を挿入:

  ```
  #あかね
  [vostart]
  こんにちは。今日はいい天気ですね。[p]
  ```

  `[vostart]` は voconfig で設定した現在番号のファイルを再生し、番号を +1 する。
  → 生成側の連番（§8）と一致する。

### 9.2 冪等性（二重挿入の防止）

- 本ツールが挿入する行には必ず **サンプルコメント marker**（既定 `; @irodori-tts`）を付す。
  ```
  [voconfig sebuf=2 name="akane" vostorage="akane_{number}.ogg" number=1]  ; @irodori-tts
  [vostart]  ; @irodori-tts
  ```
- 書き戻しは「**既存の marker 付き行を全削除 → 最新状態で再挿入**」の順で行う。
  これにより再実行しても重複せず、marker の無い（＝ユーザー手書きの）行は一切触らない。
- 破壊防止として、`--dry-run` で挿入差分（unified diff）をプレビューできる。

### 9.3 オート送り・完了待ち

`[voconfig]` 方式はオートモード時にボイス再生完了を待つ（`[playse]` 単体との差分）。
本ツールはタグ挿入のみを担当し、待ち挙動は TyranoScript の voconfig 仕様に委ねる。

---

## 10. CLI 仕様

```
irodori-tyrano <command> [options]

commands:
  scan     .ks を解析し、対象セリフ件数・キャラ別内訳を表示（生成も書き戻しもしない）
  build    差分ビルド: 音声生成（差分のみ）→ 配置 → .ks 書き戻し
  clean    生成音声 / キャッシュ / state を削除

common options:
  -c, --config PATH    設定ファイル（既定: ./config.yaml）
  --chars a,b          対象キャラを一時的に限定（config のサブセット）
  --dry-run            生成・書き戻しをせず計画と diff を表示
  --force              キャッシュを無視して全セリフ再生成
  -v, --verbose        詳細ログ
```

### 想定フロー

```
$ irodori-tyrano scan          # まず対象セリフ数を確認
$ irodori-tyrano build --dry-run   # 挿入 diff をプレビュー
$ irodori-tyrano build         # 生成 + 書き戻し
# ... シナリオ修正 ...
$ irodori-tyrano build         # 変わったセリフだけ再生成
```

---

## 11. 未確定事項・将来拡張

- **A. 話者判定の実サンプル検証**: TyranoBuilder 実出力の `.ks` を入手し、名前欄の実際の
  書式（`#name` / `#name|jname` / `[chara_show]` 併用有無）でパーサを確定する。
- **B. LoRA 未整備時のフォールバック**: 学習済み LoRA が無いキャラを `--ref-wav`（参照音声）
  だけで生成する経路を残すか。
- **C. 感情・スタイル**: VoiceDesign チェックポイント + `caption` / 末尾絵文字による感情制御。
- **D. Irodori-TTS-Server（OpenAI 互換 API）対応**: `infer.py` 直叩きに加え、
  `POST /v1/audio/speech` 経由の生成バックエンドを差し替え可能にする。
- **E. 生成バックエンドの抽象化**: TTS 呼び出しをインターフェース化し LoRA / 参照音声 / API を
  切替可能にする。
- **F. TyranoBuilder GUI / プラグイン化**。

---

## 付録: 参照

- Irodori-TTS 本体: https://github.com/Aratako/Irodori-TTS
- Irodori-TTS-Server（OpenAI 互換 API）: https://github.com/Aratako/Irodori-TTS-Server
- TyranoScript タグリファレンス: https://tyrano.jp/tag/v4
