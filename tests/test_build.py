"""静的サイトのビルドの通しテスト（問題数を減らし、共有用画像は作らない）。"""
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

pytest.importorskip("jinja2")
pytest.importorskip("markdown")

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def run_build(tmp_path, templates=None, extra_args=(), **overrides):
    config = {"name": "テストサイト", "exam_label": "科目B", "tagline": "説明",
              "base_url": "https://drill.example", "custom_domain": "drill.example",
              "problems": {"indexed": 2, "extra": 1, "candidates": 40, "min_weight": 0.5}}
    config.update(overrides)
    (tmp_path / "site.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    args = ["--config", str(tmp_path / "site.yaml"), "--out", str(tmp_path / "dist"),
            "--problems", str(tmp_path / "problems"), "--no-ogp", "--no-validate"]
    if templates:
        args += ["--templates", str(templates)]
    args += list(extra_args)
    code = build.main(args)
    return code, tmp_path / "dist"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    code, dist = run_build(tmp_path_factory.mktemp("site"))
    assert code == 0                      # リンク切れがあると 1 になる
    return dist


def test_every_kind_of_page_is_written(site):
    for path in ("index.html", "404.html", "about/index.html", "for-teams/index.html",
                 "guide/index.html", "guide/trace-table/index.html", "algo/loop-sum-001/index.html",
                 "q/loop-sum-001/01/index.html", "q/loop-sum-001/03/index.html",
                 "sitemap.xml", "robots.txt", "static/app.js", "static/style.css", ".nojekyll"):
        assert (site / path).exists(), path
    assert (site / "CNAME").read_text().strip() == "drill.example"


def test_problem_page_has_title_description_ogp_and_numbered_program(site):
    page = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    # 解説ページと同じく、検索で使われる呼び名を先頭に置く。「基本情報 科目B」は1回だけ（サイト名の後ろには重ねない）
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert re.fullmatch(r".+の擬似言語トレース 練習問題01｜基本情報 科目B｜テストサイト", title), title
    assert '<h1>条件に合う要素の合計　問題01</h1>' in page                 # ページの中の見出しは変えていない
    description = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
    assert description.startswith("基本情報技術者試験 科目Bの擬似言語「") and "練習問題01" in description[:60]
    assert '<link rel="canonical" href="https://drill.example/q/loop-sum-001/01/">' in page
    assert 'property="og:image" content="https://drill.example/ogp/loop-sum-001-01.png"' in page
    assert 'name="twitter:card" content="summary_large_image"' in page
    assert re.search(r'<meta name="description" content="[^"]{40,}">', page)
    assert '<td class="no">1</td>' in page and 'class="giji-trace"' in page
    assert "noindex" not in page


def test_quiz_data_matches_the_questions_on_the_page(site):
    page = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    quiz = json.loads(re.search(r'id="quiz-data">(.*?)</script>', page, re.S).group(1))
    assert len(quiz["practice"]) == page.count('data-kind="practice"')
    assert all(q["answer"] in "アイウエ" for q in quiz["practice"])
    # 奇数番は空欄補充を出し、戻り値の設問は出さない（問題文が戻り値を明かすため）
    kinds = [q["type"] for q in quiz["practice"]]
    assert kinds[0] == "fill_blank" and "return_value" not in kinds
    even = (site / "q/loop-sum-001/02/index.html").read_text(encoding="utf-8")
    even_kinds = [q["type"] for q in json.loads(
        re.search(r'id="quiz-data">(.*?)</script>', even, re.S).group(1))["practice"]]
    assert "return_value" in even_kinds and "fill_blank" not in even_kinds


def test_extra_problems_are_noindex_and_left_out_of_sitemap(site):
    extra = (site / "q/loop-sum-001/03/index.html").read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex,follow">' in extra
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://drill.example/q/loop-sum-001/01/" in sitemap
    assert "https://drill.example/q/loop-sum-001/03/" not in sitemap
    assert "https://drill.example/algo/loop-sum-001/" in sitemap
    assert "404" not in sitemap
    assert "Sitemap: https://drill.example/sitemap.xml" in (site / "robots.txt").read_text()


def test_algorithm_page_has_guide_text_example_trace_and_problem_links(site):
    page = (site / "algo/while-gcd-001/index.html").read_text(encoding="utf-8")
    assert "トレースのコツ" in page and "よくある間違い" in page
    assert 'class="giji-trace"' in page
    assert page.count('href="/q/while-gcd-001/') == 3


