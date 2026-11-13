"""本番形式の出題：IPA の公開問題の体裁に合わせて、1つのプログラムに1問を作る。

練習モードとの違い
  - 行番号を使わない。行は「/*** α ***/」という注釈の目印で指す
  - 問いは定型文（「次のプログラム中の［ａ］に入れる…」「次の記述中の［ａ］に入れる…」）
  - 解答群は4〜6個（公開問題で多い個数）。空欄が2つのときは、ａとｂの組合せから選ぶ
  - 読点は「，」

元になる値（正解・行・変数）は練習モードの設問と同じものを使うので、
ここでも答えは必ず実行結果と一致する。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import generator as G
from .errors import GijiError
from .explain import explain
from .generator import Problem, Template
from .interpreter import Interpreter, Options, format_value
from .parser import parse_expression, parse_program

BLANK_A = "［　ａ　］"
BLANK_B = "［　ｂ　］"
MARK = "α"
MIN_CHOICES = 4
MAX_CHOICES = 6

LEAD_PROGRAM = "次のプログラム中の{blanks}に入れる正しい答え{combo}を，解答群の中から選べ。"
LEAD_STATEMENT = "次の記述中の{blanks}に入れる正しい答え{combo}を，解答群の中から選べ。"


@dataclass
class ExamQuestion:
    form: str                   # program_blank / statement
    lead: str                   # 問いの定型文
    body: list                  # 問題文の段落（前置き、記述）
    source: str                 # 見せるプログラム（空欄つきのことがある）
    markers: dict               # 行番号 -> 目印（α）
    blanks: list                # ["ａ"] か ["ａ", "ｂ"]
    choices: list               # 各選択肢は、空欄ごとの文字列の並び
    answer_index: int
    explain: list
    focus: dict = field(default_factory=dict)   # トレース表で強調する 行・変数・ステップ


def comma(text: str) -> str:
    """読点を本試験の書き方（，）にそろえる。"""
    return text.replace("、", "，")


def _lead(pattern: str, blanks: list) -> str:
    marks = "と".join(f"［　{b}　］" for b in blanks)
    return pattern.format(blanks=marks, combo="の組合せ" if len(blanks) > 1 else "")


def _name(problem: Problem) -> str:
    return (problem.call or "").split("(")[0]


def _find(problem: Problem, kind: str):
    return next((q for q in problem.questions if q.type == kind), None)


def _spec(template: Template, kind: str) -> dict:
    return next((q for q in template.questions if q["type"] == kind), {})


def _context(template: Template, problem: Problem) -> dict:
    return {"template": template, "values": problem.params}


def _options_for(question, template: Template, problem: Problem, rng, size: int) -> list | None:
    """練習モードと同じ規則で、指定した個数の選択肢（正解を含む）を作る。"""
    result = problem.result
    spec = _spec(template, question.type)
    rule = G._domain_rule(spec, _context(template, problem))
    if question.type == "exec_count":
        line = question.detail["line"]
        value = G._exec_count(result, line)
        return G._choices_exec_count(value, line, result, problem.params, rng, size=size)
    if question.type == "var_at_line":
        d = question.detail
        value = result.values_at(d["line"], d["var"])[d["pass"] - 1]
        return G._choices_var_at_line(value, d["line"], d["var"], d["pass"], result, rng, rule, size=size)
    if question.type == "return_value" and result.return_value is not None:
        return G._choices_return_value(result.return_value, result, rng, rule, size=size)
    return None


def _many(question, template, problem, rng) -> list | None:
    for size in (MAX_CHOICES, 5, MIN_CHOICES):
        choices = _options_for(question, template, problem, rng, size)
        if choices:
            return choices
    return None


def _called(problem: Problem) -> str:
    return f"関数 {_name(problem)} を {problem.call} として呼び出"


def _phrase(question, problem: Problem, blank: str) -> str:
    """設問1つ分を、記述の中に埋め込める句にする（文末なし）。"""
    d = question.detail
    if question.type == "return_value":
        return f"戻り値は{blank}とな"
    if question.type == "exec_count":
        kinds = {s.kind for s in problem.result.steps
                 if s.line == d["line"] and s.kind not in ("for_init", "for_step")}
        if kinds == {"cond"}:
            return f"プログラム中の {MARK} の行の条件式は{blank}回評価され"
        return f"プログラム中の {MARK} の行は{blank}回実行され"
    when = "実行した直後" if d["passes"] == 1 else f"{d['pass']}回目に実行した直後"
    return f"プログラム中の {MARK} の行を{when}の変数 {d['var']} の値は{blank}とな"


def _focus(question, problem: Problem) -> dict:
    d = question.detail
    steps = problem.result.steps
    if question.type == "var_at_line":
        hits = [s for s in steps if s.line == d["line"] and d["var"] in s.vars]
        return {"line": d["line"], "variable": d["var"], "step": hits[d["pass"] - 1].index}
    if question.type == "exec_count":
        return {"line": d["line"], "variable": None, "step": None}
    returns = [s for s in steps if s.kind == "return"]
    if not returns:
        return {"line": None, "variable": None, "step": None}
    top = min(s.depth for s in returns)
    last = [s for s in returns if s.depth == top][-1]
    return {"line": last.line, "variable": None, "step": last.index}


def _markers(*questions) -> dict:
    lines = {q.detail["line"] for q in questions if q.type in ("exec_count", "var_at_line")}
    return {line: MARK for line in lines}


# ---- 出題の型 ----

def _statement_single(kind: str):
    def build(template, problem, rng, min_weight):
        question = _find(problem, kind)
        if question is None or question.weight < min_weight:
            return None
        choices = _many(question, template, problem, rng)
        if not choices or len(choices) < MIN_CHOICES:
            return None
        phrase = _phrase(question, problem, BLANK_A)
        ending = "る。" if phrase.endswith(("され", "とな")) else "。"
        linking = "すと，" if question.type == "return_value" else "したとき，"
        return ExamQuestion(
            form="statement", lead=_lead(LEAD_STATEMENT, ["ａ"]),
            body=[comma(problem.description), f"{_called(problem)}{linking}{phrase}{ending}"],
            source=problem.source, markers=_markers(question), blanks=["ａ"],
            choices=[[c] for c in choices], answer_index=choices.index(question.answer),
            explain=explain(problem, question), focus=_focus(question, problem))
    return build


def _statement_pair(template, problem, rng, min_weight):
    """記述に空欄を2つ置き、ａとｂの組合せを選ばせる。"""
    first = _find(problem, "exec_count")
    second = _find(problem, "return_value")
    if second is None or second.weight < min_weight:
        second = None
    if first is None:
        return None
    if second is None:
        second = _find(problem, "var_at_line")
        if second is None or second.detail["line"] != first.detail["line"]:
            return None
    a_options = _options_for(first, template, problem, rng, 3)
    b_options = _options_for(second, template, problem, rng, 3)
    if not a_options or not b_options or len(a_options) < 3 or len(b_options) < 3:
        return None
    pairs = [[a, b] for a in a_options for b in b_options]
    correct = [first.answer, second.answer]
    wrong = [p for p in pairs if p != correct]
    rng.shuffle(wrong)
    keep = wrong[:MAX_CHOICES - 1] + [correct]
    choices = [p for p in pairs if p in keep]          # ａ，ｂの順に整然と並べる

    if second.type == "return_value":
        text = f"{_called(problem)}すと，{_phrase(first, problem, BLANK_A)}，{_phrase(second, problem, BLANK_B)}る。"
    else:
        text = (f"{_called(problem)}したとき，{_phrase(first, problem, BLANK_A)}，"
                f"{_phrase(second, problem, BLANK_B).replace(f'プログラム中の {MARK} の行を', '')}る。")
    return ExamQuestion(
        form="statement", lead=_lead(LEAD_STATEMENT, ["ａ", "ｂ"]),
        body=[comma(problem.description), text], source=problem.source,
        markers=_markers(first, second), blanks=["ａ", "ｂ"], choices=choices,
        answer_index=choices.index(correct),
        explain=explain(problem, first) + explain(problem, second),
        focus=_focus(first, problem))


def _run(source: str, template: Template, problem: Problem) -> tuple:
    options = Options(array_base=template.array_base, int_div=template.int_div,
                      negative_divmod="error", max_steps=template.max_steps)
    try:
        call = parse_expression(problem.call) if problem.call else None
        result = Interpreter(parse_program(source), options).run(call)
    except GijiError as err:
        return ("error", type(err).__name__, err.message)
    return ("ok", format_value(result.return_value), [format_value(v) for v in result.outputs])


def _program_blank(template, problem, rng, min_weight):
    """プログラムに空欄を置く。テンプレートに blank_b があれば、ａとｂの組合せにする。"""
    spec = _spec(template, "fill_blank")
    result = problem.result
    if not spec or (result.return_value is None and not result.outputs):
        return None
    values = problem.params
    blank_a = G._substitute(str(spec["blank"]), values)
    wrong_a = [G._substitute(str(t), values) for t in spec["distractors"]]
    source = problem.source
    if source.count(blank_a) != 1:
        return None
    correct_outcome = _run(source, template, problem)
    outcomes: dict = {}

    def outcome_of(filled: str) -> tuple:
        if filled not in outcomes:
            outcomes[filled] = _run(filled, template, problem)
        return outcomes[filled]

    blank_b = G._substitute(str(spec["blank_b"]), values) if spec.get("blank_b") else None
    if blank_b and source.count(blank_b) == 1 and blank_b not in blank_a and blank_a not in blank_b:
        wrong_b = [G._substitute(str(t), values) for t in spec["distractors_b"]]
        a_options = [blank_a] + rng.sample(wrong_a, 2)
        b_options = [blank_b] + rng.sample(wrong_b, 2)
        rng.shuffle(a_options)
        rng.shuffle(b_options)
        choices, lines = [], []
        for a in a_options:
            for b in b_options:
                got = outcome_of(source.replace(blank_a, a).replace(blank_b, b))
                is_answer = (a, b) == (blank_a, blank_b)
                if is_answer or got != correct_outcome:      # 正解と同じ結果になる誤答は出さない
                    choices.append([a, b])
                    lines.append(f"ａ「{a}」，ｂ「{b}」→ {G._outcome_text(got)}{'（正解）' if is_answer else ''}")
        if len(choices) < MIN_CHOICES:
            return None
        while len(choices) > MAX_CHOICES:
            drop = next(i for i in range(len(choices) - 1, -1, -1) if choices[i] != [blank_a, blank_b])
            choices.pop(drop)
            lines.pop(drop)
        shown = source.replace(blank_a, BLANK_A).replace(blank_b, BLANK_B)
        blanks, answer = ["ａ", "ｂ"], [blank_a, blank_b]
    else:
        usable = [w for w in wrong_a if outcome_of(source.replace(blank_a, w)) != correct_outcome]
        if len(usable) < MIN_CHOICES - 1:
            return None
        picked = rng.sample(usable, min(len(usable), MAX_CHOICES - 1)) + [blank_a]
        rng.shuffle(picked)
        choices = [[c] for c in picked]
        lines = []
        for c in picked:
            got = correct_outcome if c == blank_a else outcome_of(source.replace(blank_a, c))
            lines.append(f"「{c}」→ {G._outcome_text(got)}{'（正解）' if c == blank_a else ''}")
        shown = source.replace(blank_a, BLANK_A)
        blanks, answer = ["ａ"], [blank_a]

    line = next(n for n, text in enumerate(source.split("\n"), start=1) if blank_a in text)
    if result.return_value is not None:
        fact = f"{_called(problem)}すと，戻り値は {format_value(result.return_value)} となる。"
    else:
        # 戻り値のない手続は、出力の並びを手がかりにする
        shown_outputs = "，".join(format_value(v) for v in result.outputs)
        order = "の順に出力される" if len(result.outputs) > 1 else "が出力される"
        fact = f"手続 {_name(problem)} を {problem.call} として呼び出すと，{shown_outputs} {order}。"
    return ExamQuestion(
        form="program_blank", lead=_lead(LEAD_PROGRAM, blanks),
        body=[comma(problem.description), fact], source=shown, markers={}, blanks=blanks,
        choices=choices, answer_index=choices.index(answer),
        explain=["それぞれの選択肢を空欄に入れて，実際に動かした結果は次のとおりです。"] + lines,
        focus={"line": line, "variable": None, "step": None})


_FORMS = [
    _program_blank,
    _statement_single("var_at_line"),
    _statement_pair,
    _statement_single("return_value"),
    _statement_single("exec_count"),
]


def build_exam(template: Template, problem: Problem, number: int = 1,
               min_weight: float = 0.5) -> ExamQuestion | None:
    """本番形式の問題を1つ作る。問題番号ごとに出題の型を変える。作れなければ None。"""
    rng = random.Random(f"{problem.template_id}:{problem.seed}:exam")
    start = (number - 1) % len(_FORMS)
    for form in _FORMS[start:] + _FORMS[:start]:
        question = form(template, problem, rng, min_weight)
        if question is not None:
            return question
    return None
