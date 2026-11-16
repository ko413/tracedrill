#!/usr/bin/env python3
"""コミット・push の前の確認を、まとめて行う。

    python tools/preflight.py            # 全部（テストとビルドを含む。2〜3分）
    python tools/preflight.py --quick    # テストとビルドを省く（数秒）

確かめること（CLAUDE.md の「絶対に守ること」に対応）:
  1. 公開済みの問題（problems/）と配布済みの模試（site/members/data/）を、変更・削除していない
  2. private/ がコミットの対象になっていない。.gitignore の .venv/ と private/ の行がある
  3. 合言葉・鍵が、コミットの対象になるファイルに入っていない
  4. 確認できていない書き方（「未定義でない」）を、テンプレートと原稿で使っていない
  5. site.yaml を書き換えていない（運営者の手元の版が正しい）
  6. 会員向けのファイルが、今の合言葉で全部開く（tools/members.py check）
  7. python -m pytest -q と python build.py --frozen が通る
  8. Stripe などの秘密の値（sk_live_… whsec_… など）や .dev.vars が、コミットの対象に入っていない
  9. 公開するページ（content/）に、下書きの【　】や「公開しない」の印が残っていない

1つでも NG があれば、終了コード 1 で終わる。NG のままコミット・push しない。
何も書き換えない（ビルドの出力先 dist/ を除く）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ("problems/", "site/members/data/")          # 既存のファイルを変えてはいけない場所
FORBIDDEN_NOTATION = "未定義でない"
#: 外部サービスの秘密の値の形（Stripe のシークレットキー・制限付きキー・Webhook の署名の鍵、Resend のキー）
SECRET_PATTERNS = re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}|\bwhsec_[0-9A-Za-z]{16,}|\bre_[0-9A-Za-z]{8,}_[0-9A-Za-z]{16,}")
#: 秘密の値を入れるファイル（手元にだけ置く。コミットしない）
SECRET_FILES = (".dev.vars", ".env")
DRAFT_MARKS = ("【", "---8<---")


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "git の実行に失敗しました")
    return done.stdout


def changed_files() -> list[tuple[str, str]]:
    """作業中の変更（コミット前のもの全部）。[(状態, パス)]。状態は M=変更 D=削除 R=改名 A/?=追加。"""
    result = []
    for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
        status, path = line[:2].strip() or "?", line[3:]
        if " -> " in path:                                # 改名は「元 -> 先」。元のファイルがなくなる
            old, path = path.split(" -> ", 1)
            result.append(("D", old.strip('"')))
        result.append((status[0] if status != "??" else "?", path.strip('"')))
    return result


def check_frozen(changes) -> list[str]:
    return [f"{path}（{'削除' if status == 'D' else '変更'}）" for status, path in changes
            if path.startswith(FROZEN) and status in ("M", "D", "R")]


def check_ignore() -> list[str]:
    problems = []
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for needed in (".venv/", "private/"):
        if needed not in lines:
            problems.append(f".gitignore に {needed} の行がありません")
    tracked = git("ls-files", "private").strip()
    if tracked:
        problems.append("private/ の中のファイルが git に登録されています: " + tracked.splitlines()[0] + " ほか")
    return problems


def secrets() -> dict[str, str]:
    """private/ にある合言葉と鍵（名前 → 文字列）。private/ がなければ空。"""
    found = {}
    private = ROOT / "private"

    def read(name):
        path = private / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    state = read("passphrase.json")
    if state:
        for entry in [state.get("current")] + list(state.get("history", [])):
            if entry:
                found[f"合言葉（{entry['month']} 分）"] = entry["passphrase"]
    for bundle_id, entry in (read("singles.json") or {}).items():
        found[f"単品の合言葉（{bundle_id}）"] = entry["passphrase"]
    for bundle_id, key in (read("keys.json") or {}).items():
        found[f"鍵（{bundle_id}）"] = key
    return found


def check_secrets() -> list[str]:
    wanted = secrets()
    if not wanted:
        return []
    variants = {name: {text, text.replace("-", "")} for name, text in wanted.items()}
    problems = []
    files = set(git("ls-files").splitlines()) | set(git("ls-files", "--others", "--exclude-standard").splitlines())
    for name in sorted(files):
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, texts in variants.items():
            if any(t in text for t in texts):
                problems.append(f"{name} に {label} が入っています")
    return problems


def committable_files() -> list[str]:
    return sorted(set(git("ls-files").splitlines()) | set(git("ls-files", "--others", "--exclude-standard").splitlines()))


def check_service_secrets() -> list[str]:
    problems = []
    for name in committable_files():
        path = ROOT / name
        if Path(name).name in SECRET_FILES or Path(name).name.startswith(".dev.vars"):
            problems.append(f"{name} はコミットしてはいけないファイルです（.gitignore に入れてください）")
            continue
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = SECRET_PATTERNS.search(text)
        if found:
            problems.append(f"{name} に秘密の値らしいものがあります（{found.group(0)[:10]}…）")
    return problems


def check_drafts() -> list[str]:
    """公開するページに、下書きの印が残っていないか（drafts/legal/ から content/ に移したときの埋め忘れ）。"""
    problems = []
    for name in ("tokushoho.md", "privacy.md"):
        path = ROOT / "content" / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            for mark in DRAFT_MARKS:
                if mark in text:
                    problems.append(f"content/{name} に「{mark}」が残っています（{text.count(mark)} か所）")
    return problems


def check_notation() -> list[str]:
    problems = []
    for folder in ("templates", "content", "private/templates", "private/drafts"):
        base = ROOT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix in (".yaml", ".md") and FORBIDDEN_NOTATION in path.read_text(encoding="utf-8"):
                problems.append(f"{path.relative_to(ROOT)} に「{FORBIDDEN_NOTATION}」があります")
    return problems


def check_site_yaml(changes) -> list[str]:
    return ["site.yaml が変更されています（運営者の手元の版が正しい。意図した変更か確認してください）"
            for status, path in changes if path == "site.yaml" and status in ("M", "D")]


def run(label: str, command: list[str]) -> list[str]:
    print(f"… {label}（少し時間がかかります）", flush=True)
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if done.returncode == 0:
        return []
    tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-12:])
    return [f"{' '.join(command)} が失敗しました:\n{tail}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="コミット・push の前の確認")
    parser.add_argument("--quick", action="store_true", help="テストとビルドを省く")
    parser.add_argument("--allow-site-yaml", action="store_true",
                        help="site.yaml の変更を認める（運営者が意図して設定を変えたときだけ。MIGRATION_B.md の F・G）")
    args = parser.parse_args(argv)
    try:
        changes = changed_files()
    except (RuntimeError, FileNotFoundError) as err:
        print(f"NG  git の状態を読めません: {err}")
        return 1

    checks = [
        ("公開済みの問題・配布済みの模試を変更していない", check_frozen(changes)),
        ("private/ がコミットの対象になっていない", check_ignore()),
        ("合言葉・鍵がコミットの対象のファイルに入っていない", check_secrets()),
        ("確認できていない書き方を使っていない", check_notation()),
        ("site.yaml を書き換えていない", [] if args.allow_site_yaml else check_site_yaml(changes)),
        ("外部サービスの秘密の値がコミットの対象に入っていない", check_service_secrets()),
        ("公開するページに下書きの印が残っていない", check_drafts()),
    ]
    if (ROOT / "private" / "passphrase.json").exists():
        checks.append(("会員向けのファイルが今の合言葉で全部開く",
                       run("会員向けのファイルを確認", [sys.executable, "tools/members.py", "check"])))
    if not args.quick:
        checks.append(("python -m pytest -q が通る", run("テスト", [sys.executable, "-m", "pytest", "-q"])))
        checks.append(("python build.py --frozen が通る", run("ビルド", [sys.executable, "build.py", "--frozen"])))

    failed = 0
    for label, problems in checks:
        if problems:
            failed += 1
            print(f"NG  {label}")
            for problem in problems[:10]:
                print("      " + problem.replace("\n", "\n      "))
            if len(problems) > 10:
                print(f"      ほか {len(problems) - 10} 件")
        else:
            print(f"OK  {label}")

    added = sorted({path.split("/")[0] + "/" + path.split("/")[1] if path.count("/") > 1 else path
                    for status, path in changes if status in ("A", "?")})
    if added:
        print("新しく増えるもの: " + "、".join(added[:12]) + (f" ほか{len(added) - 12}件" if len(added) > 12 else ""))
    if failed:
        print(f"\nNG が {failed} 件あります。直るまでコミット・push しないでください。")
        return 1
    print("\nすべて OK です。" + ("（--quick：テストとビルドは省きました）" if args.quick else "コミットして push できます。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
