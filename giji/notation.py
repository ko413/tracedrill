"""表記の対応表（YAML）を読み込む。

字句解析器はキーワードや記号の綴りを一切知らず、ここで作った表だけを見る。
試験制度の改定で表記が変わっても、YAML を差し替えれば済むようにするため。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .errors import NotationError

DEFAULT_NOTATION = Path(__file__).parent / "notation" / "fe-2023.yaml"

# 構文解析器が前提にしている内部名。YAML に欠けていたら読み込み時に止める。
REQUIRED_WORDS = {
    "if", "elseif", "else", "endif", "while", "endwhile", "do", "for",
    "endfor", "return", "true", "false", "and", "or", "not", "mod",
}
REQUIRED_SYMBOLS = {
    "assign", "mul", "div", "plus", "minus", "ne", "le", "ge", "lt", "gt",
    "eq", "lparen", "rparen", "lbracket", "rbracket", "lbrace", "rbrace",
    "comma", "colon", "proc_mark",
}
REQUIRED_PHRASES = {
    "wo", "from", "to", "step", "inc", "dec", "output", "length", "rows", "cols",
    "append_to", "append", "count_of", "quotient", "remainder",
}
REQUIRED_TYPES = {"int", "real", "bool", "char", "string"}


@dataclass
class Notation:
    name: str
    #: 英字キーワードの綴り -> 内部名
    words: dict[str, str] = field(default_factory=dict)
    #: (綴り, 内部名, 値) を綴りの長い順に並べたもの。記号・定型句・型名。
    fixed: list[tuple[str, str, object]] = field(default_factory=list)
    #: 内部名 -> 表示用の綴り（プログラムを画面に出すときに使う）
    spelling: dict[str, str] = field(default_factory=dict)
    #: (基本型, 次元) -> 表示用の綴り
    type_names: dict[tuple[str, int], str] = field(default_factory=dict)

    def match_fixed(self, text: str, pos: int) -> tuple[str, str, object] | None:
        """text の pos 位置から始まる最長の綴りを返す。"""
        for entry in self.fixed:
            if text.startswith(entry[0], pos):
                return entry
        return None


def _as_list(value) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _check(section: str, got: dict, required: set[str]) -> None:
    missing = required - {str(k) for k in got}
    if missing:
        raise NotationError(f"表記表の {section} に不足があります: {sorted(missing)}")


@lru_cache(maxsize=None)
def load_notation(path: str | Path | None = None) -> Notation:
    path = Path(path) if path else DEFAULT_NOTATION
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    words_raw = {str(k): v for k, v in (data.get("words") or {}).items()}
    symbols_raw = {str(k): v for k, v in (data.get("symbols") or {}).items()}
    phrases_raw = {str(k): v for k, v in (data.get("phrases") or {}).items()}
    types_raw = data.get("types") or {}
    base_raw = {str(k): str(v) for k, v in (types_raw.get("base") or {}).items()}
    suffix_raw = {int(k): str(v) for k, v in (types_raw.get("array_suffix") or {}).items()}

    _check("words", words_raw, REQUIRED_WORDS)
    _check("symbols", symbols_raw, REQUIRED_SYMBOLS)
    _check("phrases", phrases_raw, REQUIRED_PHRASES)
    _check("types.base", base_raw, REQUIRED_TYPES)

    notation = Notation(name=str(data.get("name", path.stem)))
    seen: dict[str, str] = {}

    def claim(spelling: str, kind: str) -> None:
        if spelling in seen:
            raise NotationError(
                f"綴り「{spelling}」が {seen[spelling]} と {kind} の両方に使われています"
            )
        seen[spelling] = kind

    for kind, spellings in words_raw.items():
        spellings = _as_list(spellings)
        notation.spelling[kind] = spellings[0]
        for s in spellings:
            claim(s, kind)
            notation.words[s] = kind

    fixed: list[tuple[str, str, object]] = []
    for section in (symbols_raw, phrases_raw):
        for kind, spellings in section.items():
            spellings = _as_list(spellings)
            notation.spelling[kind] = spellings[0]
            for s in spellings:
                claim(s, kind)
                fixed.append((s, kind, None))

    for base, base_name in base_raw.items():
        claim(base_name, f"type:{base}")
        fixed.append((base_name, "TYPE", (base, 0)))
        notation.type_names[(base, 0)] = base_name
        for dims, suffix in suffix_raw.items():
            full = base_name + suffix
            claim(full, f"type:{base}[{dims}]")
            fixed.append((full, "TYPE", (base, dims)))
            notation.type_names[(base, dims)] = full

    # 最長一致にするため、長い綴りを先に試す（「整数型の配列」を「整数型」より先に）。
    fixed.sort(key=lambda e: len(e[0]), reverse=True)
    notation.fixed = fixed
    return notation
