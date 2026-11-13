import shutil
from pathlib import Path

import pytest

from giji import (LexError, NotationError, ParseError, load_notation,
                  parse_expression, parse_program, run, tokenize)
from giji import ast_nodes as A
from giji.notation import DEFAULT_NOTATION


def kinds(source):
    return [t.kind for t in tokenize(source)]


def test_tokens_for_declaration():
    assert kinds("整数型: sum ← 0") == ["TYPE", "colon", "IDENT", "assign", "INT", "NEWLINE", "EOF"]


def test_longest_match_prefers_array_type():
    tok = tokenize("整数型の二次元配列: m")[0]
    assert tok.kind == "TYPE" and tok.value == ("int", 2)
    tok = tokenize("文字列型の配列: s")[0]
    assert tok.value == ("string", 1)


def test_fullwidth_and_halfwidth_symbols_are_the_same_token():
    assert kinds("a ＋ b － c") == kinds("a + b - c")
    assert kinds("f（x）") == kinds("f(x)")


def test_keyword_is_not_matched_inside_identifier():
    assert kinds("iffy ← 1")[0] == "IDENT"


def test_comments_are_skipped():
    source = "整数型: a ← 1 // 行末の注釈\n/* 複数行の\n注釈 */\n整数型: b ← 2"
    assert kinds(source).count("TYPE") == 2


def test_for_header_without_spaces():
    # 公開問題には「iを3からnまで1ずつ増やす」のように空白なしの書き方もある
    prog = parse_program("整数型: i\nfor (iを3からnまで1ずつ増やす)\nendfor")
    loop = prog.main[1]
    assert isinstance(loop, A.For) and loop.var == "i" and loop.direction == "inc"


def test_unreadable_character_reports_line():
    with pytest.raises(LexError) as info:
        tokenize("整数型: a ← 1\na ← 2 ＠ 3")
    assert info.value.line == 2


def test_unclosed_block_comment():
    with pytest.raises(LexError):
        tokenize("/* 閉じていない")


def test_precedence_matches_ipa_table():
    # 乗除 > 加減 > 関係 > and > or
    expr = parse_expression("1 + 2 × 3 < 10 and not false or false")
    assert expr.op == "or"
    assert expr.left.op == "and"
    assert expr.left.left.op == "lt"
    assert expr.left.left.left.op == "plus"
    assert expr.left.left.left.right.op == "mul"
    assert isinstance(expr.left.right, A.Unary)


def test_unary_binds_tighter_than_multiplication():
    expr = parse_expression("-2 × 3")
    assert expr.op == "mul" and isinstance(expr.left, A.Unary)


def test_quotient_phrase_marks_division():
    expr = parse_expression("(low + high) ÷ 2 の商")
    assert expr.op == "div" and expr.quotient is True


def test_quotient_phrase_only_after_division():
    with pytest.raises(ParseError):
        parse_expression("a × 2 の商")


def test_procedure_header():
    prog = parse_program("○整数型: f(整数型の配列: data, 整数型: k)\n  return k")
    proc = prog.procs["f"]
    assert proc.return_type == A.TypeSpec("int", 0)
    assert proc.params == [(A.TypeSpec("int", 1), "data"), (A.TypeSpec("int", 0), "k")]


def test_missing_endif_is_an_error():
    with pytest.raises(ParseError):
        parse_program("if (true)\n  return 1")


def test_assignment_target_must_be_variable():
    with pytest.raises(ParseError):
        parse_program("1 ← 2")


def test_do_while_closing_is_decided_by_indent():
    source = """
整数型: i ← 0
整数型: n ← 0
do
  while (n < 2)
    n ← n + 1
  endwhile
  i ← i + 1
while (i < 3)
"""
    prog = parse_program(source)
    loop = prog.main[2]
    assert isinstance(loop, A.DoWhile)
    assert isinstance(loop.body[0], A.While)
    assert len(loop.body) == 2


def test_notation_can_be_swapped_without_touching_lexer(tmp_path):
    # 表記が変わった想定：代入を「:=」、endif を「fi」に差し替える
    text = Path(DEFAULT_NOTATION).read_text(encoding="utf-8")
    text = text.replace('assign: ["←"]', 'assign: [":="]')
    text = text.replace("endif: [endif]", "endif: [fi]")
    custom = tmp_path / "custom.yaml"
    custom.write_text(text, encoding="utf-8")
    notation = load_notation(custom)
    source = "整数型: x := 1\nif (x = 1)\n  x := 5\nfi\nreturn x"
    assert run(source, notation=notation).return_value == 5
    with pytest.raises(LexError):
        run("整数型: x ← 1", notation=notation)


def test_notation_missing_entry_is_reported(tmp_path):
    text = Path(DEFAULT_NOTATION).read_text(encoding="utf-8")
    text = text.replace('  quotient: ["の商"]\n', "")
    broken = tmp_path / "broken.yaml"
    broken.write_text(text, encoding="utf-8")
    with pytest.raises(NotationError):
        load_notation(broken)
