"""字句解析：プログラムの文字列をトークンの列にする。

綴りはすべて表記表（notation.py）から引く。このファイルに書いてあるのは
「数値」「文字列」「英字の識別子」「注釈」「空白」という、表記が変わっても
変わらない部分だけ。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import LexError
from .notation import Notation, load_notation

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"\d+(\.\d+)?")
_SPACES = " \t　"


@dataclass(frozen=True)
class Token:
    kind: str       # 内部名（"if", "assign", "wo" など）か IDENT/INT/REAL/STRING/TYPE/NEWLINE/EOF
    value: object   # 数値・文字列・識別子名・(基本型, 次元)
    text: str       # 元の綴り
    line: int
    col: int
    indent: int     # その行の字下げ幅。do〜while の終端判定に使う


def _indent_of(raw: str) -> int:
    width = 0
    for ch in raw:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += 4
        elif ch == "　":
            width += 2
        else:
            break
    return width


def tokenize(source: str, notation: Notation | None = None) -> list[Token]:
    notation = notation or load_notation()
    tokens: list[Token] = []
    in_block_comment = False
    comment_start = 0
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    for lineno, raw in enumerate(lines, start=1):
        indent = _indent_of(raw)
        pos, end = 0, len(raw)
        emitted = False

        def add(kind: str, value: object, text: str) -> None:
            nonlocal emitted
            tokens.append(Token(kind, value, text, lineno, pos + 1, indent))
            emitted = True

        while pos < end:
            if in_block_comment:
                close = raw.find("*/", pos)
                if close < 0:
                    pos = end
                    break
                pos = close + 2
                in_block_comment = False
                continue

            ch = raw[pos]
            if ch in _SPACES:
                pos += 1
                continue
            if raw.startswith("//", pos):
                break
            if raw.startswith("/*", pos):
                in_block_comment = True
                comment_start = lineno
                pos += 2
                continue

            if ch == '"':
                close = raw.find('"', pos + 1)
                if close < 0:
                    raise LexError("文字列が閉じられていません", lineno)
                add("STRING", raw[pos + 1:close], raw[pos:close + 1])
                pos = close + 1
                continue

            m = _NUMBER.match(raw, pos)
            if m:
                text = m.group()
                if "." in text:
                    add("REAL", float(text), text)
                else:
                    add("INT", int(text), text)
                pos = m.end()
                continue

            m = _IDENT.match(raw, pos)
            if m:
                text = m.group()
                kind = notation.words.get(text)
                add(kind or "IDENT", text, text)
                pos = m.end()
                continue

            entry = notation.match_fixed(raw, pos)
            if entry:
                spelling, kind, value = entry
                add(kind, value, spelling)
                pos += len(spelling)
                continue

            raise LexError(f"読めない文字です: 「{ch}」", lineno)

        if emitted:
            tokens.append(Token("NEWLINE", None, "", lineno, end + 1, indent))

    if in_block_comment:
        raise LexError("注釈 /* が閉じられていません", comment_start)
    last_line = len(lines)
    tokens.append(Token("EOF", None, "", last_line, 1, 0))
    return tokens
