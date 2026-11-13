#!/usr/bin/env python3
"""静的サイトのビルド：テンプレートから問題を作り、dist/ に HTML 一式を出力する。

    python build.py                  # 検査 → 問題の確定 → HTML → 共有用画像 → sitemap → リンク検査
    python build.py --no-ogp         # 共有用画像を作らない（速い。見た目の確認用）
    python -m http.server -d dist    # 手元で確認（http://localhost:8000）

テンプレートを足したら、もう一度このスクリプトを動かすだけでよい。
一度作った問題は problems/ に生成結果ごと保存してあり、以後は作り直さない。
テンプレートを直しても、公開済みの問題の URL と中身は変わらず、新しく作る問題にだけ反映される。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import jinja2
import markdown
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from giji.errors import GijiError  # noqa: E402
from giji.exam import build_exam  # noqa: E402
from giji.explain import explain  # noqa: E402
from giji.generator import Template, generate, load_templates  # noqa: E402
from giji.render import source_html, trace_rows, trace_table_html  # noqa: E402
from validate_templates import check_template  # noqa: E402

LEVEL_NAMES = {1: "入門", 2: "基礎", 3: "中級", 4: "本試験相当"}
CHOICE_LABELS = "アイウエオカキクケコ"
QUESTION_ORDER = {"fill_blank": 0, "var_at_line": 1, "exec_count": 2, "return_value": 3}
PLACEHOLDER_URL = "https://example.com"

DEFAULTS = {
    "name": "擬似言語トレースドリル", "exam_label": "", "tagline": "", "description": "",
    "base_url": PLACEHOLDER_URL, "custom_domain": "", "base_path": "",
    "problems": {"indexed": 10, "extra": 20, "candidates": 150, "min_weight": 0.5},
    "contact": {"form_url": "", "email": ""},
    "analytics": {"cloudflare_token": ""},
    "search_console": {"google_verification": ""},
    "ogp": {"font": "site/fonts/NotoSansJP-Bold.otf"},
}


# ---- 設定と原稿 ----

def load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    site = {}
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        if isinstance(default, dict):
            value = {**default, **(value or {})}
        site[key] = value
    site["base_url"] = str(site["base_url"]).rstrip("/")
    site["base_path"] = str(site["base_path"] or "").rstrip("/")
    return site


def read_content(path: Path) -> tuple[dict, str]:
    """先頭の --- で囲んだ設定と、Markdown 本文（HTML に変換済み）を返す。"""
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    if text.startswith("---"):
        _, front, text = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
    body = markdown.markdown(text, extensions=["fenced_code", "tables"])
    return meta, body


# ---- 問題の選び方 ----

def pick_new_seeds(template: Template, cfg: dict, frozen: list, count: int, warnings: list) -> list:
    """新しく作る問題の種（seed）を count 個選ぶ。

    保存済みの問題と同じもの（プログラムも呼出しも同じ）は選ばない。
    答えがまだ出ていない問題を優先し、似た問題ばかりにならないようにする。
    """
    if count <= 0:
        return []
    pool = {}
    for seed in range(int(cfg["candidates"])):
        try:
            pool[seed] = generate(template, seed)
        except GijiError:
            continue
    used = {(snap["source"], snap["call"]) for snap in frozen}
    seen_answers = {(q["type"], q["answer"]) for snap in frozen
                    for q in snap.get("practice", {}).get("questions", [])}
    picked: list = []
    while len(picked) < count:
        best, best_score = None, -1
        for seed, problem in pool.items():
            if seed in picked or (problem.source, problem.call) in used:
                continue
            score = sum(1 for q in problem.questions if (q.type, q.answer) not in seen_answers)
            if score > best_score:
                best, best_score = seed, score
        if best is None:
            warnings.append(f"{template.id}: 値の違う問題があと {count - len(picked)} 問そろいませんでした。"
                            "params の範囲を広げてください")
            break
        picked.append(best)
        used.add((pool[best].source, pool[best].call))
        seen_answers.update((q.type, q.answer) for q in pool[best].questions)
    return picked


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_new_json(path: Path, data: dict) -> None:
    """新しいファイルとしてだけ保存する。同じ名前のファイルがあれば、上書きせずに止まる。

    公開済みの問題を誤って書き換えないための最後の歯止め（"x" は「なければ作る、あれば失敗」）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def number_ranges(numbers: list[int]) -> str:
    """[3, 7, 8, 9] を「03, 07〜09」の形にする。"""
    parts, start, previous = [], None, None
    for number in sorted(numbers) + [None]:
        if start is None:
            start = previous = number
        elif number is not None and number == previous + 1:
            previous = number
        else:
            parts.append(f"{start:02d}" if start == previous else f"{start:02d}〜{previous:02d}")
            start = previous = number
    return ", ".join(parts)


