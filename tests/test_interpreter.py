import pytest

from giji import ExecError, StepLimitError, format_value, run

SUM_MULTIPLES = """
○整数型: calc(整数型の配列: data, 整数型: k)
  整数型: sum ← 0
  整数型: i
  for (i を 1 から dataの要素数 まで 1 ずつ増やす)
    if (data[i] mod k = 0)
      sum ← sum + data[i]
    endif
  endfor
  return sum
"""


def test_for_if_and_array():
    result = run(SUM_MULTIPLES, call="calc({3, 4, 6, 7, 9}, 3)")
    assert result.return_value == 18


def test_trace_records_variable_after_each_pass():
    result = run(SUM_MULTIPLES, call="calc({3, 4, 6, 7, 9}, 3)")
    # 7行目（sum ← sum + data[i]）を通るたびの sum
    assert result.values_at(7, "sum") == [3, 9, 18]
    assert result.count(7) == 3
    # 6行目の条件判定は要素数ぶん
    assert result.count(6, "cond") == 5
    assert [s.detail for s in result.steps if s.line == 6] == [True, False, True, False, True]


def test_trace_snapshot_is_not_changed_by_later_steps():
    source = """
整数型の配列: a ← {1, 2, 3}
a[1] ← 9
"""
    result = run(source)
    assert result.steps[0].vars["a"] == [1, 2, 3]
    assert result.steps[1].vars["a"] == [9, 2, 3]


def test_while_gcd():
    source = """
○整数型: gcd(整数型: a, 整数型: b)
  整数型: r
  while (b ≠ 0)
    r ← a mod b
    a ← b
    b ← r
  endwhile
  return a
"""
    assert run(source, call="gcd(48, 18)").return_value == 6


def test_do_while_runs_body_at_least_once():
    source = """
整数型: n ← 10
整数型: count ← 0
do
  count ← count + 1
  n ← n + 1
while (n < 5)
return count
"""
    assert run(source).return_value == 1


def test_for_decreasing():
    source = """
整数型: i
整数型の配列: out ← {}
for (i を 5 から 1 まで 2 ずつ減らす)
  outの末尾に i を追加する
endfor
return out
"""
    assert run(source).return_value == [5, 3, 1]


def test_elseif_takes_first_true_branch():
    source = """
○文字列型: grade(整数型: score)
  if (score ≧ 80)
    return "A"
  elseif (score ≧ 60)
    return "B"
  else
    return "C"
  endif
"""
    assert run(source, call="grade(85)").return_value == "A"
    assert run(source, call="grade(60)").return_value == "B"
    assert run(source, call="grade(10)").return_value == "C"


def test_recursion():
    source = """
○整数型: fact(整数型: n)
  if (n ≦ 1)
    return 1
  endif
  return n × fact(n - 1)
"""
    result = run(source, call="fact(5)")
    assert result.return_value == 120
    assert max(s.depth for s in result.steps) == 5


def test_binary_search_with_quotient_phrase():
    source = """
○整数型: search(整数型の配列: data, 整数型: target)
  整数型: low ← 1
  整数型: high ← dataの要素数
  整数型: middle
  while (low ≦ high)
    middle ← (low + high) ÷ 2 の商
    if (data[middle] < target)
      low ← middle + 1
    elseif (data[middle] > target)
      high ← middle - 1
    else
      return middle
    endif
  endwhile
  return -1
"""
    assert run(source, call="search({2, 5, 8, 11, 14, 17}, 11)").return_value == 4
    assert run(source, call="search({2, 5, 8, 11, 14, 17}, 3)").return_value == -1


def test_bubble_sort_changes_callers_array():
    source = """
○sort(整数型の配列: a)
  整数型: i, j, tmp
  for (i を 1 から aの要素数 - 1 まで 1 ずつ増やす)
    for (j を 1 から aの要素数 - i まで 1 ずつ増やす)
      if (a[j] > a[j + 1])
        tmp ← a[j]
        a[j] ← a[j + 1]
        a[j + 1] ← tmp
      endif
    endfor
  endfor

整数型の配列: data ← {4, 1, 3, 2}
sort(data)
return data
"""
    assert run(source).return_value == [1, 2, 3, 4]


