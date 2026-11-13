"""表示用の整形：行番号つきのプログラムと、トレース表を HTML にする。

画面（app.py）から切り離してあるので、Streamlit がなくてもテストできる。
利用者に見せる文字列はすべて html.escape を通す。
"""

from __future__ import annotations

import html

from .interpreter import UNSET, RunResult, format_value

KIND_LABELS = {
    "decl": "宣言",
    "assign": "代入",
    "cond": "条件判定",
    "for_init": "繰返しの初期化",
    "for_step": "繰返しの更新",
    "call": "呼出し",
    "return": "戻る",
    "output": "出力",
    "append": "追加",
}

STYLE = """
<style>
.giji-code, .giji-trace { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size: 0.9rem; }
.giji-code { border-collapse: collapse; width: 100%; margin: 0.25rem 0 1rem; }
.giji-code td { padding: 0 0.6rem; white-space: pre; border: none; line-height: 1.6; }
.giji-code td.no { text-align: right; opacity: 0.55; user-select: none; width: 1%; border-right: 1px solid rgba(128,128,128,0.4); }
.giji-code tr.focus td { background: rgba(255, 200, 0, 0.28); }
.giji-code tr.focus td.no { opacity: 1; font-weight: 700; }
.giji-trace-wrap { max-height: 28rem; overflow: auto; border: 1px solid rgba(128,128,128,0.35); border-radius: 6px; }
.giji-trace { border-collapse: collapse; width: 100%; }
.giji-trace th, .giji-trace td { padding: 0.2rem 0.6rem; text-align: left; white-space: nowrap; border-bottom: 1px solid rgba(128,128,128,0.25); }
.giji-trace th { position: sticky; top: 0; background: rgba(128,128,128,0.25); backdrop-filter: blur(4px); }
.giji-trace th.focus-col, .giji-trace td.focus-col { background: rgba(80, 160, 255, 0.16); }
.giji-trace tr.focus-line td { background: rgba(255, 200, 0, 0.20); }
.giji-trace tr.focus-pass td { background: rgba(255, 200, 0, 0.45); font-weight: 700; }
.giji-trace tr.focus-pass td.focus-col { background: rgba(255, 140, 0, 0.60); outline: 2px solid rgba(255, 120, 0, 0.9); }
.giji-trace td.changed { font-weight: 700; }
.giji-trace td.empty { opacity: 0.35; }
</style>
"""


_BLANKS = {"［　ａ　］": "ａ", "［　ｂ　］": "ｂ"}


def source_html(source: str, focus_lines: tuple | list | set = (), *,
                numbered: bool = True, markers: dict | None = None) -> str:
    """プログラムを表にする。focus_lines の行は色を付ける。

    numbered=False にすると行番号を出さない（本番形式）。
    markers は 行番号 -> 目印 で、その行の末尾に「/*** α ***/」の注釈を付ける。
    空欄（［　ａ　］）は、あとから JavaScript で埋められるように span で包む。
    """
    focus = set(focus_lines)
    markers = markers or {}
    rows = []
    for number, line in enumerate(source.split("\n"), start=1):
        text = html.escape(line)
        for mark, name in _BLANKS.items():
            text = text.replace(mark, f'<span class="blank" data-blank="{name}">{mark}</span>')
        if number in markers:
            text += f'　<span class="marker">/*** {html.escape(markers[number])} ***/</span>'
        cls = ' class="focus"' if number in focus else ""
        no = f'<td class="no">{number}</td>' if numbered else ""
        rows.append(f'<tr{cls} data-line="{number}">{no}<td>{text or " "}</td></tr>')
    kind = "giji-code" if numbered else "giji-code plain"
    return f'<div class="scroll-x"><table class="{kind}">{"".join(rows)}</table></div>'


