from pathlib import Path

import pytest

from giji import run
from giji.exam import BLANK_A, BLANK_B, MARK, build_exam
from giji.generator import generate, load_templates

TEMPLATES = load_templates(Path(__file__).resolve().parent.parent / "templates" / "basic")
BY_ID = {t.id: t for t in TEMPLATES}


def exams(template, count=30):
    for number in range(1, count + 1):
        problem = generate(template, number)
        yield number, problem, build_exam(template, problem, number)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_every_problem_gets_one_exam_question_in_the_official_layout(template):
    forms = set()
    for _, problem, exam in exams(template, 20):
        assert exam is not None
        forms.add((exam.form, len(exam.blanks)))
        assert exam.lead.endswith("を，解答群の中から選べ。")
        assert ("次のプログラム中の" in exam.lead) == (exam.form == "program_blank")
        assert ("の組合せ" in exam.lead) == (len(exam.blanks) == 2)
        assert 6 <= len(exam.choices) <= 8
        assert len({tuple(c) for c in exam.choices}) == len(exam.choices)
        assert all(len(c) == len(exam.blanks) for c in exam.choices)
        assert "、" not in "".join(exam.body)                 # 読点は「，」
        for line, mark in exam.markers.items():
            assert mark == MARK and 1 <= line <= len(problem.source.split("\n"))
        if exam.markers:
            assert MARK in exam.body[-1]
    assert len(forms) >= 2                                     # 型が1つに偏らない


def test_statement_answers_match_the_real_run():
    template = BY_ID["loop-sum-001"]
    for number, problem, exam in exams(template):
        if exam.form == "statement" and "戻り値は" in exam.body[-1] and len(exam.blanks) == 1:
            assert exam.choices[exam.answer_index] == [str(problem.result.return_value)]
            return
    pytest.fail("戻り値を問う記述の問題が出なかった")


def test_program_blank_has_exactly_one_choice_that_reproduces_the_result():
    checked = 0
    for template in (BY_ID["loop-sum-001"], BY_ID["longest-run-001"], BY_ID["tally-001"]):
        for _, problem, exam in exams(template):
            if exam.form != "program_blank":
                continue
            checked += 1
            assert BLANK_A in exam.source
            expected = problem.result.return_value
            matches = []
            for index, choice in enumerate(exam.choices):
                filled = exam.source.replace(BLANK_A, choice[0])
                if len(choice) == 2:
                    filled = filled.replace(BLANK_B, choice[1])
                try:
                    got = run(filled, call=problem.call, max_steps=template.max_steps).return_value
                except Exception:
                    got = object()
                if got == expected:
                    matches.append(index)
            assert matches == [exam.answer_index]
    assert checked >= 5


def test_pair_format_appears_for_statements_and_programs():
    seen = set()
    for template in TEMPLATES:
        for _, _, exam in exams(template, 12):
            if len(exam.blanks) == 2:
                seen.add(exam.form)
    assert seen == {"statement", "program_blank"}


def test_exam_question_is_stable_for_the_same_problem():
    template = BY_ID["while-gcd-001"]
    problem = generate(template, 9)
    first, second = build_exam(template, problem, 3), build_exam(template, problem, 3)
    assert (first.lead, first.body, first.choices, first.answer_index) == \
           (second.lead, second.body, second.choices, second.answer_index)
