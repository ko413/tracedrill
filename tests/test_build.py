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
    assert "<title>条件に合う要素の合計 問題01｜擬似言語トレース問題｜テストサイト（科目B）</title>" in page
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
    assert "<title>条件に合う要素の合計（標準） 問題01｜" in added
    assert "<title>条件に合う要素の合計 問題01｜" in old               # 元からあるページのタイトルは変えない
    assert 'class="badge pace-standard">標準' in added and 'class="badge pace-long">じっくり' in old
    assert 'href="/algo/loop-sum-001/#standard"' in added


def test_levels_use_the_new_names_and_assignments(site):
    home = (site / "index.html").read_text(encoding="utf-8")
    assert "本試験相当" not in home
    beginner = home.split('id="level-1"')[1].split('id="level-2"')[0]
    middle = home.split('id="level-3"')[1].split("このサイトについて")[0]
    assert "再帰呼出しの戻り値" in beginner
    assert "二次元配列の行ごとの合計" in middle and "同じ文字が続く最長の長さ" in middle
