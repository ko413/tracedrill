"""実行器：構文木をたどって実行し、1文ごとの記録（トレース）を残す。

設問・解説・トレース表はすべてこの記録から作るので、「答え」は必ず
実際に動かした結果になる。Python の eval は使っていない。
"""

from __future__ import annotations

import copy
import sys
from collections import Counter
from dataclasses import dataclass, field

from . import ast_nodes as A
from .errors import ExecError, StepLimitError

INT_DIV_MODES = ("strict", "quotient", "real")


class _Unset:
    """宣言されたが、まだ値が入っていない変数の印。"""

    def __repr__(self) -> str:
        return "未設定"

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self


UNSET = _Unset()


@dataclass
class Options:
    #: 配列の最初の要素番号。本試験では問題文ごとに「1から始まる」等と断られる。
    array_base: int = 1
    #: 整数同士の ÷ の扱い。
    #:   strict   … 割り切れるときだけ許す。割り切れなければ誤りにする（既定）
    #:   quotient … 商の整数部分を返す（0方向へ切り捨て）
    #:   real     … 実数の除算にする
    #: 「÷ … の商」と書かれた除算は、どのモードでも商の整数部分を返す。
    int_div: str = "strict"
    #: 負の数を含む ÷ と mod の扱い。IPA の資料に定めがないため、問題生成では
    #: "error" にして、そういう計算を含む問題を作らせない。
    #:   allow … 商は0方向へ切り捨て、余りの符号は割られる数に合わせる（既定）
    #:   error … 誤りにする
    negative_divmod: str = "allow"
    max_steps: int = 10_000
    max_depth: int = 100

    def __post_init__(self):
        if self.int_div not in INT_DIV_MODES:
            raise ValueError(f"int_div は {INT_DIV_MODES} のどれかにしてください")
        if self.negative_divmod not in ("allow", "error"):
            raise ValueError("negative_divmod は allow か error にしてください")
        if self.array_base not in (0, 1):
            raise ValueError("array_base は 0 か 1 にしてください")


@dataclass
class Step:
    index: int          # 通し番号（1始まり）
    line: int
    kind: str           # decl assign cond for_init for_step call return output append
    depth: int          # 呼出しの深さ（最初の手続が1）
    proc: str
    vars: dict          # その文を実行した直後の、現在の手続の変数
    detail: object = None   # cond なら真偽、return/output なら値


@dataclass
class RunResult:
    return_value: object = None
    outputs: list = field(default_factory=list)
    steps: list = field(default_factory=list)

    def count(self, line: int, kind: str | None = None) -> int:
        """指定行が実行された回数。kind を渡すとその種類だけ数える。"""
        return sum(1 for s in self.steps
                   if s.line == line and (kind is None or s.kind == kind))

    def line_counts(self) -> Counter:
        return Counter(s.line for s in self.steps)

    def values_at(self, line: int, var: str) -> list:
        """指定行を通るたびの、実行直後の変数の値を順に返す。"""
        return [s.vars[var] for s in self.steps if s.line == line and var in s.vars]


class _ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _trunc_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def format_value(v) -> str:
    """値を擬似言語の書き方で文字列にする。"""
    if v is UNSET:
        return "未設定"
    if v is None:
        return "なし"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "{" + ", ".join(format_value(x) for x in v) + "}"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


