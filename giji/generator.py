"""問題生成：テンプレート（YAML）から、値を抽選して1問を作る。

流れは「値を抽選 → 制約を確認 → 実行 → 品質条件を確認 → 設問を作る」。
どこかで条件に合わなければ、その抽選を捨ててやり直す。
正解も誤答の選択肢も、必ず実行結果から作る。
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import (ExecError, GenerationError, GijiError, LexError,
                     ParseError, TemplateError)
from .interpreter import (INT_DIV_MODES, UNSET, Interpreter, Options,
                          RunResult, format_value)
from .notation import Notation, load_notation
from .parser import parse_expression, parse_program

QUESTION_TYPES = ("return_value", "var_at_line", "exec_count", "fill_blank")
PARAM_TYPES = ("int", "choice", "int_array", "element", "int_matrix", "char_array")
BLANK_MARK = "［　ａ　］"

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MARKER = re.compile(r"\s*//\s*@([A-Za-z_][A-Za-z0-9_]*)\s*$")
_RESERVED_NAMES = {"result", "steps", "output_count"}
_TEMPLATE_KEYS = {
    "id", "title", "level", "access", "tags", "array_base", "int_div",
    "max_steps", "description", "params", "constraints", "source", "call",
    "quality", "questions", "explanation",
}
# 繰返しの変数の初期化・更新は「その行の実行回数」に数えない
_NOT_COUNTED = ("for_init", "for_step")


# ---- データ ----

@dataclass
class Template:
    id: str
    title: str
    source: str                 # 目印の注釈を取り除いた後のプログラム
    questions: list
    level: int = 1
    access: str = "free"
    tags: list = field(default_factory=list)
    array_base: int = 1
    int_div: str = "strict"
    max_steps: int = 300
    description: str = ""
    params: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)
    call: str | None = None
    quality: list = field(default_factory=list)
    explanation: str = ""
    markers: dict = field(default_factory=dict)   # 目印の名前 -> 行番号
    path: str = ""


@dataclass
class Question:
    type: str
    prompt: str
    answer: str
    choices: list | None        # None のときは記述式（値を入力させる）
    source: str                 # この設問で見せるプログラム（空欄補充では空欄つき）
    detail: dict = field(default_factory=dict)
    weight: float = 1.0         # 出題されやすさ（テンプレートの weight）


@dataclass
class Problem:
    template_id: str
    title: str
    level: int
    seed: int
    description: str
    source: str
    call: str | None
    params: dict
    array_base: int
    questions: list
    result: RunResult
    explanation: str
    attempts: int               # 何回目の抽選で採用されたか
    rejects: Counter            # 捨てた抽選の理由と回数

    def pick_question(self) -> Question:
        """重みに従って設問を1つ選ぶ。同じ問題（同じ種）なら必ず同じ設問になる。"""
        rng = random.Random(f"{self.template_id}:{self.seed}:pick")
        return rng.choices(self.questions, weights=[q.weight for q in self.questions])[0]


class _Reject(Exception):
    """この抽選は条件に合わないのでやり直す、という合図。"""

    def __init__(self, reason: str):
        self.reason = reason


# ---- テンプレートの読み込み ----

def _extract_markers(source: str) -> tuple[str, dict]:
    """行末の「// @名前」を目印として取り出し、プログラムからは消す。

    設問で行を指すのに行番号を直接書くと、テンプレートを1行直すたびに
    ずれてしまう。目印なら行を足しても指す先が変わらない。
    """
    markers: dict[str, int] = {}
    lines = []
    for number, line in enumerate(source.rstrip("\n").split("\n"), start=1):
        found = _MARKER.search(line)
        if found:
            name = found.group(1)
            if name in markers:
                raise TemplateError(f"目印 @{name} が二重に使われています", number)
            markers[name] = number
            line = line[:found.start()]
        lines.append(line.rstrip())
    return "\n".join(lines), markers


def template_from_dict(data: dict, path: str = "") -> Template:
    where = f"（{path}）" if path else ""
    if not isinstance(data, dict):
        raise TemplateError(f"テンプレートの形式が正しくありません{where}")
    unknown = set(data) - _TEMPLATE_KEYS
    if unknown:
        raise TemplateError(f"知らない項目があります: {sorted(unknown)}{where}")
    for key in ("id", "title", "source", "questions"):
        if not data.get(key):
            raise TemplateError(f"必須の項目 {key} がありません{where}")

    source, markers = _extract_markers(str(data["source"]))
    params = data.get("params") or {}
    for name, spec in params.items():
        if not isinstance(spec, dict) or spec.get("type") not in PARAM_TYPES:
            raise TemplateError(f"params.{name} の type は {PARAM_TYPES} のどれかにしてください{where}")
    clash = (set(markers) & set(params)) | ((set(markers) | set(params)) & _RESERVED_NAMES)
    if clash:
        raise TemplateError(f"名前が重複しています: {sorted(clash)}{where}")

    questions = data["questions"]
    if not isinstance(questions, list):
        raise TemplateError(f"questions は並びで書いてください{where}")
    for q in questions:
        if not isinstance(q, dict) or q.get("type") not in QUESTION_TYPES:
            raise TemplateError(f"設問の type は {QUESTION_TYPES} のどれかにしてください{where}")
        if q["type"] in ("var_at_line", "exec_count"):
            line = q.get("line")
            if isinstance(line, str) and line not in markers:
                raise TemplateError(f"設問が指す目印 @{line} がプログラムにありません{where}")
            if not isinstance(line, (int, str)):
                raise TemplateError(f"設問に line がありません{where}")
        if q["type"] == "var_at_line" and not q.get("var"):
            raise TemplateError(f"var_at_line の設問に var がありません{where}")
        domain = q.get("domain")
        if domain is not None:
            target = (domain or {}).get("index_of") if isinstance(domain, dict) else None
            if q["type"] not in ("return_value", "var_at_line"):
                raise TemplateError(f"domain は return_value か var_at_line の設問にだけ書けます{where}")
            if (params.get(target) or {}).get("type") != "int_array":
                raise TemplateError(f"domain.index_of は配列（int_array）の名前にしてください{where}")
            extra = domain.get("extra", [])
            if not isinstance(extra, list) or not all(isinstance(v, int) for v in extra):
                raise TemplateError(f"domain.extra は整数の並びにしてください{where}")
        weight = q.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
            raise TemplateError(f"設問の weight は0以上の数にしてください{where}")
        if q["type"] == "fill_blank":
            if not q.get("blank") or len(q.get("distractors") or []) < 3:
                raise TemplateError(f"fill_blank には blank と3つ以上の distractors が必要です{where}")
            if q.get("blank_b") and len(q.get("distractors_b") or []) < 2:
                raise TemplateError(f"blank_b を書くときは distractors_b が2つ以上必要です{where}")

    if not any(q.get("weight", 1) > 0 for q in questions):
        raise TemplateError(f"weight が正の設問が1つもありません{where}")

    int_div = data.get("int_div", "strict")
    if int_div not in INT_DIV_MODES:
        raise TemplateError(f"int_div は {INT_DIV_MODES} のどれかにしてください{where}")
    array_base = data.get("array_base", 1)
    if array_base not in (0, 1):
        raise TemplateError(f"array_base は 0 か 1 にしてください{where}")

    return Template(
        id=str(data["id"]), title=str(data["title"]), source=source,
        questions=questions, level=int(data.get("level", 1)),
        access=str(data.get("access", "free")), tags=list(data.get("tags") or []),
        array_base=array_base, int_div=int_div,
        max_steps=int(data.get("max_steps", 300)),
        description=str(data.get("description") or "").strip(),
        params=params, constraints=list(data.get("constraints") or []),
        call=data.get("call"), quality=list(data.get("quality") or []),
        explanation=str(data.get("explanation") or "").strip(),
        markers=markers, path=path,
    )


def load_template(path: str | Path) -> Template:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return template_from_dict(data, str(path))


def load_templates(directory: str | Path) -> list[Template]:
    templates = [load_template(p) for p in sorted(Path(directory).rglob("*.yaml"))]
    seen: dict[str, str] = {}
    for t in templates:
        if t.id in seen:
            raise TemplateError(f"id「{t.id}」が {seen[t.id]} と {t.path} で重複しています")
        seen[t.id] = t.path
    return templates


# ---- 値の抽選と埋め込み ----

def _range(spec: dict, key: str, name: str) -> tuple[int, int]:
    value = spec.get(key)
    if isinstance(value, int):
        return value, value
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, int) for v in value) and value[0] <= value[1]):
        return value[0], value[1]
    raise TemplateError(f"params.{name}.{key} は [最小, 最大] の形で書いてください")


def _sample_params(specs: dict, rng: random.Random) -> dict:
    values: dict = {}
    for name, spec in specs.items():
        kind = spec["type"]
        if kind == "int":
            low, high = _range(spec, "range", name)
            values[name] = rng.randint(low, high)
        elif kind == "choice":
            options = spec.get("values")
            if not isinstance(options, list) or not options:
                raise TemplateError(f"params.{name}.values がありません")
            values[name] = rng.choice(options)
        elif kind == "int_array":
            low, high = _range(spec, "range", name)
            length = rng.randint(*_range(spec, "length", name))
            if spec.get("unique"):
                if high - low + 1 < length:
                    raise TemplateError(f"params.{name}: 値の範囲が狭く、重複なしで作れません")
                items = rng.sample(range(low, high + 1), length)
            else:
                items = [rng.randint(low, high) for _ in range(length)]
            order = spec.get("sorted")
            if order:
                items.sort(reverse=(order == "desc"))
            values[name] = items
        elif kind == "int_matrix":
            low, high = _range(spec, "range", name)
            rows = rng.randint(*_range(spec, "rows", name))
            cols = rng.randint(*_range(spec, "cols", name))
            values[name] = [[rng.randint(low, high) for _ in range(cols)] for _ in range(rows)]
        elif kind == "char_array":
            alphabet = str(spec.get("alphabet") or "")
            if not alphabet:
                raise TemplateError(f"params.{name}.alphabet がありません")
            length = rng.randint(*_range(spec, "length", name))
            values[name] = [rng.choice(alphabet) for _ in range(length)]
        elif kind == "element":
            source = values.get(spec.get("of"))
            if not isinstance(source, list) or not source:
                raise TemplateError(f"params.{name}.of は、先に書いた配列の名前にしてください")
            values[name] = rng.choice(source)
    return values


def _substitute(text: str, values: dict) -> str:
    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise TemplateError(f"${{{name}}} に対応する値がありません")
        return format_value(values[name])
    return _PLACEHOLDER.sub(replace, text)


# ---- 条件式の評価 ----

def _exec_count(result: RunResult, line: int) -> int:
    return sum(1 for s in result.steps if s.line == line and s.kind not in _NOT_COUNTED)


def _check_conditions(label: str, expressions: list, values: dict, variables: dict,
                      builtins: dict, options: Options, notation: Notation) -> None:
    """条件式を順に評価する。偽なら抽選のやり直し、式そのものの誤りはテンプレートの誤り。"""
    for text in expressions:
        filled = _substitute(str(text), values)
        try:
            expr = parse_expression(filled, notation)
            ok = Interpreter(_EMPTY_PROGRAM, options, builtins).evaluate(expr, variables)
        except GijiError as err:
            raise TemplateError(f"{label}「{text}」を評価できません: {err.message}") from None
        if not isinstance(ok, bool):
            raise TemplateError(f"{label}「{text}」の結果が true / false ではありません")
        if not ok:
            raise _Reject(f"{label}: {text}")


_EMPTY_PROGRAM = parse_program("")


# ---- 選択肢 ----
#
# 誤答は設問の種類ごとに「学習者が実際に間違えそうな値」から作る。
#   実行回数 … 正解の±1、ほかの行の実行回数、配列の要素数
#   変数の値 … 同じ変数の前後の回の値、代入前の値、同じ時点のほかの変数の値
#   戻り値   … 返した変数が途中で取った値、戻る時点のほかの変数の値
# 配列の中身のような、その設問の答えになり得ない値は候補に入れない。

def _same_kind(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, int) and isinstance(b, int):
        return True
    if isinstance(a, str) and isinstance(b, str):
        return True
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and UNSET not in b
    return False


def _list_variants(value: list) -> list:
    """配列の答えに対する誤答：隣どうしの入替え、逆順、1つずらし。"""
    variants = []
    for i in range(len(value) - 1):
        swapped = list(value)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        variants.append(swapped)
    variants.append(list(reversed(value)))
    variants.append(value[1:] + value[:1])
    return variants


def _build_choices(answer, tiers: list, rng: random.Random, *, valid=None,
                   size: int = 4) -> list | None:
    """tiers は [(候補の並び, そこから採る最大数), …]。前の組ほど優先して採る。

    足りないとき、整数なら正解の近くの値で埋める。それでも足りなければ None（記述式）。
    """
    if isinstance(answer, bool):
        return ["true", "false"]
    if isinstance(answer, float) or answer is None:
        return None
    seen = {format_value(answer)}
    picked: list = []

    def usable(candidate) -> bool:
        return (_same_kind(answer, candidate)
                and format_value(candidate) not in seen
                and (valid is None or valid(candidate)))

    for candidates, limit in tiers:
        pool: list = []
        for candidate in candidates:
            if usable(candidate) and all(format_value(candidate) != format_value(p) for p in pool):
                pool.append(candidate)
        rng.shuffle(pool)
        for candidate in pool[:limit]:
            if len(picked) < size - 1:
                picked.append(candidate)
                seen.add(format_value(candidate))

    if isinstance(answer, int):
        offset = 1
        while len(picked) < size - 1 and offset <= 50:
            for candidate in (answer + offset, answer - offset):
                if len(picked) < size - 1 and usable(candidate):
                    picked.append(candidate)
                    seen.add(format_value(candidate))
            offset += 1
    if len(picked) < size - 1:
        return None

    if isinstance(answer, int):
        return [format_value(v) for v in sorted(picked + [answer])]
    choices = [format_value(v) for v in picked] + [format_value(answer)]
    rng.shuffle(choices)
    return choices


def _sign_rule(answer):
    """あり得ない誤答を除く規則。

    正解が0以上の整数なら、負の値は誤答にしない。
    正解が「同じ値のない配列」なら、同じ値が2つある配列は誤答にしない
    （交換の途中の状態を選択肢に出さないため）。
    """
    if isinstance(answer, int) and not isinstance(answer, bool) and answer >= 0:
        return lambda c: c >= 0
    if isinstance(answer, list):
        texts = [format_value(v) for v in answer]
        if len(set(texts)) == len(texts):
            return lambda c: len({format_value(v) for v in c}) == len(c)
    return None


def _domain_rule(spec: dict, ctx: dict):
    """答えが要素番号の設問では、誤答も要素番号として成り立つ値だけにする。

    domain: {index_of: data, extra: [0]} と書くと、誤答は
    「array_base 〜 array_base＋要素数−1」と extra の値に限られる。
    """
    domain = spec.get("domain")
    if not domain:
        return None
    base = ctx["template"].array_base
    length = len(ctx["values"][domain["index_of"]])
    extra = set(domain.get("extra", []))
    return lambda c: base <= c <= base + length - 1 or c in extra


def _choices_exec_count(count: int, line: int, result: RunResult, values: dict,
                        rng: random.Random, size: int = 4) -> list | None:
    per_line = Counter(s.line for s in result.steps if s.kind not in _NOT_COUNTED)
    other_lines = [n for ln, n in per_line.items() if ln != line]
    lengths = [len(v) for v in values.values() if isinstance(v, list)]
    upper = max(list(per_line.values()) + lengths + [count]) + 1
    return _build_choices(
        count,
        [([count - 1, count + 1], 2), (other_lines + lengths, 2)],
        rng, valid=lambda c: 0 <= c <= upper, size=size)


def _choices_var_at_line(value, line: int, var: str, nth: int, result: RunResult,
                         rng: random.Random, valid=None, size: int = 4) -> list | None:
    hits = [i for i, s in enumerate(result.steps) if s.line == line and var in s.vars]
    at = hits[nth - 1]
    step = result.steps[at]
    passes = [result.steps[i].vars[var] for i in hits]
    neighbours = [passes[i] for i in (nth - 2, nth) if 0 <= i < len(passes)]
    if at > 0:
        before = result.steps[at - 1]
        if before.depth == step.depth and before.proc == step.proc and var in before.vars:
            neighbours.append(before.vars[var])       # この文を実行する前の値
    other_passes = [v for v in passes if v not in neighbours]
    other_vars = [v for name, v in step.vars.items() if name != var]
    tiers = [(neighbours, 2), (other_passes, 1), (other_vars, 2)]
    if isinstance(value, list):
        history = [s.vars[var] for s in result.steps if var in s.vars]
        tiers = [(neighbours, 2), (history, 3), (_list_variants(value), size)]
    return _build_choices(value, tiers, rng, valid=valid or _sign_rule(value), size=size)


def _choices_return_value(value, result: RunResult, rng: random.Random,
                          valid=None, size: int = 4) -> list | None:
    returns = [s for s in result.steps if s.kind == "return"]
    history: list = []
    others: list = []
    if returns:
        top = min(s.depth for s in returns)
        last = [s for s in returns if s.depth == top][-1]
        for name, final in last.vars.items():
            if format_value(final) == format_value(value):
                # 返した変数が途中で取った値（途中で止めてしまう誤り）
                history += [s.vars[name] for s in result.steps
                            if s.depth == last.depth and s.proc == last.proc and name in s.vars]
            else:
                others.append(final)
    tiers = [(history, 2), (others, 2)]
    if isinstance(value, list):
        tiers = [(history, 3), (_list_variants(value), size)]
    if isinstance(value, str):
        strings = [v for s in result.steps for v in s.vars.values() if isinstance(v, str)]
        tiers = [(history, 2), (strings, 3)]
    return _build_choices(value, tiers, rng, valid=valid or _sign_rule(value), size=size)


# ---- 設問 ----

def _resolve_line(spec: dict, template: Template) -> int:
    line = spec["line"]
    return template.markers[line] if isinstance(line, str) else line


def _question_return_value(spec, ctx) -> Question:
    result = ctx["result"]
    if result.return_value is not None:
        value = result.return_value
        target = f"{ctx['call']} を呼び出したとき" if ctx["call"] else "プログラムを実行したとき"
        prompt = f"{target}の戻り値はどれか。"
    elif result.outputs:
        value = result.outputs if len(result.outputs) > 1 else result.outputs[0]
        prompt = "プログラムを実行したとき、出力される値はどれか（複数あるときは出力順）。"
    else:
        raise TemplateError("return_value の設問ですが、戻り値も出力もありません")
    return Question("return_value", prompt, format_value(value),
                    _choices_return_value(value, result, ctx["rng"], _domain_rule(spec, ctx)),
                    ctx["source"])


def _question_var_at_line(spec, ctx) -> Question:
    result, rng = ctx["result"], ctx["rng"]
    line = _resolve_line(spec, ctx["template"])
    var = spec["var"]
    values = result.values_at(line, var)
    if not values:
        raise _Reject(f"{line}行目が実行されない")
    which = spec.get("pass", "random")
    if which == "last":
        nth = len(values)
    elif which == "random":
        nth = rng.randint(1, len(values))
    elif isinstance(which, int) and which >= 1:
        nth = which
        if nth > len(values):
            raise _Reject(f"{line}行目の実行が{nth}回に満たない")
    else:
        raise TemplateError("var_at_line の pass は 正の整数 / last / random のどれかにしてください")
    value = values[nth - 1]
    if value is UNSET:
        raise _Reject(f"{line}行目の時点で {var} が未設定")
    when = "実行した直後" if len(values) == 1 else f"{nth}回目に実行した直後"
    prompt = f"{line}行目を{when}の、変数 {var} の値はどれか。"
    return Question("var_at_line", prompt, format_value(value),
                    _choices_var_at_line(value, line, var, nth, result, rng,
                                         _domain_rule(spec, ctx)), ctx["source"],
                    {"line": line, "var": var, "pass": nth, "passes": len(values)})


def _question_exec_count(spec, ctx) -> Question:
    result = ctx["result"]
    line = _resolve_line(spec, ctx["template"])
    count = _exec_count(result, line)
    kinds = {s.kind for s in result.steps if s.line == line and s.kind not in _NOT_COUNTED}
    if kinds == {"cond"}:
        prompt = f"{line}行目の条件式が評価される回数はどれか。"
    else:
        prompt = f"{line}行目が実行される回数はどれか。"
    return Question("exec_count", prompt, format_value(count),
                    _choices_exec_count(count, line, result, ctx["values"], ctx["rng"]),
                    ctx["source"], {"line": line})


def _outcome(source: str, ctx) -> tuple:
    """プログラムを実行した結果を、比べられる形にする。誤りで止まったらその種類を返す。"""
    try:
        program = parse_program(source, ctx["notation"])
        result = Interpreter(program, ctx["options"]).run(ctx["call_expr"])
    except GijiError as err:
        return ("error", type(err).__name__, err.message)
    return ("ok", format_value(result.return_value), [format_value(v) for v in result.outputs])


def _outcome_text(outcome: tuple) -> str:
    """選択肢を入れて動かした結果を、解説に載せる文にする。"""
    if outcome[0] == "error":
        if outcome[1] == "StepLimitError":
            return "繰返しが終わらない"
        if outcome[1] in ("LexError", "ParseError"):
            return "プログラムとして成り立たない"
        return f"途中で止まる（{outcome[2]}）"
    if outcome[1] != "なし":
        return f"戻り値は {outcome[1]}"
    return "出力は " + "、".join(outcome[2]) if outcome[2] else "何も返さない"


def _question_fill_blank(spec, ctx) -> Question:
    values, source, rng = ctx["values"], ctx["source"], ctx["rng"]
    blank = _substitute(str(spec["blank"]), values)
    if source.count(blank) != 1:
        raise TemplateError(
            f"fill_blank の blank「{blank}」は、プログラム中にちょうど1回だけ現れる必要があります")
    correct = _outcome(source, ctx)
    distractors = []
    outcomes = {blank: _outcome_text(correct)}
    for text in spec["distractors"]:
        candidate = _substitute(str(text), values)
        if candidate == blank or candidate in distractors:
            raise TemplateError(f"fill_blank の選択肢「{candidate}」が重複しています")
        # 誤答も実際に動かし、正答と同じ結果になるなら「答えが2つある問題」なので捨てる
        got = _outcome(source.replace(blank, candidate), ctx)
        if got == correct:
            raise _Reject(f"空欄補充: 「{candidate}」でも同じ結果になる")
        outcomes[candidate] = _outcome_text(got)
        distractors.append(candidate)
    choices = rng.sample(distractors, 3) + [blank]
    rng.shuffle(choices)

    result = ctx["result"]
    if result.return_value is not None:
        target = f"{ctx['call']} を呼び出すと" if ctx["call"] else "プログラムを実行すると"
        fact = f"{target}戻り値は {format_value(result.return_value)} になる。"
    else:
        shown = "、".join(format_value(v) for v in result.outputs)
        fact = f"プログラムを実行すると {shown} の順に出力される。"
    prompt = f"{fact}プログラム中の {BLANK_MARK} に入れる正しい答えはどれか。"
    blank_line = next(n for n, text in enumerate(source.split("\n"), start=1) if blank in text)
    return Question("fill_blank", prompt, blank, choices,
                    source.replace(blank, BLANK_MARK),
                    {"line": blank_line, "outcomes": {c: outcomes[c] for c in choices}})


_BUILDERS = {
    "return_value": _question_return_value,
    "var_at_line": _question_var_at_line,
    "exec_count": _question_exec_count,
    "fill_blank": _question_fill_blank,
}


# ---- 生成 ----

def _attempt(template: Template, rng: random.Random, notation: Notation) -> dict:
    values = _sample_params(template.params, rng)
    options = Options(array_base=template.array_base, int_div=template.int_div,
                      negative_divmod="error", max_steps=template.max_steps)

    _check_conditions("制約", template.constraints, values, {}, {}, options, notation)

    source = _substitute(template.source, values)
    call = _substitute(template.call, values) if template.call else None
    try:
        program = parse_program(source, notation)
        call_expr = parse_expression(call, notation) if call else None
    except (LexError, ParseError) as err:
        raise TemplateError(f"テンプレート {template.id} のプログラムを読めません: {err}") from None
    try:
        result = Interpreter(program, options).run(call_expr)
    except ExecError as err:
        raise _Reject(f"実行時の誤り: {err.message}") from None

    variables = dict(template.markers)
    variables["steps"] = len(result.steps)
    variables["output_count"] = len(result.outputs)
    if result.return_value is not None:
        variables["result"] = result.return_value
    builtins = {
        "count": lambda line: _exec_count(result, line),
        "true_count": lambda line: sum(1 for s in result.steps
                                       if s.line == line and s.kind == "cond" and s.detail is True),
        "false_count": lambda line: sum(1 for s in result.steps
                                        if s.line == line and s.kind == "cond" and s.detail is False),
    }
    _check_conditions("品質", template.quality, values, variables, builtins, options, notation)

    ctx = {"template": template, "values": values, "source": source, "call": call,
           "call_expr": call_expr, "result": result, "rng": rng,
           "options": options, "notation": notation}
    questions = []
    for spec in template.questions:
        question = _BUILDERS[spec["type"]](spec, ctx)
        question.weight = float(spec.get("weight", 1))
        questions.append(question)

    explain_values = dict(values)
    if result.return_value is not None:
        explain_values["result"] = result.return_value
    return {
        "source": source, "call": call, "params": values, "questions": questions,
        "result": result, "explanation": _substitute(template.explanation, explain_values),
        "description": _substitute(template.description, values),
    }


def generate(template: Template, seed: int, *, max_attempts: int = 200,
             notation: Notation | None = None) -> Problem:
    """テンプレートと種（seed）から1問を作る。同じ種なら必ず同じ問題になる。"""
    notation = notation or load_notation()
    rng = random.Random(f"{template.id}:{seed}")
    rejects: Counter = Counter()
    for attempt in range(1, max_attempts + 1):
        try:
            made = _attempt(template, rng, notation)
        except _Reject as reject:
            rejects[reject.reason] += 1
            continue
        return Problem(
            template_id=template.id, title=template.title, level=template.level,
            seed=seed, array_base=template.array_base, attempts=attempt,
            rejects=rejects, **made,
        )
    reasons = "、".join(f"{reason}（{n}回）" for reason, n in rejects.most_common(3))
    raise GenerationError(
        f"テンプレート {template.id} は {max_attempts} 回抽選しても問題を作れませんでした。"
        f"主な理由: {reasons}")
