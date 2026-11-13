"""画面の通しテスト。Streamlit が入っていない環境では飛ばす。"""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def open_app(template_id=None, seed=None):
    app = AppTest.from_file(APP, default_timeout=30)
    if template_id:
        app.query_params["q"] = template_id
        app.query_params["s"] = str(seed)
    return app.run()


def click(app, label):
    button = next(b for b in app.button if b.label == label)
    return button.click().run()


def page_text(app) -> str:
    return "\n".join(str(m.value) for m in app.markdown)


def test_first_screen_shows_numbered_program_and_one_question():
    app = open_app("loop-sum-001", 7)
    assert not app.exception
    text = page_text(app)
    assert 'class="giji-code"' in text and '<td class="no">1</td>' in text
    assert text.count("**設問**") == 1
    assert 'class="giji-trace"' not in text          # 解答前はトレース表を出さない


def test_url_reproduces_the_same_problem():
    first, second = open_app("while-gcd-001", 123), open_app("while-gcd-001", 123)
    assert page_text(first) == page_text(second)


@pytest.mark.parametrize("seed", range(12))
def test_answer_then_explanation_then_next(seed):
    from giji.generator import generate, load_templates
    root = Path(APP).parent
    templates = load_templates(root / "templates" / "basic")
    template = templates[seed % len(templates)]
    question = generate(template, seed).pick_question()

    app = open_app(template.id, seed)
    if question.choices:
        app.radio[0].set_value(question.answer)
    else:
        app.text_input[0].set_value(question.answer)
    click(app, "解答する")
    assert not app.exception
    assert app.success and "正解" in app.success[0].value
    text = page_text(app)
    assert 'class="giji-trace"' in text
    assert "focus-line" in text or "focus-pass" in text
    assert app.session_state.total == 1 and app.session_state.correct == 1

    click(app, "次の問題へ")
    assert not app.exception
    assert app.session_state.answered is False
    assert app.session_state.tid != template.id


def test_wrong_answer_is_reported():
    from giji.generator import generate, load_templates
    template = load_templates(Path(APP).parent / "templates" / "basic")[0]
    question = generate(template, 5).pick_question()
    wrong = next(c for c in question.choices if c != question.answer)
    app = open_app(template.id, 5)
    app.radio[0].set_value(wrong)
    click(app, "解答する")
    assert app.error and "不正解" in app.error[0].value
    assert app.session_state.total == 1
    assert "correct" not in app.session_state
