"""IPA 擬似言語（基本情報技術者試験 科目B）のサブセット処理系。

    from giji import run
    result = run(source, call="calc({3, 6, 9}, 3)")
    result.return_value, result.steps
"""

from __future__ import annotations

from .errors import (ExecError, GenerationError, GijiError, LexError,
                     NotationError, ParseError, StepLimitError, TemplateError)
from .interpreter import (UNSET, Interpreter, Options, RunResult, Step,
                          format_value)
from .lexer import Token, tokenize
from .notation import Notation, load_notation
from .parser import parse_expression, parse_program

__all__ = [
    "run", "tokenize", "parse_program", "parse_expression", "load_notation",
    "Interpreter", "Options", "RunResult", "Step", "Token", "Notation",
    "UNSET", "format_value",
    "GijiError", "NotationError", "LexError", "ParseError", "ExecError",
    "StepLimitError", "TemplateError", "GenerationError",
]


def run(source: str, call: str | None = None, *, array_base: int = 1,
        int_div: str = "strict", max_steps: int = 10_000,
        notation: Notation | None = None) -> RunResult:
    """プログラムを実行してトレースつきの結果を返す。

    call には「calc({1, 2, 3}, 2)」のような呼出し式を擬似言語で書く。
    """
    notation = notation or load_notation()
    program = parse_program(source, notation)
    call_expr = parse_expression(call, notation) if call else None
    options = Options(array_base=array_base, int_div=int_div, max_steps=max_steps)
    return Interpreter(program, options).run(call_expr)
