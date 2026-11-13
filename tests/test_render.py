from giji import run
from giji.render import source_html, trace_html, trace_rows

SOURCE = """○整数型: f(整数型: n)
  整数型: s ← 0
  整数型: i
  for (i を 1 から n まで 1 ずつ増やす)
    s ← s ＋ i
  endfor
  return s"""


def test_source_has_a_number_on_every_line_and_marks_focus():
    page = source_html(SOURCE, [5])
    assert page.count('class="no"') == 7
    assert '<tr class="focus" data-line="5"><td class="no">5</td>' in page


def test_source_is_escaped():
    assert "<script>" not in source_html('"<script>" を出力する')
    assert "&lt;script&gt;" in source_html('"<script>" を出力する')


def test_trace_rows_cover_every_step_and_mark_the_asked_pass():
    result = run(SOURCE, call="f(3)")
    names, rows = trace_rows(result, focus_line=5, focus_var="s", focus_pass=2)
    assert names == ["n", "s", "i"]
    assert len(rows) == len(result.steps)
    assert [r["mark"] for r in rows if r["line"] == 5] == ["line", "pass", "line"]
    marked = next(r for r in rows if r["mark"] == "pass")
    assert marked["cells"]["s"] == ("3", True)      # 2回目の直後は 1 ＋ 2
    assert marked["cells"]["n"] == ("3", False)     # n は変わっていない


def test_unset_variable_is_shown_as_unset():
    result = run(SOURCE, call="f(1)")
    _, rows = trace_rows(result)
    assert rows[0]["cells"]["i"] == ("", False) and rows[1]["cells"]["i"] == ("未定義", False)


def test_trace_html_highlights_row_and_column():
    result = run(SOURCE, call="f(3)")
    page = trace_html(result, 5, "s", 2)
    assert page.count('class="focus-pass"') == 1
    assert page.count('class="focus-line"') == 2
    assert '<th class="focus-col" data-var="s">s</th>' in page


def test_recursion_shows_procedure_column():
    source = "○整数型: f(整数型: n)\n  if (n ≦ 1)\n    return 1\n  endif\n  return n ＋ f(n － 1)"
    assert "<th>手続</th>" in trace_html(run(source, call="f(3)"))
    assert "<th>手続</th>" not in trace_html(run(SOURCE, call="f(2)"))