def test_published_problems_do_not_change_when_the_template_is_edited(tmp_path):
    import shutil
    templates = tmp_path / "templates"
    shutil.copytree(ROOT / "templates" / "basic", templates)
    _, dist = run_build(tmp_path, templates=templates)
    page = "q/loop-sum-001/01/index.html"
    before = (dist / page).read_text(encoding="utf-8")
    saved = tmp_path / "problems" / "loop-sum-001" / "01.json"
    saved_before = saved.read_text(encoding="utf-8")
    assert json.loads(saved_before)["trace"]["rows"]            # トレースまで保存してある

    # 公開後にテンプレートを直す：説明文と誤答を変える
    path = templates / "loop-sum-001.yaml"
    text = path.read_text(encoding="utf-8")
    text = text.replace("k の倍数だけを合計して返す", "k で割り切れる要素の和を返す")
    text = text.replace('      - "i mod k ＝ 0"\n', '      - "i mod k ＝ 1"\n')
    path.write_text(text, encoding="utf-8")

    _, dist = run_build(tmp_path, templates=templates,
                        problems={"indexed": 3, "extra": 1, "candidates": 40, "min_weight": 0.5})
    assert (dist / page).read_text(encoding="utf-8") == before   # 既存のページは1文字も変わらない
    assert saved.read_text(encoding="utf-8") == saved_before
    newest = (dist / "q/loop-sum-001/04/index.html").read_text(encoding="utf-8")
    assert "k で割り切れる要素の和を返す" in newest             # 新しい問題には反映される
    assert "k で割り切れる要素の和を返す" not in before


def test_new_problems_avoid_repeating_saved_ones(tmp_path):
    run_build(tmp_path)
    run_build(tmp_path, problems={"indexed": 4, "extra": 2, "candidates": 60, "min_weight": 0.5})
    folder = tmp_path / "problems" / "while-gcd-001"
    calls = [json.loads(p.read_text(encoding="utf-8"))["call"] for p in sorted(folder.glob("0*.json"))]
    assert len(calls) == 6 and len(set(calls)) == 6


def test_analytics_and_contact_come_from_settings(tmp_path):
    _, dist = run_build(tmp_path, analytics={"cloudflare_token": "tok123"},
                        contact={"form_url": "https://forms.example/abc", "email": ""})
    about = (dist / "about/index.html").read_text(encoding="utf-8")
    assert "static.cloudflareinsights.com/beacon.min.js" in about and "tok123" in about
    assert 'href="https://forms.example/abc"' in about and "mailto:" not in about


