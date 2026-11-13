"""構文解析：トークン列を構文木にする（再帰下降）。

演算子の優先順位は IPA の「擬似言語の記述形式」の表のとおり、高い順に
  単項(not + -) > 乗除(× ÷ mod) > 加減(+ -) > 関係(≠ ≦ ≧ < = >) > and > or
とし、優先順位1段につき関数1つで表している。
"""

from __future__ import annotations

from . import ast_nodes as A
from .errors import ParseError
from .lexer import Token, tokenize
from .notation import Notation, load_notation

_REL_OPS = ("ne", "le", "ge", "lt", "gt", "eq")
_ADD_OPS = ("plus", "minus")
_MUL_OPS = ("mul", "div", "mod")
_UNARY_OPS = ("not", "plus", "minus")


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ---- トークン操作 ----

    @property
    def peek(self) -> Token:
        return self.tokens[self.pos]

    def _next(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def _accept(self, kind: str) -> Token | None:
        if self.peek.kind == kind:
            return self._next()
        return None

    def _expect(self, kind: str, what: str) -> Token:
        if self.peek.kind != kind:
            got = self.peek.text or "行末"
            raise ParseError(f"{what} が必要ですが「{got}」があります", self.peek.line)
        return self._next()

    def _skip_newlines(self) -> None:
        while self.peek.kind == "NEWLINE":
            self._next()

    def _end_of_statement(self) -> None:
        if self.peek.kind == "EOF":
            return
        self._expect("NEWLINE", "行末")

    # ---- プログラム全体 ----

    def program(self) -> A.Program:
        prog = A.Program()
        while True:
            self._skip_newlines()
            if self.peek.kind == "EOF":
                break
            if self.peek.kind == "proc_mark":
                proc = self._proc()
                if proc.name in prog.procs:
                    raise ParseError(f"手続「{proc.name}」が二重に宣言されています", proc.line)
                prog.procs[proc.name] = proc
            else:
                prog.main.append(self._statement())
        return prog

    def _proc(self) -> A.Proc:
        mark = self._expect("proc_mark", "○")
        return_type = None
        if self.peek.kind == "TYPE":
            return_type = A.TypeSpec(*self._next().value)
            self._expect("colon", "「:」")
        name = self._expect("IDENT", "手続名").value
        self._expect("lparen", "「(」")
        params = []
        if self.peek.kind != "rparen":
            while True:
                ptype = A.TypeSpec(*self._expect("TYPE", "引数の型名").value)
                self._expect("colon", "「:」")
                params.append((ptype, self._expect("IDENT", "引数名").value))
                if not self._accept("comma"):
                    break
        self._expect("rparen", "「)」")
        self._end_of_statement()
        # 手続の本体は「○の行より深く字下げされた文」まで。
        # 字下げが戻ったら、そこからは手続の外の文として扱う。
        body = self._block((), min_indent=mark.indent + 1)
        return A.Proc(name, params, return_type, body, mark.line)

    # ---- 文 ----

    def _block(self, stop_kinds: tuple[str, ...], do_indent: int | None = None,
               min_indent: int | None = None) -> list:
        """stop_kinds のどれかが現れるまで文を読む。終端そのものは読まない。

        do_indent は do〜while 専用。do の本体に書かれた while 文と、do を閉じる
        while は見た目が同じなので、「do と同じ字下げの while が終端」と決めている。
        min_indent は手続の本体専用。本体には閉じるキーワードがないので、
        字下げが min_indent より浅くなったところで本体の終わりとする。
        """
        stmts = []
        while True:
            self._skip_newlines()
            tok = self.peek
            if tok.kind in stop_kinds or tok.kind in ("EOF", "proc_mark"):
                break
            if do_indent is not None and tok.kind == "while" and tok.indent == do_indent:
                break
            if min_indent is not None and tok.indent < min_indent:
                break
            stmts.append(self._statement())
        return stmts

    def _statement(self):
        tok = self.peek
        kind = tok.kind
        if kind == "TYPE":
            return self._decl()
        if kind == "global":
            # 「大域: 整数型: x ← 0」。手続の外にだけ書ける（実行時に確かめる）。
            self._next()
            self._expect("colon", "「:」")
            if self.peek.kind != "TYPE":
                raise ParseError("「大域:」の後ろには型名が必要です", self.peek.line)
            decl = self._decl()
            decl.is_global = True
            decl.line = tok.line
            return decl
        if kind == "if":
            return self._if()
        if kind == "while":
            return self._while()
        if kind == "do":
            return self._do_while()
        if kind == "for":
            return self._for()
        if kind == "return":
            self._next()
            value = None if self.peek.kind in ("NEWLINE", "EOF") else self._expr()
            self._end_of_statement()
            return A.Return(value, tok.line)
        return self._expr_led_statement()

    def _decl(self) -> A.Decl:
        tok = self._next()
        self._expect("colon", "「:」")
        items = []
        while True:
            name = self._expect("IDENT", "変数名").value
            init = self._expr() if self._accept("assign") else None
            items.append((name, init))
            if not self._accept("comma"):
                break
        self._end_of_statement()
        return A.Decl(A.TypeSpec(*tok.value), items, tok.line)

    def _condition(self):
        self._expect("lparen", "「(」")
        cond = self._expr()
        self._expect("rparen", "「)」")
        return cond

    def _if(self) -> A.If:
        first = self._next()
        branches = []
        line = first.line
        while True:
            cond = self._condition()
            self._end_of_statement()
            body = self._block(("elseif", "else", "endif"))
            branches.append((cond, body, line))
            nxt = self._accept("elseif")
            if not nxt:
                break
            line = nxt.line
        else_body = None
        if self._accept("else"):
            self._end_of_statement()
            else_body = self._block(("endif",))
        self._expect("endif", "endif")
        self._end_of_statement()
        return A.If(branches, else_body, first.line)

    def _while(self) -> A.While:
        tok = self._next()
        cond = self._condition()
        self._end_of_statement()
        body = self._block(("endwhile",))
        self._expect("endwhile", "endwhile")
        self._end_of_statement()
        return A.While(cond, body, tok.line)

    def _do_while(self) -> A.DoWhile:
        tok = self._next()
        self._end_of_statement()
        body = self._block((), do_indent=tok.indent)
        closing = self._expect("while", "do を閉じる while")
        cond = self._condition()
        self._end_of_statement()
        return A.DoWhile(body, cond, tok.line, closing.line)

    def _for(self) -> A.For:
        tok = self._next()
        self._expect("lparen", "「(」")
        var = self._expect("IDENT", "繰返しの変数名").value
        self._expect("wo", "「を」")
        start = self._expr()
        self._expect("from", "「から」")
        end = self._expr()
        self._expect("to", "「まで」")
        step = self._expr()
        self._expect("step", "「ずつ」")
        if self._accept("inc"):
            direction = "inc"
        elif self._accept("dec"):
            direction = "dec"
        else:
            raise ParseError("「増やす」か「減らす」が必要です", self.peek.line)
        self._expect("rparen", "「)」")
        self._end_of_statement()
        body = self._block(("endfor",))
        self._expect("endfor", "endfor")
        self._end_of_statement()
        return A.For(var, start, end, step, direction, body, tok.line)

    def _expr_led_statement(self):
        """式から始まる文：代入、出力、末尾への追加、手続の呼出し。"""
        line = self.peek.line
        expr = self._expr()
        if self._accept("assign"):
            if not isinstance(expr, (A.Var, A.Index)):
                raise ParseError("代入先は変数か配列の要素でなければなりません", line)
            stmt = A.Assign(expr, self._expr(), line)
        elif self._accept("wo"):
            self._expect("output", "「出力する」")
            stmt = A.Output(expr, line)
        elif self._accept("append_to"):
            value = self._expr()
            self._expect("wo", "「を」")
            self._expect("append", "「追加する」")
            stmt = A.Append(expr, value, line)
        elif isinstance(expr, A.Call):
            stmt = A.ExprStmt(expr, line)
        else:
            raise ParseError("文として解釈できません", line)
        self._end_of_statement()
        return stmt

    # ---- 式（優先順位の低い順） ----

    def _expr(self):
        return self._or()

    def _or(self):
        left = self._and()
        while self.peek.kind == "or":
            tok = self._next()
            left = A.Binary("or", left, self._and(), tok.line)
        return left

    def _and(self):
        left = self._relation()
        while self.peek.kind == "and":
            tok = self._next()
            left = A.Binary("and", left, self._relation(), tok.line)
        return left

    def _relation(self):
        left = self._additive()
        while self.peek.kind in _REL_OPS:
            tok = self._next()
            left = A.Binary(tok.kind, left, self._additive(), tok.line)
        return left

    def _additive(self):
        left = self._multiplicative()
        while self.peek.kind in _ADD_OPS:
            tok = self._next()
            left = A.Binary(tok.kind, left, self._multiplicative(), tok.line)
        return left

    def _multiplicative(self):
        left = self._unary()
        while self.peek.kind in _MUL_OPS:
            tok = self._next()
            node = A.Binary(tok.kind, left, self._unary(), tok.line)
            if self.peek.kind in ("quotient", "remainder"):
                # 公開問題にある「a ÷ b の商」「a ÷ b の余り」という書き方
                if tok.kind != "div":
                    raise ParseError("「の商」「の余り」は ÷ の直後にだけ書けます", self.peek.line)
                if self._next().kind == "quotient":
                    node.quotient = True
                else:
                    node.op = "mod"
            left = node
        return left

    def _unary(self):
        if self.peek.kind in _UNARY_OPS:
            tok = self._next()
            return A.Unary(tok.kind, self._unary(), tok.line)
        return self._postfix()

    def _postfix(self):
        node = self._primary()
        while True:
            if self.peek.kind == "lbracket":
                tok = self._next()
                indices = [self._expr()]
                while self._accept("comma"):
                    indices.append(self._expr())
                self._expect("rbracket", "「]」")
                node = A.Index(node, indices, tok.line)
            elif self.peek.kind in ("length", "rows"):
                tok = self._next()
                node = A.Length(node, tok.line)
            elif self.peek.kind == "cols":
                tok = self._next()
                node = A.Length(node, tok.line, axis=1)
            elif self.peek.kind == "is":
                tok = self._next()
                if self._accept("undef"):
                    node = A.IsUndef(node, False, tok.line)
                elif self._accept("not_undef"):
                    node = A.IsUndef(node, True, tok.line)
                else:
                    raise ParseError("「が」の後ろには「未定義」か「未定義でない」が必要です", tok.line)
            else:
                return node

    def _primary(self):
        tok = self.peek
        kind = tok.kind
        if kind in ("INT", "REAL"):
            self._next()
            return A.Num(tok.value, tok.line)
        if kind == "STRING":
            self._next()
            return A.Str(tok.value, tok.line)
        if kind in ("true", "false"):
            self._next()
            return A.Bool(kind == "true", tok.line)
        if kind == "undef_value":
            self._next()
            return A.Undef(tok.line)
        if kind == "IDENT":
            self._next()
            if self._accept("lparen"):
                args = []
                if self.peek.kind != "rparen":
                    args.append(self._expr())
                    while self._accept("comma"):
                        args.append(self._expr())
                self._expect("rparen", "「)」")
                return A.Call(tok.value, args, tok.line)
            return A.Var(tok.value, tok.line)
        if kind == "lparen":
            self._next()
            inner = self._expr()
            self._expect("rparen", "「)」")
            return inner
        if kind == "lbrace":
            return self._array_literal()
        got = tok.text or "行末"
        raise ParseError(f"式が必要ですが「{got}」があります", tok.line)

    def _array_literal(self):
        tok = self._next()
        if self._accept("rbrace"):
            return A.ArrayLit([], tok.line)
        first = self._expr()
        if self._accept("count_of"):
            value = self._expr()
            self._expect("rbrace", "「}」")
            return A.ArrayFill(first, value, tok.line)
        items = [first]
        while self._accept("comma"):
            items.append(self._expr())
        self._expect("rbrace", "「}」")
        return A.ArrayLit(items, tok.line)


def parse_program(source: str, notation: Notation | None = None) -> A.Program:
    notation = notation or load_notation()
    return Parser(tokenize(source, notation)).program()


def parse_expression(text: str, notation: Notation | None = None):
    """式を1つだけ解析する（テンプレートの call 欄や制約式で使う）。"""
    notation = notation or load_notation()
    parser = Parser(tokenize(text, notation))
    parser._skip_newlines()
    expr = parser._expr()
    parser._skip_newlines()
    if parser.peek.kind != "EOF":
        raise ParseError(f"式の後ろに余分な「{parser.peek.text}」があります", parser.peek.line)
    return expr
