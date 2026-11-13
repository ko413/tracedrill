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
