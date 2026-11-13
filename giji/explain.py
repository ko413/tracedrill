"""設問ごとの解説文を、実行の記録（トレース）から自動で作る。

テンプレートに書いた解説は「考え方」の説明で、どの問題でも同じ文になる。
ここで作るのは「この値のときに何が起きたか」の説明で、問題ごとに変わる。
値はすべて実行結果から取るので、解説と答えが食い違うことはない。
"""

from __future__ import annotations

from .generator import Problem, Question
from .interpreter import UNSET, format_value

_NOT_COUNTED = ("for_init", "for_step")
_MAX_LISTED = 12


def _arrow(values: list) -> str:
    """値の移り変わりを「0 → 3 → 9」の形にする。長いときは途中を省く。"""
    texts = [format_value(v) for v in values]
    if len(texts) > _MAX_LISTED:
        texts = texts[:5] + ["…"] + texts[-5:]
    return " → ".join(texts)


def _dedupe(values: list) -> list:
    """同じ値が続く所を1つにまとめる（変わった時点だけを残す）。"""
    out: list = []
    for value in values:
        if value is UNSET:
            continue
        if not out or format_value(out[-1]) != format_value(value):
            out.append(value)
    return out


def _explain_var_at_line(problem: Problem, question: Question) -> list[str]:
    detail = question.detail
    line, var, nth = detail["line"], detail["var"], detail["pass"]
    values = problem.result.values_at(line, var)
    lines = [f"{line}行目は全部で{len(values)}回実行されます。"]
    if len(values) > 1:
        lines.append(f"実行した直後の {var} は、順に {_arrow(values)} です。")
        lines.append(f"{nth}回目の直後なので、答えは {question.answer} です。")
    else:
        lines.append(f"実行した直後の {var} は {question.answer} です。")
    return lines


def _explain_exec_count(problem: Problem, question: Question) -> list[str]:
    steps = problem.result.steps
    line = question.detail["line"]
    hits = [i for i, s in enumerate(steps) if s.line == line and s.kind not in _NOT_COUNTED]
    if not hits:
        return [f"{line}行目は一度も実行されません。"]
    if all(steps[i].kind == "cond" for i in hits):
        true_count = sum(1 for i in hits if steps[i].detail is True)
        return [f"{line}行目の条件式は{len(hits)}回評価され、真が{true_count}回、"
                f"偽が{len(hits) - true_count}回です。"]

    # 直前が条件判定なら、その条件が真になった回数と結び付けて説明する
    guards = {steps[i - 1].line for i in hits
              if i > 0 and steps[i - 1].kind == "cond" and steps[i - 1].depth == steps[i].depth}
    if len(guards) == 1:
        guard = guards.pop()
        checks = [s for s in steps if s.line == guard and s.kind == "cond"]
        true_count = sum(1 for s in checks if s.detail is True)
        if true_count == len(hits) and len(checks) != len(hits):
            return [f"{line}行目が実行されるのは、{guard}行目の条件が真になったときだけです。",
                    f"{guard}行目の条件は{len(checks)}回評価され、真になるのは{true_count}回です。"
                    f"したがって {line}行目は{len(hits)}回実行されます。"]
    return [f"{line}行目は{len(hits)}回実行されます。トレース表で {line}行目の行を数えると確かめられます。"]


def _explain_return_value(problem: Problem, question: Question) -> list[str]:
    result = problem.result
    returns = [s for s in result.steps if s.kind == "return"]
    if not returns:
        return [f"出力された値は {question.answer} です。"]
    top = min(s.depth for s in returns)
    last = [s for s in returns if s.depth == top][-1]

    if any(s.depth > top for s in returns):
        inner = [s.detail for s in returns]
        return [f"呼出しは全部で{len(returns)}回行われます。",
                f"奥の呼出しから順に {_arrow(inner)} を返し、最後に返る {question.answer} が答えです。"]

    for name, final in last.vars.items():
        if format_value(final) != question.answer:
            continue
        history = _dedupe([s.vars[name] for s in result.steps
                           if s.depth == last.depth and s.proc == last.proc and name in s.vars])
        if len(history) > 1:
            return [f"戻り値になる {name} は、{_arrow(history)} と変わります。",
                    f"{last.line}行目で返す時点の値 {question.answer} が答えです。"]
    return [f"{last.line}行目で {question.answer} を返します。"]


def _explain_fill_blank(problem: Problem, question: Question) -> list[str]:
    outcomes = question.detail.get("outcomes", {})
    lines = ["それぞれの選択肢を空欄に入れて、実際に動かした結果は次のとおりです。"]
    for choice in question.choices:
        mark = "（正解）" if choice == question.answer else ""
        lines.append(f"「{choice}」→ {outcomes.get(choice, '')}{mark}")
    return lines


_EXPLAINERS = {
    "var_at_line": _explain_var_at_line,
    "exec_count": _explain_exec_count,
    "return_value": _explain_return_value,
    "fill_blank": _explain_fill_blank,
}


def explain(problem: Problem, question: Question) -> list[str]:
    """設問1つ分の解説を、文の並びで返す。"""
    return _EXPLAINERS[question.type](problem, question)