def _describe(step) -> str:
    label = KIND_LABELS.get(step.kind, step.kind)
    if step.kind == "cond":
        return f"{label}（{'真' if step.detail else '偽'}）"
    if step.kind in ("return", "output") and step.detail is not None:
        return f"{label}（{format_value(step.detail)}）"
    return label


def trace_rows(result: RunResult, focus_line: int | None = None,
               focus_var: str | None = None, focus_pass: int | None = None) -> tuple[list, list]:
    """トレース表の中身を (変数名の並び, 行の並び) で返す。

    各行は dict で、cells は 変数名 -> (表示文字列, 直前から変わったか)。
    mark は "" / "line"（設問が指す行） / "pass"（設問が指す回そのもの）。
    """
    names: list[str] = []
    for step in result.steps:
        for name in step.vars:
            if name not in names:
                names.append(name)

    rows = []
    last_seen: dict[tuple, dict] = {}       # (手続名, 深さ) -> 直前の変数の値
    passes = 0
    for step in result.steps:
        frame = (step.proc, step.depth)
        previous = last_seen.get(frame, {})
        cells = {}
        for name in names:
            if name not in step.vars:
                cells[name] = ("", False)
                continue
            value = step.vars[name]
            text = "未定義" if value is UNSET else format_value(value)
            changed = name not in previous or format_value(previous[name]) != format_value(value)
            cells[name] = (text, changed and value is not UNSET)
        last_seen[frame] = step.vars

        mark = ""
        if focus_line is not None and step.line == focus_line:
            mark = "line"
            if focus_var is None or focus_var in step.vars:
                passes += 1
                if focus_pass is not None and passes == focus_pass:
                    mark = "pass"
        rows.append({
            "index": step.index, "line": step.line, "what": _describe(step),
            "proc": step.proc, "depth": step.depth, "cells": cells, "mark": mark,
        })
    return names, rows


def trace_html(result: RunResult, focus_line: int | None = None,
               focus_var: str | None = None, focus_pass: int | None = None) -> str:
    """全ステップのトレース表。設問が指す行・回・変数に色を付ける。"""
    names, rows = trace_rows(result, focus_line, focus_var, focus_pass)
    return trace_table_html(names, rows, focus_var)


def trace_table_html(names: list, rows: list, focus_var: str | None = None) -> str:
    """trace_rows の結果（または保存しておいた同じ形のデータ）から表を作る。"""
    show_proc = len({(r["proc"], r["depth"]) for r in rows}) > 1

    head = ["<th>#</th>", "<th>行</th>", "<th>したこと</th>"]
    if show_proc:
        head.append("<th>手続</th>")
    for name in names:
        cls = ' class="focus-col"' if name == focus_var else ""
        head.append(f'<th{cls} data-var="{html.escape(name)}">{html.escape(name)}</th>')

    body = []
    for row in rows:
        tr_class = {"line": "focus-line", "pass": "focus-pass"}.get(row["mark"], "")
        cells = [f'<td>{row["index"]}</td>', f'<td>{row["line"]}</td>',
                 f'<td>{html.escape(row["what"])}</td>']
        if show_proc:
            indent = "　" * max(row["depth"] - 1, 0)
            cells.append(f'<td>{indent}{html.escape(row["proc"])}</td>')
        for name in names:
            text, changed = row["cells"][name]
            classes = []
            if name == focus_var:
                classes.append("focus-col")
            if changed:
                classes.append("changed")
            if not text:
                classes.append("empty")
            cls = f' class="{" ".join(classes)}"' if classes else ""
            cells.append(f'<td{cls} data-var="{html.escape(name)}">{html.escape(text) or "—"}</td>')
        cls = f' class="{tr_class}"' if tr_class else ""
        body.append(f'<tr{cls} data-line="{row["line"]}" data-step="{row["index"]}">{"".join(cells)}</tr>')

    return ('<div class="giji-trace-wrap scroll-x"><table class="giji-trace">'
            f'<thead><tr>{"".join(head)}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')