# ---- 問題ページの中身 ----

def question_focus(problem, question) -> dict:
    """設問が指す行・その回のステップ番号・変数（JavaScript が色付けに使う）。"""
    detail = question.detail
    steps = problem.result.steps
    if question.type == "var_at_line":
        hits = [s for s in steps if s.line == detail["line"] and detail["var"] in s.vars]
        return {"line": detail["line"], "variable": detail["var"],
                "step": hits[detail["pass"] - 1].index, "showLineBefore": True}
    if question.type == "exec_count":
        return {"line": detail["line"], "variable": None, "step": None, "showLineBefore": True}
    if question.type == "fill_blank":
        return {"line": detail["line"], "variable": None, "step": None, "showLineBefore": False}
    returns = [s for s in steps if s.kind == "return"]
    if not returns:
        return {"line": None, "variable": None, "step": None, "showLineBefore": False}
    top = min(s.depth for s in returns)
    last = [s for s in returns if s.depth == top][-1]
    return {"line": last.line, "variable": None, "step": last.index, "showLineBefore": False}


def pick_questions(problem, number: int, min_weight: float) -> list:
    """静的ページに出す設問を選ぶ。

    空欄補充の問題文は戻り値を明かすので、同じページに「戻り値はどれか」は置けない。
    奇数番の問題は空欄補充を、偶数番の問題は戻り値を出して、ページごとの違いも作る。
    """
    questions = [q for q in problem.questions if q.weight >= min_weight]
    kinds = {q.type for q in questions}
    if {"fill_blank", "return_value"} <= kinds:
        drop = "return_value" if number % 2 == 1 else "fill_blank"
        questions = [q for q in questions if q.type != drop]
    return sorted(questions, key=lambda q: QUESTION_ORDER[q.type])


def trace_data(result) -> dict:
    names, rows = trace_rows(result)
    return {"names": names, "rows": rows}


def make_snapshot(template: Template, seed: int, number: int, min_weight: float) -> dict:
    """問題を1つ生成し、ページに必要なものをすべて含むデータにする（これを保存して固定する）。"""
    problem = generate(template, seed)
    questions = pick_questions(problem, number, min_weight)
    practice = []
    for question in questions:
        if not question.choices:
            continue                      # 記述式になった設問は静的ページでは扱わない
        labels = dict(zip(question.choices, CHOICE_LABELS))
        practice.append({
            "type": question.type, "prompt": question.prompt,
            "choices": [{"label": labels[c], "text": c} for c in question.choices],
            "answer": question.answer, "answer_label": labels[question.answer],
            "explain": explain(problem, question), "focus": question_focus(problem, question),
        })
    blank = next((q for q in questions if q.type == "fill_blank"), None)

    exam_data = None
    exam = build_exam(template, problem, number, min_weight)
    if exam is not None:
        labelled = [{"label": CHOICE_LABELS[i], "texts": texts} for i, texts in enumerate(exam.choices)]
        answer = labelled[exam.answer_index]
        pairs = "，".join(f"{b} {t}" for b, t in zip(exam.blanks, answer["texts"]))
        exam_data = {
            "form": exam.form, "lead": exam.lead, "body": [p for p in exam.body if p],
            "blanks": exam.blanks, "choices": labelled, "answer_label": answer["label"],
            "answer_text": pairs if len(exam.blanks) > 1 else answer["texts"][0],
            "explain": exam.explain, "source": exam.source,
            "markers": {str(line): mark for line, mark in exam.markers.items()},
            "focus": exam.focus,
        }
    return {
        "version": 1, "template_id": template.id, "number": number, "seed": seed,
        "description": problem.description, "call": problem.call, "source": problem.source,
        "explanation": problem.explanation,
        "practice": {"source": blank.source if blank else problem.source, "questions": practice},
        "exam": exam_data, "trace": trace_data(problem.result),
    }


