"""画面（Streamlit）：1つのプログラムに設問を1つ出し、答えたらトレース表つきで解説する。

    streamlit run app.py

URL の ?q=テンプレートID&s=種 で同じ問題を再現できる（SNS で「今日の1問」を共有する用途）。
"""

from __future__ import annotations

import random
from pathlib import Path

import streamlit as st

from giji.errors import GijiError
from giji.generator import generate, load_templates
from giji.render import STYLE, source_html, trace_html

ROOT = Path(__file__).parent
APP_TITLE = "擬似言語トレース練習"
TAGLINE = "基本情報技術者試験・科目Bの擬似言語を、1行ずつ追う練習ができます。問題は毎回ちがう値で作られます。"
MEMBER_URL = ""          # 会員版の案内ページができたら URL を入れる（空なら表示しない）
LEVEL_NAMES = {1: "入門", 2: "基礎", 3: "中級", 4: "発展"}
CHOICE_LABELS = "アイウエオカ"


@st.cache_resource
def all_templates() -> dict:
    return {t.id: t for t in load_templates(ROOT / "templates" / "basic")}


@st.cache_data(show_spinner=False, max_entries=256)
def make_problem(template_id: str, seed: int):
    return generate(all_templates()[template_id], seed)


# ---- 状態 ----

def start_problem(template_id: str, seed: int) -> None:
    st.session_state.update(tid=template_id, seed=seed, answered=False, chosen=None)
    st.query_params.update(q=template_id, s=str(seed))


def next_problem() -> None:
    levels = st.session_state.get("levels") or list(LEVEL_NAMES)
    pool = [t for t in all_templates().values() if t.level in levels] or list(all_templates().values())
    # 直前と同じテンプレートは避ける（候補が1つしかないときを除く）
    others = [t for t in pool if t.id != st.session_state.get("tid")] or pool
    start_problem(random.choice(others).id, random.randrange(1_000_000))


def submit() -> None:
    chosen = st.session_state.get("choice_input")
    if chosen is None or str(chosen).strip() == "":
        return
    st.session_state.update(answered=True, chosen=str(chosen))
    question = current()[1]
    st.session_state.total = st.session_state.get("total", 0) + 1
    if is_correct(question, str(chosen)):
        st.session_state.correct = st.session_state.get("correct", 0) + 1


def reset_score() -> None:
    st.session_state.update(total=0, correct=0)


def current():
    problem = make_problem(st.session_state.tid, st.session_state.seed)
    return problem, problem.pick_question()


def normalize(text: str) -> str:
    table = str.maketrans("｛｝，、＋－", "{},,+-")
    return "".join(str(text).translate(table).split())


def is_correct(question, chosen: str) -> bool:
    return normalize(chosen) == normalize(question.answer)


def focus_of(problem, question) -> tuple:
    """トレース表で強調する (行, 変数, 何回目) を設問から決める。"""
    detail = question.detail
    if question.type == "var_at_line":
        return detail["line"], detail["var"], detail["pass"]
    if question.type in ("exec_count", "fill_blank"):
        return detail.get("line"), None, None
    returns = [s for s in problem.result.steps if s.kind == "return"]
    if not returns:
        return None, None, None
    top = min(s.depth for s in returns)
    last = [s for s in returns if s.depth == top][-1]
    nth = sum(1 for s in problem.result.steps if s.line == last.line and s.index <= last.index)
    return last.line, None, nth


# ---- 画面 ----

st.set_page_config(page_title=f"{APP_TITLE}｜基本情報 科目B", page_icon="🧮", layout="centered")
st.markdown(STYLE, unsafe_allow_html=True)

if "tid" not in st.session_state:
    wanted = st.query_params.get("q")
    seed_text = st.query_params.get("s", "")
    if wanted in all_templates() and seed_text.isdigit():
        start_problem(wanted, int(seed_text))
    else:
        next_problem()

with st.sidebar:
    st.header(APP_TITLE)
    st.caption(TAGLINE)
    available = sorted({t.level for t in all_templates().values()})
    st.multiselect("レベル", available, default=available, key="levels",
                   format_func=lambda n: LEVEL_NAMES.get(n, str(n)))
    total = st.session_state.get("total", 0)
    correct = st.session_state.get("correct", 0)
    st.metric("正解数", f"{correct} / {total}")
    st.button("成績をリセット", on_click=reset_score)
    if MEMBER_URL:
        st.link_button("会員版（全レベル・全テンプレート）", MEMBER_URL)
    st.divider()
    st.caption("問題はこのサイトが自動生成したオリジナル問題で、IPAの試験問題ではありません。"
               "答えと解説は、プログラムを実際に動かした結果から作っています。")

try:
    problem, question = current()
except GijiError as err:
    st.error(f"問題を作れませんでした。別の問題に切り替えてください。（{err}）")
    st.button("次の問題へ", on_click=next_problem, type="primary")
    st.stop()

answered = st.session_state.answered
line, var, nth = focus_of(problem, question)

st.subheader(problem.title)
st.caption(f"レベル：{LEVEL_NAMES.get(problem.level, problem.level)}")
if problem.description:
    st.write(problem.description)

# 解答前は設問が指す行だけを示す。空欄補充は空欄つきのプログラムを見せる。
shown_source = problem.source if answered else question.source
show_focus = [line] if line and (answered or question.type in ("var_at_line", "exec_count")) else []
st.markdown("**〔プログラム〕**")
st.markdown(source_html(shown_source, show_focus), unsafe_allow_html=True)

st.markdown(f"**設問**　{question.prompt}")

if not answered:
    with st.form("answer"):
        if question.choices:
            labels = dict(zip(question.choices, CHOICE_LABELS))
            st.radio("解答群", question.choices, index=None, key="choice_input",
                     format_func=lambda c: f"{labels[c]}　{c}")
        else:
            st.text_input("答えを入力（配列は {1, 2, 3} の形）", key="choice_input")
        st.form_submit_button("解答する", on_click=submit, type="primary")
else:
    chosen = st.session_state.chosen
    labels = dict(zip(question.choices or [], CHOICE_LABELS))

    def with_label(text: str) -> str:
        return f"{labels[text]}　{text}" if text in labels else text

    if is_correct(question, chosen):
        st.success(f"正解です。　答え：{with_label(question.answer)}")
    else:
        st.error(f"不正解です。　あなたの答え：{with_label(chosen)}　／　正解：{with_label(question.answer)}")

    st.markdown("#### 解説")
    if problem.explanation:
        st.write(problem.explanation)

    st.markdown("#### トレース表（全ステップ）")
    legend = "太字は、その文で値が変わった変数です。"
    if line:
        legend += f" 黄色は設問が指す {line} 行目"
        legend += "、濃い黄色がその回です。" if nth else "です。"
    if var:
        legend += f" 青い列が変数 {var} です。"
    st.caption(legend)
    st.markdown(trace_html(problem.result, line, var, nth), unsafe_allow_html=True)
    st.caption(f"この問題のURLを共有すると、同じ問題を開けます（?q={problem.template_id}&s={problem.seed}）。")

    st.button("次の問題へ", on_click=next_problem, type="primary")