def test_share_image_is_1200_by_630(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    font = ROOT / "site" / "fonts" / "NotoSansJP-Bold.otf"
    if not font.exists():
        pytest.skip("フォントがない")
    build.draw_card(tmp_path / "card.png", font, "サイト名", "問題01", "最大公約数（互除法）", "設問の文")
    assert Image.open(tmp_path / "card.png").size == (1200, 630)


def test_problem_page_offers_exam_format_without_line_numbers(site):
    page = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    quiz = json.loads(re.search(r'id="quiz-data">(.*?)</script>', page, re.S).group(1))
    assert quiz["exam"]["answer"] in "アイウエオカ"
    exam = page.split('id="mode-exam"')[1].split('class="review"')[0]
    assert 'data-mode="exam"' in page and "本番形式" in page
    assert "解答群の中から選べ。" in exam and "，" in exam
    assert 'class="giji-code plain"' in exam and 'class="no"' not in exam
    assert 4 <= exam.count('name="exam"') <= 6


def test_blank_is_filled_in_place_instead_of_swapping_programs(site):
    page = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    practice = page.split('id="mode-practice"')[1].split('data-kind="practice"')[0]
    assert practice.count('class="program"') == 1
    assert 'class="blank" data-blank="ａ"' in practice
    assert "program-blank" not in page and "program-full" not in page


def test_frozen_build_stops_when_a_problem_is_not_saved(tmp_path, capsys):
    # 保存済みの問題が1つもない状態で --frozen：止まり、何も保存しない
    code, _ = run_build(tmp_path, extra_args=["--frozen"])
    out = capsys.readouterr().out
    assert code == 1
    assert "手元で python build.py を実行し、problems/ をコミットしてください。" in out
    assert not (tmp_path / "problems").exists()

    # 手元でビルドして保存したあとなら、--frozen でも通る
    assert run_build(tmp_path)[0] == 0
    assert run_build(tmp_path, extra_args=["--frozen"])[0] == 0

    # 問題数を増やしたのに保存していない場合も止まり、どのテンプレートかを示す
    code, _ = run_build(tmp_path, extra_args=["--frozen"],
                        problems={"indexed": 3, "extra": 1, "candidates": 40, "min_weight": 0.5})
    out = capsys.readouterr().out
    assert code == 1 and "loop-sum-001: 問題04（1問）" in out
    assert not (tmp_path / "problems" / "loop-sum-001" / "04.json").exists()


def snapshot_bytes(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*.json"))}


def test_only_the_missing_number_is_generated_and_nothing_else_is_rewritten(tmp_path, capsys):
    import shutil
    templates = tmp_path / "templates"
    shutil.copytree(ROOT / "templates" / "basic", templates)
    sizes = {"indexed": 4, "extra": 2, "candidates": 60, "min_weight": 0.5}
    assert run_build(tmp_path, templates=templates, problems=sizes)[0] == 0
    store = tmp_path / "problems"
    before = snapshot_bytes(store)
    assert len([k for k in before if k.startswith("loop-sum-001/0")]) == 6

    # テンプレートの解説を書き換え、途中の1問（03）だけを消す
    path = templates / "loop-sum-001.yaml"
    text = path.read_text(encoding="utf-8")
    assert "真になった要素だけを sum に足していくので" in text
    path.write_text(text.replace("真になった要素だけを sum に足していくので", "【書き換えた解説】なので"),
                    encoding="utf-8")
    (store / "loop-sum-001" / "03.json").unlink()

    # --frozen は、実際に存在しない番号だけを不足として示す
    capsys.readouterr()
    assert run_build(tmp_path, templates=templates, problems=sizes, extra_args=["--frozen"])[0] == 1
    out = capsys.readouterr().out
    assert "loop-sum-001: 問題03（1問）" in out
    assert "04" not in out.split("loop-sum-001: 問題")[1].split("\n")[0]
    assert not (store / "loop-sum-001" / "03.json").exists()

    # ふつうのビルドは、03 だけを作る
    assert run_build(tmp_path, templates=templates, problems=sizes)[0] == 0
    out = capsys.readouterr().out
    assert "新しく作って保存した問題: 1 問" in out
    after = snapshot_bytes(store)
    assert set(after) == set(before)
    changed = [name for name in before if after[name] != before[name]]
    assert changed == ["loop-sum-001/03.json"]         # ほかの JSON は1バイトも変わらない

    # 作り直した 03 だけが新しい解説になり、番号も 03 のまま。保存済みの問題とも重ならない
    rebuilt = json.loads(after["loop-sum-001/03.json"])
    assert rebuilt["number"] == 3 and "【書き換えた解説】" in rebuilt["explanation"]
    others = [json.loads(after[f"loop-sum-001/{n:02d}.json"]) for n in (1, 2, 4, 5, 6)]
    assert all("【書き換えた解説】" not in snap["explanation"] for snap in others)
    assert (rebuilt["source"], rebuilt["call"]) not in {(s["source"], s["call"]) for s in others}


def test_several_gaps_are_filled_in_place(tmp_path, capsys):
    sizes = {"indexed": 4, "extra": 3, "candidates": 60, "min_weight": 0.5}
    run_build(tmp_path, problems=sizes)
    store = tmp_path / "problems"
    folder = store / "while-gcd-001"
    for name in ("02.json", "05.json", "06.json", "example.json"):
        (folder / name).unlink()
    before = snapshot_bytes(store)

    capsys.readouterr()
    assert run_build(tmp_path, problems=sizes, extra_args=["--frozen"])[0] == 1
    out = capsys.readouterr().out
    assert "while-gcd-001: 問題02, 05〜06（3問）" in out and "while-gcd-001: 解説ページの例題" in out

    assert run_build(tmp_path, problems=sizes)[0] == 0
    after = snapshot_bytes(store)
    assert all(after[name] == data for name, data in before.items())
    assert sorted(set(after) - set(before)) == [f"while-gcd-001/{n}" for n in
                                               ("02.json", "05.json", "06.json", "example.json")]
    assert [json.loads(after[f"while-gcd-001/{n:02d}.json"])["number"] for n in (2, 5, 6)] == [2, 5, 6]


def test_saving_refuses_to_overwrite_an_existing_file(tmp_path):
    target = tmp_path / "01.json"
    build.save_new_json(target, {"a": 1})
    with pytest.raises(FileExistsError):
        build.save_new_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_home_shows_one_problem_first_and_keeps_a_short_description(site):
    page = (site / "index.html").read_text(encoding="utf-8")
    first_screen, rest = page.split('class="level-entry"')
    assert 'id="daily-body"' in first_screen and 'class="giji-code"' in first_screen
    assert first_screen.count('name="daily"') == 4 and "解答する" in first_screen
    # 「今日の1問」は説明文の中ではなく、問題の枠のすぐ上の独立した見出し
    assert re.search(r'<h2 class="daily-title" id="daily-label" data-kaomoji="daily">今日の1問</h2>\s*<div class="question" id="daily-body">', first_screen)
    assert "今日の1問" not in first_screen.split('class="daily-lead"')[1].split("</p>")[0]
    assert "このサイトについて" in rest and "トレース" in rest            # 説明文は最初の画面の下に残す
    daily = json.loads(re.search(r'id="daily-data">(.*?)</script>', page, re.S).group(1))
    assert len(daily) >= 7                                             # 日替わりにできるだけの数がある
    assert all(item["answer"] in "アイウエ" and len(item["choices"]) == 4 for item in daily)
    assert all((site / item["path"].strip("/") / "index.html").exists() for item in daily)
    titles = [item["title"] for item in daily]
    assert all(a != b for a, b in zip(titles, titles[1:]))             # 同じアルゴリズムが続かない


def test_daily_problems_are_short_beginner_standard_ones(site):
    page = (site / "index.html").read_text(encoding="utf-8")
    daily = json.loads(re.search(r'id="daily-data">(.*?)</script>', page, re.S).group(1))
    for item in daily:
        assert item["level"] == "入門"
        assert item["source_html"].count("<tr") <= 9


def test_hints_come_before_the_questions_and_do_not_reach_the_asked_step(site):
    page = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    hints = page.split('class="hints"')[1].split('data-kind="practice"')[0]
    assert "ヒント1：トレース表の枠を見る" in hints
    quiz = json.loads(re.search(r'id="quiz-data">(.*?)</script>', page, re.S).group(1))
    asked = [q["step"] for q in quiz["practice"] if q.get("step")]
    shown = [int(n) for n in re.findall(r'data-step="(\d+)"', hints)]
    if "ヒント2" in hints:
        assert shown and (not asked or max(shown) < min(asked))


def test_standard_and_long_sets_share_one_explanation_page(site):
    algo = (site / "algo/loop-sum-001/index.html").read_text(encoding="utf-8")
    assert 'id="standard"' in algo and 'id="long"' in algo
    assert algo.index('id="standard"') < algo.index('id="long"')       # 標準を先に並べる
    assert 'href="/q/loop-sum-002/01/"' in algo and 'href="/q/loop-sum-001/01/"' in algo
    assert not (site / "algo/loop-sum-002").exists()                   # 解説ページは増やさない

    added = (site / "q/loop-sum-002/01/index.html").read_text(encoding="utf-8")
    old = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    # 追加した版だけ「（標準）」が付く。元からあるページには付けない（2026-11-16 に、題名の形そのものは検索向けに変えた）
    assert re.search(r"<title>[^<]+の擬似言語トレース 練習問題01（標準）｜基本情報 科目B｜", added)
    assert re.search(r"<title>[^<（]+の擬似言語トレース 練習問題01｜基本情報 科目B｜", old)
    assert "<h1>条件に合う要素の合計（標準）　問題01</h1>" in added and "<h1>条件に合う要素の合計　問題01</h1>" in old
    assert 'class="badge pace-standard">標準' in added and 'class="badge pace-long">じっくり' in old
    assert 'href="/algo/loop-sum-001/#standard"' in added


def test_levels_use_the_new_names_and_assignments(site):
    home = (site / "index.html").read_text(encoding="utf-8")
    assert "本試験相当" not in home
    beginner = home.split('id="level-1"')[1].split('id="level-2"')[0]
    middle = home.split('id="level-3"')[1].split("このサイトについて")[0]
    assert "再帰呼出しの戻り値" in beginner
    assert "二次元配列の行ごとの合計" in middle and "同じ文字が続く最長の長さ" in middle


def test_member_pages_are_built_from_prepared_files_only(site):
    """会員ページとサンプル模試：ビルドは site/members/ を配るだけで、private/ を読まない。"""
    members_dir = ROOT / "site" / "members"
    if not (members_dir / "sample.json").exists():
        pytest.skip("site/members/ がまだありません")
    sample = (site / "mock" / "sample" / "index.html").read_text(encoding="utf-8")
    page = (site / "members" / "index.html").read_text(encoding="utf-8")
    for html in (sample, page):
        assert 'id="members-app"' in html and "/static/member.js" in html and "/static/mock.js" in html
    assert 'data-sample="/members/sample.json"' in sample and "noindex" not in sample
    assert "月額980円" in page
    # 配るのは、暗号化済みのファイルと目次・鍵束・サンプルだけ
    copied = sorted(str(p.relative_to(site / "members")) for p in (site / "members").rglob("*.json"))
    expected = sorted(str(p.relative_to(members_dir)) for p in members_dir.rglob("*.json"))
    assert copied == expected
    for path in (site / "members" / "data").glob("*.json"):
        box = json.loads(path.read_text(encoding="utf-8"))
        assert set(box) == {"v", "alg", "iv", "ct"}          # 中身は読めない形
    # 先行公開中のテンプレートの問題ページは、公開サイトのどこにもない
    private_templates = ROOT / "private" / "templates"
    if private_templates.exists():
        for template in private_templates.glob("*.yaml"):
            assert not (site / "algo" / template.stem).exists() and not (site / "q" / template.stem).exists()
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert "/mock/sample/" in sitemap and "/members/" in sitemap
    assert "無料サンプル模試" in (site / "index.html").read_text(encoding="utf-8")


def test_kaomoji_only_in_the_agreed_places(site):
    """顔文字：1ファイルにまとめ、決めた場所だけに出す。問題文・本番形式・会員ページには出さない。"""
    source = (ROOT / "site" / "static" / "kaomoji.js").read_text(encoding="utf-8")
    faces = re.findall(r"'([^']+)'", source[source.index("var FACES"):source.index("var WORDS")])
    assert 8 <= len(set(faces)) <= 12

    # 顔文字そのものは kaomoji.js にしかない（HTML・ほかの JS・問題データには書かれていない）
    for path in list(site.rglob("*.html")) + list(site.rglob("*.json")) + list((site / "static").glob("*.js")):
        if path.name == "kaomoji.js":
            continue
        text = path.read_text(encoding="utf-8")
        assert not any(face in text for face in faces), path

    home = (site / "index.html").read_text(encoding="utf-8")
    assert 'class="daily-lead" data-kaomoji="lead"' in home and "/static/kaomoji.js" in home
    assert sorted(set(re.findall(r'data-kaomoji="(\w+)"', home))) == ["daily", "lead"]

    problem = next(p for p in sorted((site / "q").rglob("index.html")))
    html = problem.read_text(encoding="utf-8")
    practice, exam = html.split('id="mode-exam"')
    assert practice.count('<summary data-kaomoji="hint">') >= 1
    assert "data-kaomoji" not in exam                      # 本番形式には目印がない
    assert set(re.findall(r'data-kaomoji="(\w+)"', html)) == {"hint"}

    members = site / "members" / "index.html"
    if members.exists():
        assert "kaomoji.js" not in members.read_text(encoding="utf-8")     # 会員ページは読み込まない
        assert "kaomoji.js" in (site / "mock" / "sample" / "index.html").read_text(encoding="utf-8")

    script = (ROOT / "site" / "static" / "app.js").read_text(encoding="utf-8")
    assert "grade(examSection, quiz.exam.answer, false)" in script   # 本番形式の答え合わせは元の文言のまま


def test_algorithm_pages_use_search_names_and_link_to_related_pages(site):
    """解説ページ：検索で使われる呼び名をタイトルと見出しに入れ、関連する題材・ガイド・模試へつなぐ。"""
    page = (site / "algo/stack-basic-001/index.html").read_text(encoding="utf-8")
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert title.startswith("スタックの擬似言語をトレースで解説｜練習問題") and "基本情報 科目B" in title
    description = re.search(r'<meta name="description" content="(.*?)">', page).group(1)
    assert "擬似言語「スタック」" in description and "全ステップのトレース表つき" in description
    assert '<h2 id="program">スタックのプログラム（擬似言語）</h2>' in page
    assert '<h2 id="example">例題のトレース表' in page

    related = page.split("関連するアルゴリズム")[1].split("読み方に迷ったら")[0]
    links = re.findall(r'href="(/algo/[^"]+/)"', related)
    assert len(links) == 3 and "/algo/stack-basic-001/" not in links
    guides = page.split("読み方に迷ったら")[1].split("すべてのアルゴリズム")[0]
    assert "/guide/trace-table/" in guides and "/guide/notation/" in guides and "/guide/arrays/" in guides
    assert "/mock/sample/" in guides

    # 題名しかない題材（topic がない）でも壊れない。問題ページからも関連へ進める
    problem = next(iter(sorted((site / "q" / "stack-basic-001").rglob("index.html")))).read_text(encoding="utf-8")
    block = problem.split('class="note related-links"')[1].split("</p>")[0]
    assert block.count("/algo/") == 3 and "/guide/notation/" in block


def test_every_algorithm_has_a_search_name():
    for path in sorted((ROOT / "content" / "algo").glob("*.md")):
        assert re.search(r"^topic: \S", path.read_text(encoding="utf-8"), re.M), path.name


def test_notation_cheat_sheet_uses_confirmed_notation_only(site):
    page = (site / "guide/notation/index.html").read_text(encoding="utf-8")
    for text in ("擬似言語の書き方 早見表", "繰返し処理を終了する", "未定義の値", "の末尾 に", "大域:", "endwhile"):
        assert text in page, text
    assert "<table>" in page
    # IPA の公開問題で確認できなかった書き方は、サイトのどの原稿にも書かない
    for source in list((ROOT / "content").rglob("*.md")) + list((ROOT / "templates").rglob("*.yaml")):
        assert "未定義でない" not in source.read_text(encoding="utf-8"), source
    assert "/guide/notation/" in (site / "guide/index.html").read_text(encoding="utf-8")


def test_mock_steps_are_counted_through_addresses_with_landing_pages(site):
    """模試の開始・採点の計測：アドレスを切り替えて数える。切り替え先には、元へ戻すだけのページがある。"""
    if not (ROOT / "site" / "members" / "sample.json").exists():
        pytest.skip("site/members/ がまだありません")
    for parent in ("mock/sample", "members"):
        for step in ("started", "graded"):
            html = (site / parent / step / "index.html").read_text(encoding="utf-8")
            assert 'content="noindex"' in html and f'url=/{parent}/"' in html
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert "started" not in sitemap and "graded" not in sitemap
    sample = (site / "mock/sample/index.html").read_text(encoding="utf-8")
    assert 'data-step-base="/mock/sample/"' in sample and 'data-algo-base="/algo/"' in sample
    script = (ROOT / "site" / "static" / "mock.js").read_text(encoding="utf-8")
    assert "countStep('started')" in script and "countStep('graded')" in script


def test_member_page_shows_what_members_get_now_and_counts_join_clicks(site):
    """会員ページ：いま解ける回数と、無料と会員の比較表。入会ボタンを押した回数も数える。"""
    members_dir = ROOT / "site" / "members"
    if not (members_dir / "index.json").exists():
        pytest.skip("site/members/ がまだありません")
    kinds = [b["kind"] for b in json.loads((members_dir / "index.json").read_text(encoding="utf-8"))["bundles"]]
    page = (site / "members" / "index.html").read_text(encoding="utf-8")
    assert f"模試 {kinds.count('mock')}回分（{kinds.count('mock') * 16}問）" in page
    table = page.split('<table class="compare">')[1].split("</table>")[0]
    assert table.count("<tr>") == 7 and "月額980円" in table and f"いま{kinds.count('mock')}回分" in table
    shown = re.search(r"練習問題（(\d+)題材・(\d+)問）", table)        # 題材数と問題数は、ビルドした実際の数から出す
    assert shown and int(shown.group(1)) == len(list((site / "algo").iterdir())) and int(shown.group(2)) > 0
    assert "kaomoji" not in page and "data-kaomoji" not in page        # 会員ページに顔文字は出さない

    join = (site / "members" / "join" / "index.html").read_text(encoding="utf-8")
    assert 'content="noindex"' in join and 'url=/members/"' in join
    assert "join" not in (site / "sitemap.xml").read_text(encoding="utf-8")
    script = (ROOT / "site" / "static" / "mock.js").read_text(encoding="utf-8")
    assert "countStep('join')" in script and "target: '_blank'" in script


def test_entry_pages_put_the_next_action_first(site):
    """入口のページ：次にすること（解く・始める・入会する）を、説明より前に置く。"""
    algo = (site / "algo/binary-search-001/index.html").read_text(encoding="utf-8")
    cta = algo.index('class="page-cta"')
    assert 'href="/q/binary-search-001/01/">練習問題を解く' in algo[cta:cta + 300]
    assert cta < algo.index('id="program"')                         # プログラムや解説より前
    header = algo.split('<header class="site-header">')[1].split("</header>")[0]
    assert header.count("<a ") <= 5 and 'class="skip-link" href="#main"' in algo and '<main id="main">' in algo

    problem = next(iter(sorted((site / "q" / "binary-search-001").rglob("index.html")))).read_text(encoding="utf-8")
    if (ROOT / "site" / "members" / "sample.json").exists():
        assert 'class="mock-cta"' in problem and "/mock/sample/" in problem.split('class="mock-cta"')[1][:200]
        sample = (site / "mock/sample/index.html").read_text(encoding="utf-8")
        assert sample.index('id="mock-app"') < sample.index("この模試について")     # 始めるボタンの枠が、説明より前
        assert sample.count("data-hide-on-start") == 3
        home = (site / "index.html").read_text(encoding="utf-8")
        assert home.index('class="home-mock"') < home.index('id="algorithms"')      # 模試の案内は、長い一覧より前
        assert 'href="/members/">会員</a>' in header
    script = (ROOT / "site" / "static" / "mock.js").read_text(encoding="utf-8")
    for needle in ("mock-progress:", "続きから再開する", "未解答：", "summary.focus("):
        assert needle in script, needle


def test_combination_table_rows_are_clickable_in_both_scripts():
    """組合せ表：行のどこを押しても選べる処理が、問題ページ（app.js）と模試（mock.js）の両方にある。"""
    for name, hook in (("app.js", "document.addEventListener('click', pickComboRow)"),
                       ("mock.js", "paper.addEventListener('click', pickComboRow)")):
        script = (ROOT / "site" / "static" / name).read_text(encoding="utf-8")
        assert "function pickComboRow(event)" in script and hook in script, name
        assert "closest('input, label, a')" in script          # 丸・ラベルを直接押したときは、ブラウザの動きのまま
        assert "new Event('change', { bubbles: true })" in script


def test_home_lists_algorithms_in_collapsed_groups_that_keep_their_links(site):
    page = (site / "index.html").read_text(encoding="utf-8")
    groups = re.findall(r'<details class="level-group" id="level-(\d+)">\s*<summary><h3>(.+?)</h3>'
                        r'<span class="level-count">(\d+)種類</span></summary>(.*?)</details>', page, re.S)
    assert len(groups) >= 3 and [name for _, name, _, _ in groups][:3] == ["入門", "基礎", "中級"]
    assert "<details class=\"level-group\" open" not in page and " open>" not in page   # 最初はすべて閉じている
    for level, _, count, body in groups:
        links = re.findall(r'<li data-progress-set="[a-z0-9-]+" data-progress-total="\d+"><a href="([^"]+)">', body)
        assert len(links) == int(count) > 0                              # 見出しの数と中身が合う。閉じていても HTML に残る
        assert f'href="#level-{level}"' in page                          # 上の入口のリンクの行き先がある
    listed = sum(int(count) for _, _, count, _ in groups)
    section = page.split('id="algorithms"')[1].split("</section>")[0]
    assert listed == section.count('<li data-progress-set=')                        # 分類の外に置き去りの題材がない
    # 一覧より上の順番は変えない：今日の1問 → レベルの入口 → 模試の案内 → 一覧
    order = [page.index(mark) for mark in ('id="daily"', 'class="level-entry"', 'id="algorithms"')]
    assert order == sorted(order)


# ---- 会員の確認方法（A案＝合言葉、B案＝サイトで入会）の切り替え ----

def _members_page(tmp_path, monkeypatch, members, legal=True):
    if not (ROOT / "site" / "members" / "index.json").exists():
        pytest.skip("site/members/ がまだありません")
    simple = tmp_path / "content"
    simple.mkdir()
    for name in ("about.md", "for-teams.md"):
        (simple / name).write_text((ROOT / "content" / name).read_text(encoding="utf-8"), encoding="utf-8")
    if legal:
        for name in ("tokushoho.md", "privacy.md"):
            (simple / name).write_text((ROOT / "drafts" / "legal" / name).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(build, "SIMPLE_DIR", simple)
    code, dist = run_build(tmp_path, members=members)
    assert code == 0
    return dist, (dist / "members" / "index.html").read_text(encoding="utf-8")


def test_default_member_page_is_the_passphrase_one_and_has_no_trace_of_plan_b(site):
    page = site / "members" / "index.html"
    if not page.exists():
        pytest.skip("site/members/ がまだありません")
    html = page.read_text(encoding="utf-8")
    assert "/static/member.js" in html and "member-b.js" not in html and "data-member-api" not in html
    assert "合言葉" in html and "Stripe" not in html
    home = (site / "index.html").read_text(encoding="utf-8")
    assert "/tokushoho/" not in home and "/privacy/" not in home            # 下書きのうちは、リンクもページも出ない
    assert not (site / "tokushoho").exists() and not (site / "privacy").exists()
    assert (site / "static" / "member-b.js").exists()                       # ファイルは置いてあるが、どのページも読み込まない
    assert not [p for p in site.rglob("*.html") if "member-b.js" in p.read_text(encoding="utf-8")]


def test_both_mode_loads_passphrase_and_plan_b_side_by_side(tmp_path, monkeypatch):
    dist, html = _members_page(tmp_path, monkeypatch,
                               {"note_url": "https://note.com/x/membership", "price": 980, "method": "both",
                                "api_url": "https://api.drill.example/"})
    assert html.index("/static/member.js") < html.index("/static/member-b.js") < html.index("/static/mock.js")
    assert 'data-member-api="https://api.drill.example"' in html and 'data-price="980"' in html
    assert "サイトで入会する" in html and "今月の合言葉" in html                    # 両方の案内が出る
    assert 'href="/tokushoho/"' in html and 'href="/privacy/"' in html
    assert "kaomoji.js" not in html
    for name, title in (("tokushoho", "特定商取引法に基づく表記"), ("privacy", "プライバシーポリシー")):
        assert f"<h1>{title}</h1>" in (dist / name / "index.html").read_text(encoding="utf-8")
    assert "/tokushoho/" in (dist / "index.html").read_text(encoding="utf-8")       # フッターからも行ける
    assert "/tokushoho/" in (dist / "sitemap.xml").read_text(encoding="utf-8")


def test_stripe_mode_drops_the_passphrase_module(tmp_path, monkeypatch):
    _, html = _members_page(tmp_path, monkeypatch, {"price": 980, "method": "stripe", "api_url": "https://api.drill.example"})
    assert "/static/member.js" not in html and "/static/member-b.js" in html
    assert "サイトで入会する" in html and "今月の合言葉" not in html and "note で会員になる" not in html


def test_plan_b_cannot_be_switched_on_without_api_url_or_legal_pages(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="api_url"):
        _members_page(tmp_path / "a", monkeypatch, {"method": "stripe", "api_url": ""}) if (tmp_path / "a").mkdir() is None else None
    with pytest.raises(SystemExit, match="tokushoho.md"):
        _members_page(tmp_path / "b", monkeypatch, {"method": "both", "api_url": "https://api.drill.example"}, legal=False) \
            if (tmp_path / "b").mkdir() is None else None
    with pytest.raises(SystemExit, match="members.method"):
        _members_page(tmp_path / "c", monkeypatch, {"method": "paypal"}) if (tmp_path / "c").mkdir() is None else None


def test_problem_page_titles_are_unique_and_match_the_algo_page_wording(site):
    titles = {}
    for page in sorted((site / "q").glob("*/*/index.html")):
        title = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8")).group(1)
        assert title not in titles, f"{page} と {titles.get(title)} の題名が同じ: {title}"
        titles[title] = page
        assert re.fullmatch(r".+の擬似言語トレース 練習問題\d{2}(（標準）|（じっくり）)?｜基本情報 科目B｜[^｜]+", title), title
    algo = (site / "algo" / "loop-sum-001" / "index.html").read_text(encoding="utf-8")
    topic = re.search(r"<title>(.+?)の擬似言語をトレースで解説", algo).group(1)
    first = re.search(r"<title>(.*?)</title>", (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")).group(1)
    assert first.startswith(topic + "の擬似言語トレース 練習問題01")


def test_learning_record_hooks_line_tip_and_share_row_are_in_the_pages(site):
    home = (site / "index.html").read_text(encoding="utf-8")
    algo = (site / "algo" / "loop-sum-001" / "index.html").read_text(encoding="utf-8")
    problem = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    for page in (home, algo, problem):
        assert page.index("/static/progress.js") < page.index("/static/app.js")
    assert 'id="progress-box" data-progress-scope="" hidden' in home
    assert re.search(r'<li data-progress-set="loop-sum-001" data-progress-total="\d+">', home)
    assert re.search(r'id="progress-box" data-progress-scope="[^"]*loop-sum-001/ [^"]*" hidden', algo)
    assert 'data-problem-id="loop-sum-001/01"' in problem and 'id="review-bar" hidden' in problem
    assert 'id="share-row" hidden' in problem and problem.count('class="note line-tip"') >= 1
    # 共有は、押したときにだけ開くリンク。ページに X のスクリプトや自動投稿は入れない
    for page in (home, algo, problem):
        assert "platform.twitter.com" not in page and "twitter.com/intent" not in page
    app = (ROOT / "site" / "static" / "app.js").read_text(encoding="utf-8")
    assert "https://twitter.com/intent/tweet?text=" in app and "noopener" in app
    # 会員ページの模試には共有を出さない（共有の指定は、無料サンプルの呼び出しにだけある）
    mock = (ROOT / "site" / "static" / "mock.js").read_text(encoding="utf-8")
    assert mock.count("share:") == 1 and "play(bundle, null)" in mock
    assert mock.index("function samplePage") < mock.index("share:")


def test_problem_page_is_ready_for_two_columns_step_trace_and_answer_time(site):
    problem = (site / "q/loop-sum-001/01/index.html").read_text(encoding="utf-8")
    home = (site / "index.html").read_text(encoding="utf-8")
    algo = (site / "algo" / "loop-sum-001" / "index.html").read_text(encoding="utf-8")
    # 2列にするのは問題ページだけ（広い画面で、左にプログラム・右に設問）
    assert '<main id="main" class="wide">' in problem and '<main id="main">' in home and '<main id="main">' in algo
    practice = problem[problem.index('id="mode-practice"'):problem.index("</section>\n\n", problem.index('id="mode-practice"'))]
    assert practice.index('<div class="two-col">') < practice.index('<div class="col-program">') \
        < practice.index('<div class="program">') < practice.index('<div class="col-questions">') \
        < practice.index('<div class="hints">') < practice.index('data-kind="practice"')
    assert problem.count('<div class="two-col">') == problem.count('<div class="col-program">') == problem.count('<div class="col-questions">')
    style = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".two-col, .col-program, .col-questions { display: contents; }" in style      # 狭い画面では今までどおり1列
    wide = style[style.index("@media (min-width: 64rem)"):]
    assert ".problem.js .two-col { display: grid;" in wide and "position: sticky" in wide
    # 1ステップずつ表示と解答時間は、表の HTML を変えずに画面側で行う
    app = (ROOT / "site" / "static" / "app.js").read_text(encoding="utf-8")
    for text in ("1ステップずつ表示", "← 前へ", "次へ →", "すべて表示", "かかった時間：", "解答までの時間：", "visibilitychange"):
        assert text in app, text
    assert "step-controls" not in problem and 'class="giji-trace"' in problem
    mock = (ROOT / "site" / "static" / "mock.js").read_text(encoding="utf-8")
    assert "stopwatch" not in mock and "解答までの時間" not in mock                    # 模試の時間表示とは別のもの
