"""行番号つきの例外。

問題テンプレートの検査では「どの行で何が起きたか」が必要になるので、
すべての例外に行番号を持たせている。
"""

from __future__ import annotations


class GijiError(Exception):
    """処理系が出すすべての例外の親。"""

    def __init__(self, message: str, line: int | None = None):
        self.message = message
        self.line = line
        prefix = f"{line}行目: " if line is not None else ""
        super().__init__(prefix + message)


class NotationError(GijiError):
    """表記の対応表（YAML）に誤りがある。"""


class LexError(GijiError):
    """字句解析で読めない文字があった。"""


class ParseError(GijiError):
    """構文が擬似言語の規則に合わない。"""


class ExecError(GijiError):
    """実行時の誤り（範囲外参照、未設定の変数、0除算など）。"""


class TemplateError(GijiError):
    """問題テンプレートの書き方に誤りがある。"""


class GenerationError(GijiError):
    """条件を満たす問題を、決められた回数の抽選で作れなかった。"""


class StepLimitError(ExecError):
    """実行ステップ数または再帰の深さが上限を超えた（無限ループ対策）。"""