def test_two_dimensional_array():
    source = """
整数型の二次元配列: m ← {{1, 2, 3}, {4, 5, 6}}
m[2, 1] ← m[1, 3] + m[2, 2]
return m
"""
    assert run(source).return_value == [[1, 2, 3], [8, 5, 6]]


def test_array_fill():
    source = """
整数型: n ← 3
整数型の配列: a ← {n 個の 0}
a[2] ← 7
return a
"""
    assert run(source).return_value == [0, 7, 0]


def test_array_base_is_switchable():
    source = "整数型の配列: a ← {10, 20, 30}\nreturn a[1]"
    assert run(source, array_base=1).return_value == 10
    assert run(source, array_base=0).return_value == 20


def test_out_of_range_reports_line():
    source = "整数型の配列: a ← {10, 20, 30}\nreturn a[0]"
    with pytest.raises(ExecError) as info:
        run(source)
    assert info.value.line == 2


def test_integer_division_modes():
    source = "return 7 ÷ 2"
    with pytest.raises(ExecError):
        run(source)                                   # 既定の strict は割り切れないと誤り
    assert run(source, int_div="quotient").return_value == 3
    assert run(source, int_div="real").return_value == 3.5
    assert run("return 8 ÷ 2").return_value == 4       # 割り切れるなら strict でも可
    assert run("return 7.0 ÷ 2").return_value == 3.5   # 実数が混ざれば常に実数の除算


def test_quotient_phrase_wins_over_mode():
    for mode in ("strict", "quotient", "real"):
        assert run("return 7 ÷ 2 の商", int_div=mode).return_value == 3


def test_negative_division_truncates_toward_zero():
    assert run("return -7 ÷ 2 の商").return_value == -3
    assert run("return -7 mod 2").return_value == -1


def test_division_by_zero():
    with pytest.raises(ExecError):
        run("return 1 ÷ 0")
    with pytest.raises(ExecError):
        run("return 1 mod 0")


def test_and_or_short_circuit():
    # i が範囲外になったら a[i] を評価しない
    source = """
整数型の配列: a ← {1, 2, 3}
整数型: i ← 1
while (i ≦ aの要素数 and a[i] ≠ 9)
  i ← i + 1
endwhile
return i
"""
    assert run(source).return_value == 4


def test_unset_variable_is_an_error():
    with pytest.raises(ExecError) as info:
        run("整数型: x\nreturn x + 1")
    assert "設定されていない" in str(info.value)


def test_undeclared_variable_is_an_error():
    with pytest.raises(ExecError):
        run("x ← 1")


def test_condition_must_be_boolean():
    with pytest.raises(ExecError):
        run("if (1)\nendif")


def test_infinite_loop_is_stopped():
    with pytest.raises(StepLimitError):
        run("while (true)\nendwhile", max_steps=500)


def test_runaway_recursion_is_stopped():
    source = "○整数型: f(整数型: n)\n  return f(n + 1)"
    with pytest.raises(StepLimitError):
        run(source, call="f(1)")


def test_output_statement():
    source = """
整数型: i
for (i を 1 から 3 まで 1 ずつ増やす)
  i × i を出力する
endfor
"""
    assert run(source).outputs == [1, 4, 9]


def test_wrong_argument_count():
    with pytest.raises(ExecError):
        run("○f(整数型: a)\n  return", call="f(1, 2)")


def test_format_value():
    assert format_value([1, [True, "a"]]) == '{1, {true, "a"}}'


def test_remainder_phrase():
    assert run("return 17 ÷ 5 の余り").return_value == 2


