"""構文木のデータクラス。

構文解析器が作り、実行器が読むだけの入れ物。すべての節が行番号を持つ
（トレース表と誤りの報告で使う）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TypeSpec:
    base: str   # int / real / bool / char / string
    dims: int   # 0=単独の値, 1=配列, 2=二次元配列


# ---- 式 ----

@dataclass
class Num:
    value: int | float
    line: int


@dataclass
class Str:
    value: str
    line: int


@dataclass
class Bool:
    value: bool
    line: int


@dataclass
class Var:
    name: str
    line: int


@dataclass
class Index:
    target: object
    indices: list
    line: int


@dataclass
class Length:
    target: object
    line: int
    axis: int = 0      # 0=要素数（二次元配列なら行数）, 1=列数


@dataclass
class Call:
    name: str
    args: list
    line: int


@dataclass
class Unary:
    op: str            # not / plus / minus
    operand: object
    line: int


@dataclass
class Binary:
    op: str            # mul div mod plus minus ne le ge lt gt eq and or
    left: object
    right: object
    line: int
    quotient: bool = False   # 「÷ … の商」と書かれた除算


@dataclass
class ArrayLit:
    items: list
    line: int


@dataclass
class ArrayFill:
    """{n 個の 0} の形の配列。"""
    count: object
    value: object
    line: int


@dataclass
class Undef:
    """「未定義の値」。"""
    line: int


@dataclass
class IsUndef:
    """「x が 未定義」「x が 未定義でない」。"""
    operand: object
    negate: bool       # True なら「未定義でない」
    line: int


# ---- 文 ----

@dataclass
class Decl:
    type: TypeSpec
    items: list        # [(変数名, 初期値の式 or None)]
    line: int
    is_global: bool = False   # 「大域:」付きの宣言


@dataclass
class Assign:
    target: object     # Var か Index
    value: object
    line: int


@dataclass
class If:
    branches: list     # [(条件式, 文の並び, 行番号)]  if と elseif
    else_body: list | None
    line: int


@dataclass
class While:
    cond: object
    body: list
    line: int


@dataclass
class DoWhile:
    body: list
    cond: object
    line: int          # do の行
    cond_line: int     # 末尾の while の行


@dataclass
class For:
    var: str
    start: object
    end: object
    step: object
    direction: str     # inc / dec
    body: list
    line: int


@dataclass
class Return:
    value: object | None
    line: int


@dataclass
class Output:
    value: object
    line: int


@dataclass
class Append:
    target: object
    value: object
    line: int


@dataclass
class Break:
    """「繰返し処理を終了する」。いちばん内側の繰返しを抜ける。"""
    line: int


@dataclass
class ExprStmt:
    """手続の呼出しだけの文。"""
    call: Call
    line: int


# ---- 全体 ----

@dataclass
class Proc:
    name: str
    params: list       # [(TypeSpec, 変数名)]
    return_type: TypeSpec | None
    body: list
    line: int


@dataclass
class Program:
    procs: dict = field(default_factory=dict)   # 名前 -> Proc
    main: list = field(default_factory=list)    # 手続の外に書かれた文
