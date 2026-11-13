from pathlib import Path

import pytest

from giji import GenerationError, TemplateError, run
from giji.generator import (BLANK_MARK, generate, load_templates,
                            template_from_dict)

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def make(**overrides):
    data = {
        "id": "t-001",
        "title": "テスト",
        "params": {"n": {"type": "int", "range": [3, 8]}},
        "source": (
            "○整数型: f(整数型: n)\n"
            "  整数型: s ← 0\n"
            "  整数型: i\n"
            "  for (i を 1 から n まで 1 ずつ増やす)\n"
            "    s ← s ＋ i   // @add\n"
            "  endfor\n"
            "  return s\n"
        ),
        "call": "f(${n})",
        "questions": [{"type": "return_value"}],
    }
    data.update(overrides)
    return template_from_dict(data)


def test_marker_is_removed_from_source_and_resolved_to_line():
    template = make()
    assert template.markers == {"add": 5}
    assert "@add" not in template.source and "//" not in template.source


def test_same_seed_gives_same_problem():
    template = make(questions=[{"type": "return_value"},
                               {"type": "var_at_line", "line": "add", "var": "s"}])
    first, second = generate(template, 42), generate(template, 42)
    assert first.source == second.source
    assert [(q.prompt, q.answer, q.choices) for q in first.questions] == \
           [(q.prompt, q.answer, q.choices) for q in second.questions]
    assert any(generate(template, s).params != first.params for s in range(1, 20))


def test_answer_comes_from_real_execution():
    problem = generate(make(), 1)
    expected = run(problem.source, call=problem.call).return_value
    question = problem.questions[0]
    assert question.answer == str(expected)
    assert question.answer in question.choices and len(set(question.choices)) == 4


def test_constraint_filters_parameters():
    template = make(constraints=["${n} mod 2 ＝ 0"])
    assert all(generate(template, s).params["n"] % 2 == 0 for s in range(30))


def test_quality_condition_filters_problems():
    template = make(quality=["count(add) ≧ 6", "result ≠ 0"])
    assert all(generate(template, s).params["n"] >= 6 for s in range(30))


def test_impossible_quality_is_reported_with_reason():
    with pytest.raises(GenerationError) as info:
        generate(make(quality=["count(add) ≧ 100"]), 0, max_attempts=20)
    assert "品質" in str(info.value)


def test_broken_quality_expression_is_a_template_error():
    with pytest.raises(TemplateError):
        generate(make(quality=["count(nowhere) ≧ 1"]), 0)


def test_negative_mod_never_reaches_a_problem():
    # n － 5 が負になる抽選（n < 5）は、実行時の誤りとして捨てられる
    template = make(
        source="○整数型: f(整数型: n)\n  return (n － 5) mod 3\n",
        params={"n": {"type": "int", "range": [1, 9]}},
    )
    for seed in range(40):
        assert generate(template, seed).params["n"] >= 5


def test_exec_count_question():
    template = make(questions=[{"type": "exec_count", "line": "add"}])
    problem = generate(template, 3)
    assert problem.questions[0].answer == str(problem.params["n"])


def test_fill_blank_shows_blank_and_has_one_right_answer():
    template = make(questions=[{
        "type": "fill_blank", "blank": "s ＋ i",
        "distractors": ["s － i", "s × i", "i"],
    }])
    problem = generate(template, 5)
    question = problem.questions[0]
    assert BLANK_MARK in question.source and "s ＋ i" not in question.source
    results = {choice: run(problem.source.replace("s ＋ i", choice),
                           call=problem.call).return_value for choice in question.choices}
    right = [c for c, value in results.items() if value == results[question.answer]]
    assert right == [question.answer]


def test_fill_blank_rejects_draws_with_two_right_answers():
    # 「s ＋ i ＋ 0」は常に正答と同じ結果になるので、1問も作れない
    template = make(questions=[{
        "type": "fill_blank", "blank": "s ＋ i",
        "distractors": ["s ＋ i ＋ 0", "s × i", "i"],
    }])
    with pytest.raises(GenerationError) as info:
        generate(template, 0, max_attempts=20)
    assert "同じ結果" in str(info.value)


def test_unknown_key_and_missing_marker_are_template_errors():
    with pytest.raises(TemplateError):
        make(qualty=["result ≠ 0"])
    with pytest.raises(TemplateError):
        make(questions=[{"type": "exec_count", "line": "nowhere"}])


def test_bundled_templates_generate_valid_problems():
    templates = load_templates(TEMPLATES)
    assert len(templates) >= 8
    for template in templates:
        for seed in range(25):
            problem = generate(template, seed)
            for question in problem.questions:
                assert question.choices is None or question.answer in question.choices


def _bundled(name):
    from giji.generator import load_template
    return load_template(TEMPLATES / "basic" / f"{name}.yaml")


def test_exec_count_choices_are_plausible_counts():
    # 配列の中身（最大30）が実行回数の選択肢に紛れ込まないこと
    template = _bundled("max-index-001")
    for seed in range(60):
        problem = generate(template, seed)
        question = next(q for q in problem.questions if q.type == "exec_count")
        longest = len(problem.params["data"])
        assert all(0 <= int(c) <= longest + 1 for c in question.choices)


def test_array_choices_are_rearrangements_of_the_answer():
    template = _bundled("bubble-pass-001")
    for seed in range(40):
        problem = generate(template, seed)
        for question in problem.questions:
            if question.type in ("return_value", "var_at_line"):
                members = sorted(question.answer.strip("{}").split(", "))
                for choice in question.choices:
                    assert sorted(choice.strip("{}").split(", ")) == members


def test_var_choices_include_a_neighbouring_pass():
    template = make(questions=[{"type": "var_at_line", "line": "add", "var": "s", "pass": 2}])
    problem = generate(template, 2)
    question = problem.questions[0]
    values = problem.result.values_at(5, "s")
    assert question.answer == str(values[1])
    assert str(values[0]) in question.choices or str(values[2]) in question.choices


def test_question_weight_controls_how_often_it_is_asked():
    template = make(questions=[{"type": "return_value", "weight": 0},
                               {"type": "exec_count", "line": "add"}])
    assert {generate(template, s).pick_question().type for s in range(30)} == {"exec_count"}
    problem = generate(template, 1)
    assert problem.pick_question() is problem.pick_question()


def test_low_weight_return_value_in_lookup_templates():
    template = _bundled("max-index-001")
    picks = [generate(template, s).pick_question().type for s in range(200)]
    assert picks.count("return_value") < 40


def test_weights_must_leave_something_to_ask():
    with pytest.raises(TemplateError):
        make(questions=[{"type": "return_value", "weight": 0}])


def test_index_answers_only_offer_valid_element_numbers():
    for name, extra in (("max-index-001", set()), ("binary-search-001", {0})):
        template = _bundled(name)
        for seed in range(60):
            problem = generate(template, seed)
            length = len(problem.params["data"])
            for question in problem.questions:
                if question.type in ("return_value", "var_at_line"):
                    assert len(question.choices) == 4
                    for choice in question.choices:
                        assert 1 <= int(choice) <= length or int(choice) in extra


def test_fill_blank_records_what_each_choice_does():
    problem = generate(_bundled("digit-sum-001"), 4)
    question = next(q for q in problem.questions if q.type == "fill_blank")
    outcomes = question.detail["outcomes"]
    assert set(outcomes) == set(question.choices)
    assert outcomes[question.answer] == f"戻り値は {problem.result.return_value}"
    assert len(set(outcomes.values())) >= 2