def test_negative_divmod_can_be_forbidden():
    from giji import Interpreter, Options, parse_program
    for source in ("return -7 mod 2", "return 7 ÷ -2 の商", "return -8 ÷ 2"):
        with pytest.raises(ExecError):
            Interpreter(parse_program(source), Options(negative_divmod="error")).run()


def test_rows_and_columns_of_a_matrix():
    source = "整数型の二次元配列: m ← {{1, 2, 3}, {4, 5, 6}}\nreturn mの行数 × 10 ＋ mの列数"
    assert run(source).return_value == 23


# ---- 大域変数・未定義・配列によるスタック／キュー ----

STACK = """
大域: 整数型の配列: stack ← {4 個の 0}
大域: 整数型: top ← 0

○push(整数型: x)
  top ← top ＋ 1
  stack[top] ← x

○整数型: pop()
  整数型: v ← stack[top]
  top ← top － 1
  return v

○整数型: test()
  整数型: a
  push(3)
  push(5)
  a ← pop()
  push(7)
  return a ＋ pop() × 10
"""

QUEUE = """
大域: 整数型の配列: queue ← {3 個の 未定義の値}
大域: 整数型: head ← 1, tail ← 1, size ← 0

○enqueue(整数型: x)
  queue[tail] ← x
  tail ← tail mod queueの要素数 ＋ 1
  size ← size ＋ 1

○整数型: dequeue()
  整数型: v ← queue[head]
  queue[head] ← 未定義の値
  head ← head mod queueの要素数 ＋ 1
  size ← size － 1
  return v

○test()
  enqueue(1)
  enqueue(2)
  dequeue() を出力する
  enqueue(3)
  enqueue(4)
  dequeue() を出力する
  dequeue() を出力する
"""

LIST = """
大域: 整数型の配列: dataList ← {10, 30, 20, 40, 未定義の値}
大域: 整数型の配列: pointerList ← {3, 4, 2, 未定義の値, 未定義の値}

○整数型の配列: orderList()
  整数型: p ← 1
  整数型の配列: out ← {}
  while (p が 未定義でない)
    outの末尾に dataList[p] を追加する
    p ← pointerList[p]
  endwhile
  return out
"""


def _run(source, call, **opts):
    return run(source, call=call, **opts)


def _main(source):
    return run(source)


def test_global_stack_shared_between_procedures():
    result = _run(STACK, "test()")
    assert result.return_value == 5 + 70
    # 大域変数は、どの手続の記録にも含まれる（トレース表・設問で追える）
    in_push = [s for s in result.steps if s.proc == "push"]
    assert in_push and all("stack" in s.vars and "top" in s.vars for s in in_push)
    assert in_push[-1].vars["stack"] == [3, 7, 0, 0] and in_push[-1].vars["top"] == 2


def test_ring_queue_with_undefined_slots():
    result = _run(QUEUE, "test()")
    assert result.outputs == [1, 2, 3]
    last = result.steps[-1].vars
    assert format_value(last["queue"]) == "{4, 未定義, 未定義}" and last["size"] == 1


def test_undefined_ends_list_traversal():
    assert _run(LIST, "orderList()").return_value == [10, 20, 30, 40]


def test_is_undefined_on_plain_variables():
    src = "整数型: x\n論理型: a ← x が 未定義\nx ← 1\n論理型: b ← x が 未定義でない\nx ← 未定義の値\n論理型: c ← x が 未定義\n"
    v = _main(src).steps[-1].vars
    assert (v["a"], v["b"], v["c"]) == (True, True, True)


def test_undefined_cannot_be_used_in_arithmetic_or_conditions():
    for body in ("整数型: y ← x ＋ 1", "if (x > 0)\nendif", "整数型の配列: a ← {1, 2}\na[x] ← 1",
                 "整数型の配列: a ← {未定義の値}\n整数型: y ← a[1] × 2"):
        with pytest.raises(ExecError):
            _main("整数型: x\n" + body + "\n")


