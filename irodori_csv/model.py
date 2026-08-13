"""シナリオCSVのデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field


# CSV のヘッダ列名（SPEC §4.2 / §4.3）
CHAR_HEADERS = ["キャラ名", "参照番号", "LoRAフォルダ", "生成ファイルヘッド", "キャプション"]
LINE_HEADERS = ["参照番号", "テキスト", "送信テキスト", "キャプション"]

# セクション判定に使う特徴列
CHAR_MARKER = "LoRAフォルダ"
LINE_MARKER = "送信テキスト"


@dataclass
class Character:
    """キャラクター定義（CSV 定義セクションの 1 行）。"""

    name: str          # キャラ名（表示・サブフォルダ名）
    ref: str           # 参照番号（セリフ側との結合キー・一意）
    lora_dir: str      # LoRA アダプタのフォルダパス
    head: str          # 生成ファイルヘッド（出力名のプレフィックス）
    caption: str = ""  # v4: 既定のキャプション（声質・話し方。行側が空ならこれを使う）


@dataclass
class Line:
    """セリフ（CSV セリフセクションの 1 行）。"""

    ref: str           # 参照番号（定義を指す）
    text: str          # 原文（人間可読）
    send_text: str     # Irodori-TTS へ送る顔文字付きテキスト
    caption: str = ""  # v4: この行のキャプション（感情・話し方。空ならキャラ既定にフォールバック）

    def tts_text(self) -> str:
        """TTS へ渡すテキスト。送信テキストが空なら原文にフォールバック（SPEC §4.3）。"""
        return self.send_text if self.send_text.strip() else self.text


def effective_caption(line: "Line", character: "Character | None") -> str:
    """行に適用するキャプション。行が空ならキャラ既定、どちらも空なら ""。"""
    if line.caption.strip():
        return line.caption.strip()
    if character is not None and character.caption.strip():
        return character.caption.strip()
    return ""


@dataclass
class Scenario:
    characters: list[Character] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    def character_by_ref(self, ref: str) -> Character | None:
        for c in self.characters:
            if c.ref == ref:
                return c
        return None