def make_example(template: Template, seed: int) -> dict:
    """解説ページに載せる例題（全トレースつき）のデータ。"""
    problem = generate(template, seed)
    return {
        "version": 1, "template_id": template.id, "seed": seed, "call": problem.call,
        "source": problem.source, "trace": trace_data(problem.result),
        "questions": [{"prompt": q.prompt, "answer": q.answer, "explain": explain(problem, q)}
                      for q in problem.questions if q.type != "fill_blank"],
    }


def view_from_snapshot(snap: dict) -> dict:
    """保存しておいたデータから、ページに埋め込む HTML と JavaScript 用のデータを作る。"""
    practice = snap["practice"]
    quiz = [{"type": q["type"], "answer": q["answer_label"], "answerText": q["answer"], **q["focus"]}
            for q in practice["questions"]]
    views = [{**q, "key": q["type"]} for q in practice["questions"]]
    exam = snap.get("exam")
    exam_view, exam_quiz, exam_html = None, None, ""
    if exam:
        markers = {int(line): mark for line, mark in exam["markers"].items()}
        exam_view = {**exam, "marker_line": next(iter(markers), None)}
        exam_quiz = {"answer": exam["answer_label"], **exam["focus"]}
        exam_html = source_html(exam["source"], numbered=False, markers=markers)
    trace = snap["trace"]
    return {
        "problem": {"description": snap["description"], "call": snap["call"],
                    "explanation": snap["explanation"]},
        "questions": views, "exam": exam_view, "exam_html": exam_html,
        "source_html": source_html(snap["source"]),
        "practice_html": source_html(practice["source"]),
        "trace_html": trace_table_html(trace["names"], trace["rows"]),
        "quiz_json": json.dumps({"practice": quiz, "exam": exam_quiz},
                                ensure_ascii=False).replace("</", "<\\/"),
    }


# ---- 共有用の画像（OGP） ----

def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    lines, current = [], ""
    for ch in text:
        if draw.textlength(current + ch, font=font) > width:
            lines.append(current)
            current = ch
            if len(lines) == max_lines:
                break
        else:
            current += ch
    if len(lines) < max_lines and current:
        lines.append(current)
    if len(lines) == max_lines and "".join(lines) != text:
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def draw_card(path: Path, font_path: Path, site_name: str, eyebrow: str, title: str, body: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1200, 630), (20, 33, 61))
    draw = ImageDraw.Draw(image)
    small = ImageFont.truetype(str(font_path), 34)
    large = ImageFont.truetype(str(font_path), 68)
    middle = ImageFont.truetype(str(font_path), 36)
    draw.rectangle([0, 0, 1200, 14], fill=(252, 163, 17))
    draw.text((70, 70), eyebrow, font=small, fill=(252, 163, 17))
    y = 140
    for line in _wrap(draw, title, large, 1060, 2):
        draw.text((70, y), line, font=large, fill=(255, 255, 255))
        y += 92
    y += 24
    for line in _wrap(draw, body, middle, 1060, 3):
        draw.text((70, y), line, font=middle, fill=(214, 222, 235))
        y += 56
    draw.text((70, 545), site_name, font=small, fill=(160, 174, 196))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


# ---- ビルド本体 ----

