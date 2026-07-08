"""シナリオCSVのデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field


# CSV のヘッダ列名（SPEC §4.2 / §4.3）
CHAR_HEADERS = ["キャラ名", "参照番号", "LoRAフォルダ", "生成ファイルヘッド"]
LINE_HEADERS = ["参照番号", "テキスト", "送信テキスト"]

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


@dataclass
class Line:
    """セリフ（CSV セリフセクションの 1 行）。"""

    ref: str           # 参照番号（定義を指す）
    text: str          # 原文（人間可読）
    send_text: str     # Irodori-TTS へ送る顔文字付きテキスト

    def tts_text(self) -> str:
        """TTS へ渡すテキスト。送信テキストが空なら原文にフォールバック（SPEC §4.3）。"""
        return self.send_text if self.send_text.strip() else self.text


@dataclass
class Scenario:
    characters: list[Character] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    def character_by_ref(self, ref: str) -> Character | None:
        for c in self.characters:
            if c.ref == ref:
                return c
        return None
