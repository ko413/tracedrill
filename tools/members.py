#!/usr/bin/env python3
"""会員向けコンテンツ（模試・先行公開ドリル）を作り、暗号化して公開用フォルダに置く。

    python tools/members.py sample                  # 無料のサンプル模試を作る（最初の1回だけ）
    python tools/members.py mock --month 2026-12    # その月の模試を1回分作る（第N回は自動で付く）
    python tools/members.py early queue-ring-001    # 先行公開テンプレートのドリルを作る
    python tools/members.py publish --month 2026-12 # 暗号化して site/members/ に置く。月が変われば合言葉も変える
    python tools/members.py release queue-ring-001  # 先行公開を終えて、無料の問題として公開する準備をする
    python tools/members.py single mock-001 --url https://…   # 模試1回分だけを開ける単品用の合言葉を作る
    python tools/members.py check                   # 公開前の確認（会員と同じ手順で全部開いてみる。書き換えない）
    python tools/members.py status                  # 今の状態を一覧する
    python tools/members.py recover 合言葉          # private/ をなくしたときの復旧

置き場所は2つ。
  private/        … 平文の中身、鍵、合言葉、先行公開中のテンプレート。**リポジトリに入れない**（.gitignore 済み）。
  site/members/   … 暗号化したファイルと目次だけ。こちらはコミットして公開する。

決まりごと（problems/ と同じ考え方）:
  - 一度作った模試・ドリル（private/bundles/*.json）は作り直さない。同じ名前があれば止まる。
  - 一度暗号化したファイル（site/members/data/*.json）も書き換えない。
  - 書き換えるのは、目次（index.json）と、合言葉で開く鍵束（keyring.json）だけ。

会員の確認方法（今は「合言葉」）に関係するのは keyring.json だけなので、
Stripe などに移るときも、模試の中身と暗号化の仕組みはそのまま使える。
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import random
import secrets
import shutil
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build  # noqa: E402
from giji.errors import GijiError  # noqa: E402
from giji.generator import Template, load_templates  # noqa: E402
from giji.render import source_html, trace_table_html  # noqa: E402

MOCK_QUESTIONS = 16
MOCK_MINUTES = 80
MOCK_NAME = "アルゴリズム16問模試（トレース中心）"
DRILL_QUESTIONS = 10
KDF_ITERATIONS = 200_000
#: 合言葉に使う文字。読み間違えやすい 0/O、1/I/L は入れない。
PASS_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MIN_WEIGHT = 0.5


class MemberError(Exception):
    pass


class Paths:
    def __init__(self, root: Path = ROOT, private: Path | None = None, public: Path | None = None,
                 templates: Path | None = None, problems: Path | None = None, content: Path | None = None):
        self.private = private or root / "private"
        self.public = public or root / "site" / "members"
        self.templates = templates or root / "templates" / "basic"
        self.problems = problems or root / "problems"
        self.content = content or root / "content"          # 解説の原稿（content/algo/<id>.md）
        self.private_templates = self.private / "templates"
        self.bundles = self.private / "bundles"
        self.keys = self.private / "keys.json"
        self.passphrase = self.private / "passphrase.json"
        self.released = self.private / "released.json"
        self.singles = self.private / "singles.json"        # 単品用の合言葉（模試の名前 → 合言葉と販売ページ）
        self.data = self.public / "data"
        self.index = self.public / "index.json"
        self.keyring = self.public / "keyring.json"
        self.sample = self.public / "sample.json"
        self.single = self.public / "single"                # 単品用の鍵束（その模試の鍵だけが入っている）


# ---- 小道具 ----

def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def normalize_passphrase(text: str) -> str:
    """入力のゆれを吸収する（全角・小文字・ハイフン・空白）。member.js と同じ規則。"""
    text = unicodedata.normalize("NFKC", text).upper()
    return "".join(ch for ch in text if ch.isalnum())


def new_passphrase() -> str:
    groups = ["".join(secrets.choice(PASS_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join(groups)


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise MemberError("暗号化に cryptography が必要です。pip install -r requirements-members.txt を実行してください") from None
    return AESGCM


def encrypt(key: bytes, plain: bytes) -> dict:
    """AES-256-GCM。ブラウザの Web Crypto でそのまま復号できる形（暗号文の末尾に認証タグ）。"""
    iv = os.urandom(12)
    return {"v": 1, "alg": "AES-256-GCM", "iv": _b64(iv), "ct": _b64(_aesgcm()(key).encrypt(iv, plain, None))}


def decrypt(key: bytes, box: dict) -> bytes:
    return _aesgcm()(key).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["ct"]), None)


def derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", normalize_passphrase(passphrase).encode("utf-8"), salt, iterations, 32)


def make_keyring(passphrase: str, keys: dict, issued: str) -> dict:
    """合言葉で開く「鍵束」。中身は 模試の名前 → その模試の鍵。"""
    salt = os.urandom(16)
    plain = json.dumps({"issued": issued, "keys": keys}, ensure_ascii=False).encode("utf-8")
    box = encrypt(derive_key(passphrase, salt), plain)
    return {**box, "kdf": "PBKDF2-SHA256", "iter": KDF_ITERATIONS, "salt": _b64(salt), "issued": issued}


def open_keyring(passphrase: str, ring: dict) -> dict:
    key = derive_key(passphrase, base64.b64decode(ring["salt"]), int(ring["iter"]))
    return json.loads(decrypt(key, ring).decode("utf-8"))


# ---- 問題づくり ----

def _question(snap: dict, template: Template) -> dict:
    """保存用の問題データ（build.py の snapshot）から、模試の画面に必要なものだけを取り出す。"""
    exam = snap["exam"]
    markers = {int(line): mark for line, mark in exam["markers"].items()}
    trace = snap["trace"]
    return {
        "template_id": template.id, "seed": snap["seed"], "title": template.title,
        "level": build.LEVEL_NAMES.get(template.level, str(template.level)),
        "lead": exam["lead"], "body": exam["body"], "blanks": exam["blanks"],
        "program_html": source_html(exam["source"], numbered=False, markers=markers),
        "choices": exam["choices"], "answer": exam["answer_label"], "answer_text": exam["answer_text"],
        "explain": exam["explain"], "explanation": snap["explanation"],
        "marker_line": next(iter(markers), None),
        "review_html": source_html(snap["source"]) + trace_table_html(trace["names"], trace["rows"]),
        "source": snap["source"], "call": snap["call"],
    }


def _used(paths: Paths) -> set:
    """公開済みの問題と、これまでの模試・ドリルに出した問題（プログラムと呼出しの組）。"""
    used = set()
    for path in paths.problems.glob("*/[0-9]*.json"):
        snap = json.loads(path.read_text(encoding="utf-8"))
        used.add((snap["source"], snap["call"]))
    for path in list(paths.bundles.glob("*.json")) + ([paths.sample] if paths.sample.exists() else []):
        for q in json.loads(path.read_text(encoding="utf-8"))["questions"]:
            used.add((q["source"], q["call"]))
    return used


def _make_one(template: Template, number: int, rng: random.Random, used: set) -> dict | None:
    """まだ出していない値で、本番形式の問題を1つ作る。作れなければ None。"""
    for _ in range(60):
        seed = rng.randrange(100_000, 1_000_000)
        try:
            snap = build.make_snapshot(template, seed, number, MIN_WEIGHT)
        except GijiError:
            continue
        if snap["exam"] is None or (snap["source"], snap["call"]) in used:
            continue
        used.add((snap["source"], snap["call"]))
        return _question(snap, template)
    return None


def _groups(templates: list[Template]) -> list[list[Template]]:
    """同じアルゴリズムの版（variant_of）を1組にまとめる。模試では1組から1問だけ出す。"""
    groups: dict[str, list[Template]] = {}
    for template in templates:
        groups.setdefault(template.variant_of or template.id, []).append(template)
    return [sorted(group, key=lambda t: (t.pace != "standard", t.id)) for _, group in sorted(groups.items())]


def all_templates(paths: Paths, include_private: bool) -> list[Template]:
    templates = load_templates(paths.templates)
    if include_private and paths.private_templates.exists() and any(paths.private_templates.glob("*.yaml")):
        templates += load_templates(paths.private_templates)
    return templates


def compose_mock(bundle_id: str, title: str, issued: str, templates: list[Template], used: set,
                 count: int = MOCK_QUESTIONS, minutes: int = MOCK_MINUTES) -> dict:
    """模試1回分。アルゴリズムが重ならないように選び、やさしい順に並べる。名前（id）が同じなら同じ選び方になる。"""
    rng = random.Random(f"bundle:{bundle_id}")
    groups = _groups(templates)
    rng.shuffle(groups)
    # 半分までは中級以上から先に選ぶ（やさしい問題ばかりにならないように）。残りは全体から。
    hard = [g for g in groups if g[0].level >= 3][:count // 2]
    rest = [g for g in groups if g not in hard]
    made = []
    for group in hard + rest:
        if len(made) >= count:
            break
        question = _make_one(group[0], len(made) + 1, rng, used)   # 模試は標準の版を優先
        if question:
            made.append((group[0].level, group[0].id, question))
    questions = [q for _, _, q in sorted(made, key=lambda item: item[:2])]       # やさしい順に並べる
    if len(questions) < count:
        raise MemberError(f"{count}問そろいませんでした（{len(questions)}問）。テンプレートを増やしてください")
    return {"version": 1, "id": bundle_id, "kind": "mock", "title": title, "issued": issued,
            "minutes": minutes, "questions": questions}


def compose_drill(template: Template, issued: str, used: set, count: int = DRILL_QUESTIONS) -> dict:
    rng = random.Random(f"bundle:early-{template.id}")
    questions = []
    for number in range(1, count * 4):
        if len(questions) >= count:
            break
        question = _make_one(template, number, rng, used)
        if question:
            questions.append(question)
    if not questions:
        raise MemberError(f"{template.id}: 問題を作れませんでした")
    return {"version": 1, "id": f"early-{template.id}", "kind": "drill", "issued": issued, "minutes": 0,
            "title": f"先行公開：{template.title}", "template_id": template.id, "questions": questions}


def _save_new(path: Path, data: dict) -> None:
    if path.exists():
        raise MemberError(f"{path} はすでにあります。作ったものは作り直しません（別の名前で作ってください）")
    build.save_new_json(path, data)


# ---- コマンド ----

def this_month() -> str:
    return datetime.date.today().strftime("%Y-%m")


def cmd_sample(paths: Paths, count: int = MOCK_QUESTIONS) -> dict:
    """無料のサンプル模試。公開中のテンプレートだけで作り、平文のまま公開する。"""
    if paths.sample.exists():
        raise MemberError(f"{paths.sample} はすでにあります。サンプル模試は作り直しません")
    bundle = compose_mock("sample", f"サンプル模試：{MOCK_NAME}", this_month(),
                          all_templates(paths, include_private=False), _used(paths), count=count)
    _save_new(paths.sample, bundle)
    return bundle


def cmd_mock(paths: Paths, month: str, count: int = MOCK_QUESTIONS) -> dict:
    existing = sorted(paths.bundles.glob("mock-*.json"))
    number = len(existing) + 1
    bundle_id = f"mock-{number:03d}"
    title = f"第{number}回 {MOCK_NAME}"
    bundle = compose_mock(bundle_id, title, month, all_templates(paths, include_private=True),
                          _used(paths), count=count)
    _save_new(paths.bundles / f"{bundle_id}.json", bundle)
    return bundle


def cmd_early(paths: Paths, template_id: str, month: str) -> dict:
    templates = {t.id: t for t in all_templates(paths, include_private=True)}
    if template_id not in templates:
        raise MemberError(f"テンプレート {template_id} が見つかりません（private/templates/ に置いてください）")
    bundle = compose_drill(templates[template_id], month, _used(paths))
    _save_new(paths.bundles / f"{bundle['id']}.json", bundle)
    return bundle


def cmd_publish(paths: Paths, month: str, new_passphrase: bool = False) -> dict:
    """暗号化して公開用フォルダに置く。月が変わったとき（か --new-passphrase）だけ合言葉を変える。"""
    bundles = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(paths.bundles.glob("*.json"))]
    if not bundles:
        raise MemberError("private/bundles/ に模試がありません。先に mock か early を実行してください")
    keys = _read(paths.keys, {})
    released = _read(paths.released, {})
    added = []
    for bundle in bundles:
        target = paths.data / f"{bundle['id']}.json"
        if bundle["id"] not in keys:
            if target.exists():
                raise MemberError(f"{target} はあるのに鍵が private/keys.json にありません。private/ を復元してください")
            keys[bundle["id"]] = _b64(os.urandom(32))
        if not target.exists():
            plain = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
            build.save_new_json(target, encrypt(base64.b64decode(keys[bundle["id"]]), plain))
            added.append(bundle["id"])
    _write(paths.keys, keys)

    write_index(paths, bundles, month)

    state = _read(paths.passphrase, {"current": None, "history": []})
    current = state["current"]
    changed = new_passphrase or current is None or current["month"] != month
    if changed:
        if current:
            state["history"].append(current)
        current = {"month": month, "passphrase": new_passphrase_value()}
        state["current"] = current
        _write(paths.passphrase, state)
    ring_keys = None
    if paths.keyring.exists() and not changed:
        try:
            ring_keys = open_keyring(current["passphrase"], _read(paths.keyring, {}))["keys"]
        except Exception:      # 鍵束が壊れている・合言葉と合わない → 作り直す
            ring_keys = None
    if ring_keys != keys:
        _write(paths.keyring, make_keyring(current["passphrase"], keys, month))
    return {"passphrase": current["passphrase"], "month": current["month"], "changed": changed,
            "added": added, "total": len(bundles)}


def write_index(paths: Paths, bundles: list, month: str) -> None:
    """目次（題名と問題数だけ。中身は入れない）。単品で買える回には、その印と販売ページを付ける。"""
    released = _read(paths.released, {})
    singles = _read(paths.singles, {})
    entries = []
    for bundle in bundles:
        entry = {"id": bundle["id"], "kind": bundle["kind"], "title": bundle["title"],
                 "issued": bundle["issued"], "count": len(bundle["questions"]), "minutes": bundle["minutes"]}
        if bundle["id"] in released:
            entry["public_path"] = released[bundle["id"]]
        if bundle["id"] in singles and (paths.single / f"{bundle['id']}.json").exists():
            entry["single"] = True
            if singles[bundle["id"]].get("url"):
                entry["single_url"] = singles[bundle["id"]]["url"]
        entries.append(entry)
    entries.sort(key=lambda e: (e["issued"], e["id"]), reverse=True)     # 新しい月を上に
    _write(paths.index, {"version": 1, "updated": month, "bundles": entries})


def cmd_single(paths: Paths, bundle_id: str, url: str | None = None, new_passphrase: bool = False) -> dict:
    """模試1回分だけを開ける「単品用の合言葉」を作る（note の有料記事などで1回ずつ売るため）。

    その模試の鍵だけを入れた小さな鍵束 site/members/single/<id>.json を足す。
    暗号化済みの模試（site/members/data/）にも、会員用の鍵束にも触らない。
    単品用の合言葉は月が替わっても変わらない（--new-passphrase で作り直したときだけ変わる）。
    """
    keys = _read(paths.keys, {})
    if bundle_id not in keys or not (paths.data / f"{bundle_id}.json").exists():
        raise MemberError(f"{bundle_id} はまだ公開用に暗号化されていません。先に publish を実行してください")
    singles = _read(paths.singles, {})
    entry = singles.get(bundle_id)
    target = paths.single / f"{bundle_id}.json"
    changed = entry is None or new_passphrase or not target.exists()
    if entry is None or new_passphrase:
        entry = {"passphrase": new_passphrase_value(), "url": (entry or {}).get("url", "")}
    if url is not None:
        entry["url"] = url
    singles[bundle_id] = entry
    _write(paths.singles, singles)
    if changed:
        bundle = _read(paths.bundles / f"{bundle_id}.json", {"issued": ""})
        _write(target, make_keyring(entry["passphrase"], {bundle_id: keys[bundle_id]}, bundle.get("issued", "")))
    bundles = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(paths.bundles.glob("*.json"))]
    index = _read(paths.index, {"updated": this_month()})
    write_index(paths, bundles, index.get("updated", this_month()))
    return {"id": bundle_id, "passphrase": entry["passphrase"], "url": entry["url"], "changed": changed}


def single_text(result: dict, title: str, site_url: str) -> str:
    return (f"【{title} の合言葉】\n{result['passphrase']}\n\n"
            f"{site_url}/members/?id={result['id']} を開き、合言葉を入力してください。\n"
            "この合言葉で開けるのは、この回の模試だけです。期限はありません。\n"
            "毎月の新しい模試と、これまでのすべての回を解くには、メンバーシップをご利用ください。")


def new_passphrase_value() -> str:      # テストで差し替えやすいように分けてある
    return new_passphrase()


def cmd_release(paths: Paths, template_id: str) -> Path:
    """先行公開を終える：テンプレートを templates/basic/ に移す（このあと python build.py で無料の問題ができる）。"""
    source = paths.private_templates / f"{template_id}.yaml"
    target = paths.templates / f"{template_id}.yaml"
    if not source.exists():
        raise MemberError(f"{source} がありません")
    if target.exists():
        raise MemberError(f"{target} がすでにあります")
    text = source.read_text(encoding="utf-8").replace("access: member", "access: free", 1)
    target.write_text(text, encoding="utf-8")
    source.unlink()
    # 解説の下書き（private/drafts/content/algo/<id>.md）があれば、一緒に content/algo/ へ移す
    draft = paths.private / "drafts" / "content" / "algo" / f"{template_id}.md"
    page = paths.content / "algo" / f"{template_id}.md"
    if draft.exists() and not page.exists():
        page.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(draft), str(page))
    released = _read(paths.released, {})
    released[f"early-{template_id}"] = f"/algo/{template_id}/"
    _write(paths.released, released)
    return target


def cmd_recover(paths: Paths, passphrase: str) -> list[str]:
    """private/ をなくしたときの復旧。公開してある鍵束を今の合言葉で開き、鍵と模試の中身を取り戻す。

    取り戻せないのは、先行公開中のテンプレート（private/templates/）だけ。
    """
    if not paths.keyring.exists():
        raise MemberError(f"{paths.keyring} がありません")
    ring = _read(paths.keyring, {})
    try:
        opened = open_keyring(passphrase, ring)
    except Exception:
        raise MemberError("この合言葉では鍵束を開けません。note に載せた最新の合言葉を指定してください") from None
    keys = {**opened["keys"], **_read(paths.keys, {})}
    _write(paths.keys, keys)
    restored = []
    for bundle_id, key in sorted(opened["keys"].items()):
        target = paths.bundles / f"{bundle_id}.json"
        source = paths.data / f"{bundle_id}.json"
        if target.exists() or not source.exists():
            continue
        bundle = json.loads(decrypt(base64.b64decode(key), _read(source, {})).decode("utf-8"))
        build.save_new_json(target, bundle)
        restored.append(bundle_id)
    if not paths.passphrase.exists():
        text = "-".join(normalize_passphrase(passphrase)[i:i + 4] for i in range(0, 16, 4))
        _write(paths.passphrase, {"current": {"month": opened["issued"], "passphrase": text}, "history": []})
    return restored


def cmd_check(paths: Paths) -> list[str]:
    """公開前の確認。公開用フォルダの中身を、会員と同じ手順で実際に開いて確かめる（何も書き換えない）。

    問題があれば MemberError。なければ、確かめた内容の一覧を返す。
    """
    state = _read(paths.passphrase, {"current": None, "history": []})
    current = state["current"]
    if not current:
        raise MemberError("合言葉がまだありません。先に publish を実行してください")
    if not paths.keyring.exists():
        raise MemberError(f"{paths.keyring} がありません。publish を実行してください")
    ring = _read(paths.keyring, {})
    try:
        keys = open_keyring(current["passphrase"], ring)["keys"]
    except Exception:
        raise MemberError("今の合言葉で鍵束を開けません。publish をやり直してください") from None
    lines = [f"今の合言葉（{current['month']} 分）で鍵束が開く"]
    bundle_ids = sorted(p.stem for p in paths.bundles.glob("*.json"))
    missing = [b for b in bundle_ids if b not in keys]
    if missing:
        raise MemberError("鍵束に入っていない模試があります: " + "、".join(missing) + "。publish を実行してください")
    for bundle_id in bundle_ids:
        source = paths.data / f"{bundle_id}.json"
        if not source.exists():
            raise MemberError(f"{source} がありません。publish を実行してください")
        try:
            opened = json.loads(decrypt(base64.b64decode(keys[bundle_id]), _read(source, {})).decode("utf-8"))
        except Exception:
            raise MemberError(f"{bundle_id} を開けません（鍵と暗号化ファイルが合っていません）。private/ を控えから戻してください") from None
        if opened != _read(paths.bundles / f"{bundle_id}.json", None):
            raise MemberError(f"{bundle_id}: 公開用のファイルと private/bundles/ の中身が違います")
    lines.append(f"模試・ドリル {len(bundle_ids)} 件すべてが開き、中身が private/bundles/ と一致する（バックナンバーを含む）")
    listed = sorted(b["id"] for b in _read(paths.index, {"bundles": []})["bundles"])
    if listed != bundle_ids:
        raise MemberError("目次（index.json）と模試の一覧が合っていません。publish を実行してください")
    lines.append("目次（index.json）に全件が載っている")
    for old in state.get("history", []):
        try:
            open_keyring(old["passphrase"], ring)
        except Exception:
            continue
        raise MemberError(f"前の合言葉（{old['month']} 分）でも鍵束が開いてしまいます。publish --new-passphrase を実行してください")
    lines.append(f"前の合言葉 {len(state.get('history', []))} 個では開かない")
    public_text = "".join(p.read_text(encoding="utf-8") for p in paths.public.rglob("*.json"))
    secrets_found = [name for name, text in [("今の合言葉", current["passphrase"])]
                     + [(f"単品の合言葉（{k}）", v["passphrase"]) for k, v in _read(paths.singles, {}).items()]
                     if text in public_text]
    if secrets_found:
        raise MemberError("公開用フォルダに合言葉そのものが入っています: " + "、".join(secrets_found))
    lines.append("公開用フォルダに合言葉は入っていない")
    for bundle_id, entry in sorted(_read(paths.singles, {}).items()):
        target = paths.single / f"{bundle_id}.json"
        try:
            one = open_keyring(entry["passphrase"], _read(target, {}))["keys"]
        except Exception:
            raise MemberError(f"単品用の合言葉で {target} を開けません。single をやり直してください") from None
        if list(one) != [bundle_id] or one[bundle_id] != keys[bundle_id]:
            raise MemberError(f"単品用の鍵束 {target} の中身が正しくありません")
        lines.append(f"単品用の合言葉で {bundle_id} だけが開く")
    return lines


def cmd_status(paths: Paths) -> list[str]:
    lines = []
    state = _read(paths.passphrase, {"current": None})
    current = state["current"]
    lines.append(f"合言葉: {current['passphrase']}（{current['month']} 分）" if current else "合言葉: まだありません")
    for path in sorted(paths.bundles.glob("*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        mark = "公開用に暗号化済み" if (paths.data / path.name).exists() else "未公開（publish を実行）"
        lines.append(f"  {bundle['id']}  {bundle['issued']}  {len(bundle['questions'])}問  {bundle['title']}  … {mark}")
    waiting = sorted(p.stem for p in paths.private_templates.glob("*.yaml")) if paths.private_templates.exists() else []
    lines.append("先行公開中（まだ無料公開していない）テンプレート: " + ("、".join(waiting) or "なし"))
    lines.append("サンプル模試: " + ("あり" if paths.sample.exists() else "なし（sample を実行）"))
    for bundle_id, entry in sorted(_read(paths.singles, {}).items()):
        lines.append(f"単品用の合言葉: {bundle_id}  {entry['passphrase']}  販売ページ: {entry.get('url') or '未設定'}")
    return lines


def note_text(result: dict, site_url: str) -> str:
    return (f"【{result['month']} の合言葉】\n{result['passphrase']}\n\n"
            f"{site_url}/members/ を開き、合言葉を入力してください。\n"
            "これまでの模試（バックナンバー）と先行公開ドリルも、同じ合言葉ですべて解けます。\n"
            "合言葉は毎月変わります。新しい合言葉は、この会員限定の記事でお知らせします。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="会員向けコンテンツの作成と公開")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sample", help="無料のサンプル模試を作る")
    p = sub.add_parser("mock", help="模試を1回分作る")
    p.add_argument("--month", default=this_month(), help="発行月（例 2026-12）")
    p = sub.add_parser("early", help="先行公開テンプレートのドリルを作る")
    p.add_argument("template_id")
    p.add_argument("--month", default=this_month())
    p = sub.add_parser("publish", help="暗号化して site/members/ に置く")
    p.add_argument("--month", default=this_month(), help="合言葉の月。変わると新しい合言葉になる")
    p.add_argument("--new-passphrase", action="store_true", help="月の途中でも合言葉を変える（漏れたとき用）")
    p = sub.add_parser("release", help="先行公開を終えて templates/basic/ に移す")
    p.add_argument("template_id")
    p = sub.add_parser("single", help="模試1回分だけを開ける単品用の合言葉を作る")
    p.add_argument("bundle_id", help="例 mock-001")
    p.add_argument("--url", help="販売ページ（note の有料記事など）の URL。会員ページの一覧に出る")
    p.add_argument("--new-passphrase", action="store_true", help="単品用の合言葉を作り直す（漏れたとき用）")
    sub.add_parser("status", help="今の状態を表示する")
    sub.add_parser("check", help="公開前の確認：今の合言葉で全部の模試が開くか、前の合言葉で開かないかを確かめる")
    p = sub.add_parser("recover", help="private/ をなくしたとき、今の合言葉で鍵と模試を取り戻す")
    p.add_argument("passphrase")
    args = parser.parse_args(argv)
    paths = Paths()
    try:
        if args.command == "sample":
            bundle = cmd_sample(paths)
            print(f"サンプル模試（{len(bundle['questions'])}問）を {paths.sample} に作りました。python build.py で公開されます")
        elif args.command == "mock":
            bundle = cmd_mock(paths, args.month)
            print(f"{bundle['title']} を private/bundles/{bundle['id']}.json に作りました。次は publish です")
        elif args.command == "early":
            bundle = cmd_early(paths, args.template_id, args.month)
            print(f"{bundle['title']}（{len(bundle['questions'])}問）を作りました。次は publish です")
        elif args.command == "publish":
            result = cmd_publish(paths, args.month, args.new_passphrase)
            site = build.load_config(ROOT / "site.yaml")
            print(f"公開用ファイル: 全{result['total']}件（今回追加 {len(result['added'])}件: {'、'.join(result['added']) or 'なし'}）")
            print("合言葉は" + ("新しくなりました。" if result["changed"] else "前回と同じです。"))
            print("---- note の会員限定記事に貼る文面 ----")
            print(note_text(result, site["base_url"] + site["base_path"]))
            print("----")
            print("このあと: python build.py --frozen → site/members/ をコミットして push")
        elif args.command == "single":
            result = cmd_single(paths, args.bundle_id, args.url, args.new_passphrase)
            site = build.load_config(ROOT / "site.yaml")
            title = _read(paths.bundles / f"{args.bundle_id}.json", {}).get("title", args.bundle_id)
            print("単品用の合言葉を" + ("作りました。" if result["changed"] else "確認しました（前回と同じ）。"))
            print("---- 有料記事の有料部分に貼る文面 ----")
            print(single_text(result, title, site["base_url"] + site["base_path"]))
            print("----")
            print("このあと: python build.py --frozen → site/members/ をコミットして push")
        elif args.command == "release":
            target = cmd_release(paths, args.template_id)
            page = ROOT / "content" / "algo" / f"{args.template_id}.md"
            print(f"{target} に移しました。")
            print(f"解説: {page} " + ("を下書きから移しました。" if page.exists() else "がありません。ほかの解説を写して書いてください。"))
            print("このあと: python build.py を実行し、problems/・templates/・content/ をコミットしてください")
        elif args.command == "check":
            for line in cmd_check(paths):
                print("OK  " + line)
            print("公開用のファイルに問題はありません。")
        elif args.command == "recover":
            restored = cmd_recover(paths, args.passphrase)
            print(f"鍵を private/keys.json に戻しました。模試の中身を {len(restored)} 件戻しました: {'、'.join(restored) or 'なし'}")
            print("先行公開中のテンプレート（private/templates/）は戻せません。控えから戻してください")
        else:
            print("\n".join(cmd_status(paths)))
    except MemberError as err:
        print(f"エラー: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