class Builder:
    def __init__(self, site: dict, out: Path, store: Path, make_ogp: bool, frozen: bool = False):
        self.site = site
        self.out = out
        self.store = store                 # 生成した問題を保存しておくフォルダ（problems/）
        self.created = 0                   # 今回のビルドで新しく作った問題の数
        self.frozen = frozen               # 真なら新しい問題を作らない（CI 用）
        self.unsaved: list[str] = []       # frozen のときに、保存されていなかった問題
        self.make_ogp = make_ogp
        self.pages: list[dict] = []        # 出力したページ（sitemap とリンク検査に使う）
        self.warnings: list[str] = []
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(ROOT / "site" / "templates"),
            autoescape=True, undefined=jinja2.StrictUndefined)
        static = ROOT / "site" / "static"
        digest = hashlib.sha1(b"".join(p.read_bytes() for p in sorted(static.iterdir())))
        self.build_id = digest.hexdigest()[:8]
        self.font = ROOT / site["ogp"]["font"]
        if make_ogp and not self.font.exists():
            self.warnings.append(f"フォント {self.font} がないので、共有用画像を作りませんでした")
            self.make_ogp = False

    def url(self, path: str) -> str:
        return self.site["base_path"] + path

    def abs_url(self, path: str) -> str:
        return self.site["base_url"] + self.site["base_path"] + path

    def og_image(self, name: str, eyebrow: str, title: str, body: str) -> str:
        path = f"/ogp/{name}.png"
        if self.make_ogp:
            draw_card(self.out / "ogp" / f"{name}.png", self.font, self.site["name"], eyebrow, title, body)
        return self.abs_url(path)

    def render(self, template: str, path: str, *, title: str, description: str,
               og_image: str, breadcrumbs: list | None = None, noindex: bool = False,
               filename: str = "index.html", listed: bool = True, **context) -> None:
        site = self.site
        suffix = f"（{site['exam_label']}）" if site["exam_label"] else ""
        full_title = f"{site['name']}｜{site['tagline']}" if path == "/" else f"{title}｜{site['name']}{suffix}"
        crumbs = breadcrumbs or []
        crumb_json = json.dumps({
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": c["name"],
                                 "item": self.abs_url(c["path"])} for i, c in enumerate(crumbs, 1)],
        }, ensure_ascii=False).replace("</", "<\\/")
        page = {
            "path": path, "title": title, "full_title": full_title,
            "description": " ".join(str(description).split()), "canonical": self.abs_url(path),
            "noindex": noindex, "og_image": og_image, "og_title": title,
            "breadcrumbs": crumbs, "breadcrumb_json": crumb_json,
        }
        html = self.env.get_template(template).render(
            site=site, page=page, url=self.url, build_id=self.build_id, **context)
        target = self.out / path.strip("/") / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        self.pages.append({"path": path, "noindex": noindex or not listed, "html": html, "file": target})

    # -- 各ページ --

    def build(self, templates: list[Template]) -> None:
        site, cfg = self.site, self.site["problems"]
        if self.out.exists():
            shutil.rmtree(self.out)
        (self.out / "static").mkdir(parents=True)
        for item in (ROOT / "site" / "static").iterdir():
            shutil.copy(item, self.out / "static" / item.name)

        default_image = self.og_image("default", site["exam_label"] or "擬似言語", site["name"], site["tagline"])

        algos = []
        for template in sorted(templates, key=lambda t: (t.level, t.title)):
            algos.append(self.algo_info(template, cfg))

        for algo in algos:
            self.build_algo(algo, algos, float(cfg["min_weight"]))
        guides = self.build_guides(default_image)
        self.build_simple("about", "/about/", default_image, show_contact=True)
        self.build_simple("for-teams", "/for-teams/", default_image, show_contact=True)

        levels = [{"name": LEVEL_NAMES.get(level, str(level)),
                   "algos": [a for a in algos if a["level"] == level]}
                  for level in sorted({a["level"] for a in algos})]
        first = algos[0]["problems"][0]["path"] if algos and algos[0]["problems"] else "/"
        self.render("home.html", "/", title=site["name"], description=site["description"],
                    og_image=default_image, levels=levels, guides=guides, first_problem=first)
        self.render("404.html", "/", filename="404.html", listed=False, title="ページが見つかりません",
                    description="お探しのページは見つかりませんでした。", og_image=default_image, noindex=True)
        self.write_extras()

    def frozen_problems(self, template: Template, cfg: dict) -> tuple[list, dict]:
        """保存済みの問題を読み込み、足りない分だけ新しく作って保存する。

        保存済みのファイルは読むだけで、書き換えない。これが「公開した問題は変わらない」の仕組み。
        """
        folder = self.store / template.id
        wanted = int(cfg["indexed"]) + int(cfg["extra"])
        # 番号ごとに「あるか・ないか」を調べる。途中の番号が欠けていても、その後ろは保存済みとして扱う。
        saved: dict[int, dict] = {}
        missing: list[int] = []
        for number in range(1, wanted + 1):
            path = folder / f"{number:02d}.json"
            if path.exists():
                saved[number] = load_json(path)
            else:
                missing.append(number)
        example_path = folder / "example.json"
        need_example = not example_path.exists()

        if self.frozen and (missing or need_example):
            # CI で作った問題はリポジトリに残らず、次のビルドで別の問題になり得る。作らずに知らせる。
            if missing:
                self.unsaved.append(f"{template.id}: 問題{number_ranges(missing)}（{len(missing)}問）")
            if need_example:
                self.unsaved.append(f"{template.id}: 解説ページの例題")
        elif missing or need_example:
            seeds = pick_new_seeds(template, cfg, list(saved.values()),
                                   len(missing) + (1 if need_example else 0), self.warnings)
            # 欠けている番号にだけ、番号の小さい順に割り当てる。例題は余った種で作る。
            for number, seed in zip(missing, seeds):
                snap = make_snapshot(template, seed, number, float(cfg["min_weight"]))
                save_new_json(folder / f"{number:02d}.json", snap)
                saved[number] = snap
                self.created += 1
            if need_example and len(seeds) > len(missing):
                save_new_json(example_path, make_example(template, seeds[len(missing)]))
        example = load_json(example_path) if example_path.exists() else None
        return [saved[number] for number in sorted(saved)], example

    def algo_info(self, template: Template, cfg: dict) -> dict:
        meta, body = {}, ""
        source = ROOT / "content" / "algo" / f"{template.id}.md"
        if source.exists():
            meta, body = read_content(source)
        else:
            self.warnings.append(f"{template.id}: 解説の原稿 content/algo/{template.id}.md がありません")
        path = f"/algo/{template.id}/"
        snaps, example = self.frozen_problems(template, cfg)

        entries = [{"number": f"{snap['number']:02d}", "n": snap["number"], "snap": snap,
                    "path": f"/q/{template.id}/{snap['number']:02d}/", "call": snap["call"]}
                   for snap in snaps]
        indexed, extras = entries[:int(cfg["indexed"])], entries[int(cfg["indexed"]):]
        return {
            "template": template, "id": template.id, "title": template.title, "path": path,
            "level": template.level, "level_name": LEVEL_NAMES.get(template.level, str(template.level)),
            "tags": template.tags, "summary": meta.get("summary", template.description),
            "description": template.description, "body": body, "example": example,
            "problems": indexed, "extras": extras, "count": len(entries),
        }

    def build_algo(self, algo: dict, algos: list, min_weight: float) -> None:
        template = algo["template"]
        home = {"name": "トップ", "path": "/"}
        crumb = {"name": algo["title"], "path": algo["path"]}
        image = self.og_image(algo["id"], f"レベル：{algo['level_name']}",
                              f"{algo['title']}のトレース解説", algo["summary"])

        example = algo["example"] or {"call": "", "source": "", "questions": [],
                                      "trace": {"names": [], "rows": []}}
        self.render(
            "algo.html", algo["path"], title=f"{algo['title']}のトレース解説と練習問題",
            description=f"{algo['summary']} 考え方、トレースのコツ、よくある間違いと、"
                        f"値を変えた練習問題{algo['count']}問。全ステップのトレース表つき。",
            og_image=image, breadcrumbs=[home, crumb], algo=algo, body=algo["body"],
            example={"call": example["call"], "source_html": source_html(example["source"]),
                     "trace_html": trace_table_html(example["trace"]["names"], example["trace"]["rows"]),
                     "questions": example["questions"]},
            problems=algo["problems"], extras=algo["extras"],
            others=[a for a in algos if a["id"] != algo["id"]])

        everything = algo["problems"] + algo["extras"]
        for position, item in enumerate(everything):
            view = view_from_snapshot(item["snap"])
            if not view["questions"]:
                self.warnings.append(f"{algo['id']} 問題{item['number']}: 出せる設問がありません")
            indexed = position < len(algo["problems"])
            page_image = image
            if indexed:
                page_image = self.og_image(
                    f"{algo['id']}-{item['number']}", f"擬似言語トレース問題　レベル：{algo['level_name']}",
                    f"{algo['title']}　問題{item['number']}",
                    f"{view['problem']['call'] or ''} の動きを1行ずつ追う。"
                    f"設問{len(view['questions'])}つ・全ステップのトレース表つき")
            call = view["problem"]["call"] or ""
            self.render(
                "problem.html", item["path"], title=f"{algo['title']} 問題{item['number']}｜擬似言語トレース問題",
                description=f"{view['problem']['description']} {call} の動きを1行ずつ追う問題です。"
                            f"設問{len(view['questions'])}つ、全ステップのトレース表と解説つき。",
                og_image=page_image, noindex=not indexed,
                breadcrumbs=[home, crumb, {"name": f"問題{item['number']}", "path": item["path"]}],
                algo=algo, number=item["number"],
                prev_path=everything[position - 1]["path"] if position else None,
                next_path=everything[position + 1]["path"] if position + 1 < len(everything) else None,
                **view)

    def build_guides(self, image: str) -> list:
        home = {"name": "トップ", "path": "/"}
        index_crumb = {"name": "読み方ガイド", "path": "/guide/"}
        guides, index = [], None
        for source in sorted((ROOT / "content" / "guide").glob("*.md")):
            meta, body = read_content(source)
            entry = {"title": meta.get("title", source.stem), "description": meta.get("description", ""),
                     "order": meta.get("order", 99), "body": body,
                     "path": "/guide/" if source.stem == "index" else f"/guide/{source.stem}/"}
            if source.stem == "index":
                index = entry
            else:
                guides.append(entry)
        guides.sort(key=lambda g: g["order"])
        for guide in guides:
            self.render("page.html", guide["path"], title=guide["title"], description=guide["description"],
                        og_image=self.og_image(f"guide-{guide['path'].strip('/').split('/')[-1]}",
                                               "読み方ガイド", guide["title"], guide["description"]),
                        breadcrumbs=[home, index_crumb, {"name": guide["title"], "path": guide["path"]}],
                        body=guide["body"], children=[], show_contact=False)
        if index:
            self.render("page.html", "/guide/", title=index["title"], description=index["description"],
                        og_image=image, breadcrumbs=[home, index_crumb], body=index["body"],
                        children=guides, show_contact=False)
        return guides

    def build_simple(self, name: str, path: str, image: str, show_contact: bool) -> None:
        meta, body = read_content(ROOT / "content" / f"{name}.md")
        title = meta.get("title", name)
        self.render("page.html", path, title=title, description=meta.get("description", ""),
                    og_image=image, breadcrumbs=[{"name": "トップ", "path": "/"}, {"name": title, "path": path}],
                    body=body, children=[], show_contact=show_contact)

    def write_extras(self) -> None:
        site = self.site
        listed = sorted({p["path"] for p in self.pages if not p["noindex"]})
        urls = "\n".join(f"  <url><loc>{xml_escape(self.abs_url(path))}</loc></url>" for path in listed)
        (self.out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "\n</urlset>\n",
            encoding="utf-8")
        (self.out / "robots.txt").write_text(
            f"User-agent: *\nAllow: /\n\nSitemap: {self.abs_url('/sitemap.xml')}\n", encoding="utf-8")
        (self.out / ".nojekyll").write_text("", encoding="utf-8")
        if site["custom_domain"]:
            (self.out / "CNAME").write_text(site["custom_domain"].strip() + "\n", encoding="utf-8")

        if site["base_url"] == PLACEHOLDER_URL:
            self.warnings.append("site.yaml の base_url が仮の値（https://example.com）のままです。"
                                 "公開前に実際のドメインへ差し替えてください")
        if not (site["contact"]["form_url"] or site["contact"]["email"]):
            self.warnings.append("site.yaml の contact が空です。問い合わせ窓口は「準備中」と表示されます")
        if not site["analytics"]["cloudflare_token"]:
            self.warnings.append("site.yaml の analytics.cloudflare_token が空です。アクセス計測のタグは出力していません")

    def check_links(self) -> list[str]:
        """サイト内リンクの行き先が、すべて出力されているか確かめる。"""
        base = self.site["base_path"]
        broken = []
        for page in self.pages:
            for link in re.findall(r'(?:href|src)="([^"#?]+)', page["html"]):
                if not link.startswith(base + "/") or link.startswith("//"):
                    continue
                relative = link[len(base):].lstrip("/")
                target = self.out / relative
                if link.endswith("/"):
                    target = target / "index.html"
                if not target.exists():
                    broken.append(f"{page['path']} → {link}")
        return sorted(set(broken))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="静的サイトをビルドする")
    parser.add_argument("--config", default=str(ROOT / "site.yaml"))
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--problems", default=str(ROOT / "problems"),
                        help="生成した問題を保存して固定しておくフォルダ")
    parser.add_argument("--templates", default=str(ROOT / "templates" / "basic"))
    parser.add_argument("--frozen", action="store_true",
                        help="保存されていない問題があればエラーで止める（GitHub Actions 用）")
    parser.add_argument("--no-validate", action="store_true", help="テンプレートの検査を省く")
    parser.add_argument("--no-ogp", action="store_true", help="共有用の画像を作らない")
    args = parser.parse_args(argv)

    site = load_config(Path(args.config))
    template_dir = Path(args.templates)

    if not args.no_validate:
        failed = False
        for path in sorted(template_dir.rglob("*.yaml")):
            errors, _, summary = check_template(path, 60)
            if errors:
                failed = True
                print(f"[NG] {path.name}  {summary}")
                for message in errors:
                    print(f"    誤り: {message}")
        if failed:
            print("テンプレートに誤りがあるので、ビルドを中止しました")
            return 1

    templates = load_templates(template_dir)
    builder = Builder(site, Path(args.out), Path(args.problems), make_ogp=not args.no_ogp,
                      frozen=args.frozen)
    builder.build(templates)

    if builder.unsaved:
        print("エラー: problems/ に保存されていない問題があります。")
        for item in builder.unsaved:
            print(f"  - {item}")
        print("ここで作った問題はリポジトリに保存されず、固定されません。")
        print("手元で python build.py を実行し、problems/ をコミットしてください。")
        return 1

    broken = builder.check_links()
    indexed = sum(1 for p in builder.pages if not p["noindex"])
    print(f"{len(builder.pages)} ページを {args.out} に出力しました（検索対象 {indexed}、対象外 {len(builder.pages) - indexed}）")
    print(f"新しく作って保存した問題: {builder.created} 問（保存先 {args.problems}）")
    for message in builder.warnings:
        print(f"注意: {message}")
    for message in broken:
        print(f"リンク切れ: {message}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