def test_global_rules():
    # 手続の中では宣言できない
    with pytest.raises(ExecError):
        _run("○f()\n  大域: 整数型: g ← 1\n", "f()")
    # 大域変数と同じ名前の局所変数・引数は認めない
    with pytest.raises(ExecError):
        _run("大域: 整数型: g ← 1\n○f()\n  整数型: g ← 2\n", "f()")
    with pytest.raises(ExecError):
        _run("大域: 整数型: g ← 1\n○f(整数型: g)\n  return\n", "f(1)")
    # 「大域:」のない手続外の変数は、これまでどおり手続からは見えない
    with pytest.raises(ExecError):
        _run("整数型: m ← 1\n○整数型: f()\n  return m\n", "f()")


def test_programs_without_globals_record_the_same_variables():
    result = _run("○整数型: f(整数型: n)\n  整数型: s ← n ＋ 1\n  return s\n", "f(2)")
    assert [sorted(s.vars) for s in result.steps] == [["n", "s"], ["n", "s"]]


# ---- 繰返し処理を終了する・「の値 を追加する」 ----

LIST_BREAK = """
大域: 整数型の配列: dataList ← {10, 30, 20, 40, 未定義の値}
大域: 整数型の配列: pointerList ← {3, 4, 2, 未定義の値, 未定義の値}

○整数型の配列: orderList()
  整数型: i, p ← 1
  整数型の配列: out ← {}
  for (i を 1 から dataListの要素数 まで 1 ずつ増やす)
    outの末尾 に dataList[p]の値 を追加する
    if (pointerList[p] が 未定義)
      繰返し処理を終了する
    endif
    p ← pointerList[p]
  endfor
  return out
"""


def test_break_leaves_only_the_innermost_loop_and_is_recorded():
    result = _run(LIST_BREAK, "orderList()")
    assert result.return_value == [10, 20, 30, 40]
    breaks = [s for s in result.steps if s.kind == "break"]
    assert len(breaks) == 1 and breaks[0].line == 11
    assert breaks[0].vars["i"] == 4                 # 抜けた時点の値のまま
    nested = """
○整数型: f()
  整数型: i, j, n ← 0
  for (i を 1 から 3 まで 1 ずつ増やす)
    j ← 0
    while (true)
      j ← j ＋ 1
      if (j > i)
        繰返し処理を終了する
      endif
      n ← n ＋ 1
    endwhile
  endfor
  return n
"""
    assert _run(nested, "f()").return_value == 1 + 2 + 3
    do_loop = "○整数型: g()\n  整数型: k ← 0\n  do\n    k ← k ＋ 1\n    if (k ＝ 3)\n      繰返し処理を終了する\n    endif\n  while (k < 10)\n  return k\n"
    assert _run(do_loop, "g()").return_value == 3


def test_break_outside_a_loop_is_an_error_even_across_a_call():
    with pytest.raises(ExecError):
        _main("繰返し処理を終了する\n")
    src = "○stop()\n  繰返し処理を終了する\n\n○整数型: f()\n  整数型: i\n  for (i を 1 から 3 まで 1 ずつ増やす)\n    stop()\n  endfor\n  return i\n"
    with pytest.raises(ExecError):
        _run(src, "f()")


def test_append_accepts_both_wordings():
    for line in ("aの末尾に x を追加する", "aの末尾 に x を追加する", "aの末尾 に xの値 を追加する",
                 "aの末尾に b[1]の値 を追加する"):
        src = f"整数型の配列: a ← {{}}\n整数型の配列: b ← {{7}}\n整数型: x ← 7\n{line}\n"
        assert _main(src).steps[-1].vars["a"] == [7], line


def test_output_accepts_the_value_of_wording():
    """「x の値 を出力する」（IPA のサンプル問題の書き方）。「の値」がなくても同じ。"""
    src = "整数型: n ← 3\nnの値 を出力する\n(n ＋ 1) を出力する\nn を出力する\n"
    assert _main(src).outputs == [3, 4, 3]