class Interpreter:
    def __init__(self, program: A.Program, options: Options | None = None,
                 builtins: dict | None = None):
        self.program = program
        self.options = options or Options()
        #: 名前 -> Python の関数。テンプレートの条件式で count(行) などを使うためのもの。
        self.builtins = builtins or {}
        self.result = RunResult()
        self.frames: list[tuple[str, dict]] = []

    # ---- 入口 ----

    def run(self, call=None) -> RunResult:
        """手続の外の文を実行し、call（式）があればそれを評価して戻り値にする。"""
        self.result = RunResult()
        self.frames = [("(main)", {})]
        # 擬似言語の呼出し1回が Python の呼出し十数回になるので、上限を一時的に広げる。
        # それでも足りない場合は StepLimitError に言い換える。
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, self.options.max_depth * 40 + 1000))
        try:
            try:
                self._exec_block(self.program.main)
            except _ReturnSignal as sig:
                self.result.return_value = sig.value
                return self.result
            if call is not None:
                self.result.return_value = self._eval(call)
            return self.result
        except RecursionError:
            raise StepLimitError("呼出しまたは式の入れ子が深すぎます") from None
        finally:
            sys.setrecursionlimit(old_limit)

    def evaluate(self, expr, variables: dict | None = None):
        """式を1つだけ評価する（テンプレートの制約式・品質条件で使う）。"""
        self.result = RunResult()
        self.frames = [("(expr)", dict(variables or {}))]
        return self._eval(expr)

    # ---- 記録 ----

    @property
    def _vars(self) -> dict:
        return self.frames[-1][1]

    def _record(self, line: int, kind: str, detail=None) -> None:
        if len(self.result.steps) >= self.options.max_steps:
            raise StepLimitError(
                f"実行ステップ数が上限（{self.options.max_steps}）を超えました", line)
        self.result.steps.append(Step(
            index=len(self.result.steps) + 1,
            line=line,
            kind=kind,
            depth=len(self.frames) - 1,
            proc=self.frames[-1][0],
            vars=copy.deepcopy(self._vars),
            detail=copy.deepcopy(detail),
        ))

    # ---- 文 ----

    def _exec_block(self, stmts: list) -> None:
        for stmt in stmts:
            self._exec(stmt)

    def _exec(self, stmt) -> None:
        method = getattr(self, "_exec_" + type(stmt).__name__)
        method(stmt)

    def _exec_Decl(self, stmt: A.Decl) -> None:
        for name, init in stmt.items:
            if name in self._vars:
                raise ExecError(f"変数「{name}」が二重に宣言されています", stmt.line)
            self._vars[name] = UNSET if init is None else self._eval(init)
        self._record(stmt.line, "decl")

    def _exec_Assign(self, stmt: A.Assign) -> None:
        value = self._eval(stmt.value)
        self._store(stmt.target, value)
        self._record(stmt.line, "assign")

    def _store(self, target, value) -> None:
        if isinstance(target, A.Var):
            if target.name not in self._vars:
                raise ExecError(f"宣言されていない変数「{target.name}」に代入しています", target.line)
            self._vars[target.name] = value
            return
        container, offset = self._locate(target)
        container[offset] = value

    def _exec_If(self, stmt: A.If) -> None:
        for cond, body, line in stmt.branches:
            ok = self._truth(cond)
            self._record(line, "cond", ok)
            if ok:
                self._exec_block(body)
                return
        if stmt.else_body is not None:
            self._exec_block(stmt.else_body)

    def _exec_While(self, stmt: A.While) -> None:
        while True:
            ok = self._truth(stmt.cond)
            self._record(stmt.line, "cond", ok)
            if not ok:
                return
            self._exec_block(stmt.body)

    def _exec_DoWhile(self, stmt: A.DoWhile) -> None:
        while True:
            self._exec_block(stmt.body)
            ok = self._truth(stmt.cond)
            self._record(stmt.cond_line, "cond", ok)
            if not ok:
                return

    def _exec_For(self, stmt: A.For) -> None:
        # 終了値と増分は繰返しに入る前に1回だけ求める。
        if stmt.var not in self._vars:
            raise ExecError(f"繰返しの変数「{stmt.var}」が宣言されていません", stmt.line)
        start = self._number(stmt.start)
        end = self._number(stmt.end)
        step = self._number(stmt.step)
        if step <= 0:
            raise ExecError("for の増分・減分は正の数でなければなりません", stmt.line)
        self._vars[stmt.var] = start
        self._record(stmt.line, "for_init")
        while True:
            current = self._vars[stmt.var]
            if not _is_number(current):
                raise ExecError(f"繰返しの変数「{stmt.var}」が数値ではありません", stmt.line)
            ok = current <= end if stmt.direction == "inc" else current >= end
            self._record(stmt.line, "cond", ok)
            if not ok:
                return
            self._exec_block(stmt.body)
            current = self._vars[stmt.var]
            self._vars[stmt.var] = current + step if stmt.direction == "inc" else current - step
            self._record(stmt.line, "for_step")

    def _exec_Return(self, stmt: A.Return) -> None:
        value = None if stmt.value is None else self._eval(stmt.value)
        self._record(stmt.line, "return", value)
        raise _ReturnSignal(value)

    def _exec_Output(self, stmt: A.Output) -> None:
        value = self._eval(stmt.value)
        self.result.outputs.append(copy.deepcopy(value))
        self._record(stmt.line, "output", value)

    def _exec_Append(self, stmt: A.Append) -> None:
        target = self._eval(stmt.target)
        if not isinstance(target, list):
            raise ExecError("「の末尾に…を追加する」の対象が配列ではありません", stmt.line)
        target.append(self._eval(stmt.value))
        self._record(stmt.line, "append")

    def _exec_ExprStmt(self, stmt: A.ExprStmt) -> None:
        self._eval(stmt.call)
        self._record(stmt.line, "call")

    # ---- 式 ----

    def _eval(self, node):
        method = getattr(self, "_eval_" + type(node).__name__)
        return method(node)

    def _truth(self, node) -> bool:
        value = self._eval(node)
        if not isinstance(value, bool):
            raise ExecError("条件式の結果が true / false ではありません", node.line)
        return value

    def _number(self, node):
        value = self._eval(node)
        if not _is_number(value):
            raise ExecError("数値が必要です", node.line)
        return value

    def _eval_Num(self, node: A.Num):
        return node.value

    def _eval_Str(self, node: A.Str):
        return node.value

    def _eval_Bool(self, node: A.Bool):
        return node.value

    def _eval_Var(self, node: A.Var):
        if node.name not in self._vars:
            raise ExecError(f"宣言されていない変数「{node.name}」を参照しています", node.line)
        value = self._vars[node.name]
        if value is UNSET:
            raise ExecError(f"値が設定されていない変数「{node.name}」を参照しています", node.line)
        return value

    def _locate(self, node: A.Index) -> tuple[list, int]:
        """a[i, j] の最後の添字が指す (入れ物, 位置) を返す。"""
        container = self._eval(node.target)
        base = self.options.array_base
        last = len(node.indices) - 1
        for n, index_node in enumerate(node.indices):
            if not isinstance(container, list):
                raise ExecError("配列ではないものに要素番号を付けています", node.line)
            index = self._eval(index_node)
            if not _is_int(index):
                raise ExecError("要素番号が整数ではありません", node.line)
            offset = index - base
            if not 0 <= offset < len(container):
                raise ExecError(
                    f"配列の範囲外です（要素番号 {index}、要素数 {len(container)}）", node.line)
            if n == last:
                return container, offset
            container = container[offset]
        raise ExecError("要素番号がありません", node.line)

    def _eval_Index(self, node: A.Index):
        container, offset = self._locate(node)
        value = container[offset]
        if value is UNSET:
            raise ExecError("値が設定されていない要素を参照しています", node.line)
        return value

    def _eval_Length(self, node: A.Length):
        target = self._eval(node.target)
        if not isinstance(target, list):
            raise ExecError("「の要素数」の対象が配列ではありません", node.line)
        if node.axis == 1:
            if not target or not isinstance(target[0], list):
                raise ExecError("「の列数」の対象が二次元配列ではありません", node.line)
            return len(target[0])
        return len(target)

    def _eval_ArrayLit(self, node: A.ArrayLit):
        return [self._eval(item) for item in node.items]

    def _eval_ArrayFill(self, node: A.ArrayFill):
        count = self._eval(node.count)
        if not _is_int(count) or count < 0:
            raise ExecError("「個の」の前は0以上の整数でなければなりません", node.line)
        value = self._eval(node.value)
        return [copy.deepcopy(value) for _ in range(count)]

    def _eval_Unary(self, node: A.Unary):
        if node.op == "not":
            return not self._truth(node.operand)
        value = self._number(node.operand)
        return -value if node.op == "minus" else value

    def _eval_Binary(self, node: A.Binary):
        op = node.op
        # and / or は左から評価し、結果が決まった時点で右を評価しない（短絡評価）。
        if op == "and":
            return self._truth(node.left) and self._truth(node.right)
        if op == "or":
            return self._truth(node.left) or self._truth(node.right)

        left = self._eval(node.left)
        right = self._eval(node.right)

        if op in ("eq", "ne"):
            if isinstance(left, list) or isinstance(right, list):
                raise ExecError("配列どうしは = で比較できません", node.line)
            same = left == right and isinstance(left, bool) == isinstance(right, bool)
            return same if op == "eq" else not same

        if op == "plus" and isinstance(left, str) and isinstance(right, str):
            return left + right

        if op in ("lt", "le", "gt", "ge") and isinstance(left, str) and isinstance(right, str):
            pass
        elif not (_is_number(left) and _is_number(right)):
            raise ExecError("数値どうしでなければ計算・比較できません", node.line)

        if op == "lt":
            return left < right
        if op == "le":
            return left <= right
        if op == "gt":
            return left > right
        if op == "ge":
            return left >= right
        if op == "plus":
            return left + right
        if op == "minus":
            return left - right
        if op == "mul":
            return left * right
        if op == "mod":
            if not (_is_int(left) and _is_int(right)):
                raise ExecError("mod は整数どうしでなければなりません", node.line)
            if right == 0:
                raise ExecError("0 で割っています", node.line)
            self._check_sign(node, left, right)
            return left - right * _trunc_div(left, right)
        if op == "div":
            return self._divide(node, left, right)
        raise ExecError(f"未対応の演算子です: {op}", node.line)

    def _divide(self, node: A.Binary, left, right):
        if right == 0:
            raise ExecError("0 で割っています", node.line)
        self._check_sign(node, left, right)
        both_int = _is_int(left) and _is_int(right)
        if node.quotient:
            if not both_int:
                raise ExecError("「の商」は整数どうしの ÷ にだけ使えます", node.line)
            return _trunc_div(left, right)
        if not both_int:
            return left / right
        mode = self.options.int_div
        if mode == "quotient":
            return _trunc_div(left, right)
        if mode == "real":
            return left / right
        if left % right != 0:
            raise ExecError(
                f"整数どうしの ÷ が割り切れません（{left} ÷ {right}）。"
                "「の商」を付けるか、int_div を quotient か real にしてください", node.line)
        return left // right

    def _check_sign(self, node, left, right) -> None:
        if self.options.negative_divmod == "error" and (left < 0 or right < 0):
            raise ExecError("負の数を含む ÷ / mod は使えない設定です", node.line)

    def _eval_Call(self, node: A.Call):
        proc = self.program.procs.get(node.name)
        if proc is None and node.name in self.builtins:
            return self.builtins[node.name](*[self._eval(arg) for arg in node.args])
        if proc is None:
            raise ExecError(f"手続「{node.name}」が見つかりません", node.line)
        if len(node.args) != len(proc.params):
            raise ExecError(
                f"手続「{node.name}」の引数は {len(proc.params)} 個ですが "
                f"{len(node.args)} 個渡されています", node.line)
        if len(self.frames) > self.options.max_depth:
            raise StepLimitError(
                f"呼出しの深さが上限（{self.options.max_depth}）を超えました", node.line)
        # 配列は複製せずにそのまま渡す（呼び出された側の書換えが呼出し元に見える）。
        args = [self._eval(arg) for arg in node.args]
        local = {name: value for (_, name), value in zip(proc.params, args)}
        self.frames.append((proc.name, local))
        try:
            self._exec_block(proc.body)
            return None
        except _ReturnSignal as sig:
            return sig.value
        finally:
            self.frames.pop()
