"""テンプレートの検査：各テンプレートから多数の問題を作り、出題して問題ないか確かめる。

    python tools/validate_templates.py                 # templates/ 以下をすべて検査
    python tools/validate_templates.py templates/basic/loop-sum-001.yaml -n 500

誤りが1つでもあれば終了コード1で終わるので、公開前の自動チェックに使える。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from giji.errors import GijiError  # noqa: E402
from giji.generator import generate, load_template  # noqa: E402

MIN_ACCEPT_RATE = 0.20      # 抽選の採用率がこれ未満なら警告（条件が厳しすぎる）
MIN_DISTINCT_ANSWERS = 3    # 答えの種類がこれ未満なら警告（毎回同じ答えになる）


def check_template(path: Path, runs: int) -> tuple[list[str], list[str], str]:
    """(誤り, 警告, 要約) を返す。"""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        template = load_template(path)
    except (GijiError, OSError, ValueError) as err:
        return [f"読み込めません: {err}"], [], ""

    attempts = 0
    made = 0
    rejects: Counter = Counter()
    answers: dict[int, set] = {}
    written: dict[int, int] = {}
    question_types = [q["type"] for q in template.questions]

    for seed in range(runs):
        try:
            problem = generate(template, seed)
        except GijiError as err:
            errors.append(f"seed={seed}: {err}")
            if len(errors) >= 5:
                errors.append("（誤りが多いので打ち切りました）")
                break
            continue
        made += 1
        attempts += problem.attempts
        rejects.update(problem.rejects)

        again = generate(template, seed)
        if [q.answer for q in again.questions] != [q.answer for q in problem.questions]:
            errors.append(f"seed={seed}: 同じ種なのに別の問題になりました")

        for index, question in enumerate(problem.questions):
            answers.setdefault(index, set()).add(question.answer)
            if question.choices is None:
                written[index] = written.get(index, 0) + 1
                continue
            if question.answer not in question.choices:
                errors.append(f"seed={seed} 設問{index + 1}: 正解が選択肢にありません")
            if len(set(question.choices)) != len(question.choices):
                errors.append(f"seed={seed} 設問{index + 1}: 選択肢が重複しています")
            expected = 2 if set(question.choices) <= {"true", "false"} else 4
            if len(question.choices) != expected:
                errors.append(f"seed={seed} 設問{index + 1}: 選択肢が{len(question.choices)}個です")

    if made:
        rate = made / attempts
        if rate < MIN_ACCEPT_RATE:
            top = "、".join(f"{reason}（{n}）" for reason, n in rejects.most_common(2))
            warnings.append(f"採用率が低いです（{rate:.0%}）。主な理由: {top}")
        for index, seen in answers.items():
            kind = question_types[index]
            if kind != "fill_blank" and len(seen) < MIN_DISTINCT_ANSWERS and seen != {"true", "false"}:
                warnings.append(f"設問{index + 1}（{kind}）: 答えが{len(seen)}種類しかありません")
        for index, count in written.items():
            warnings.append(
                f"設問{index + 1}（{question_types[index]}）: {count}/{made}問が記述式になりました")
        summary = f"{made}/{runs}問を生成、採用率 {rate:.0%}"
    else:
        summary = "1問も生成できませんでした"
    return errors, warnings, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="問題テンプレートを検査する")
    parser.add_argument("paths", nargs="*", help="テンプレートのファイルかフォルダ（省略時は templates/）")
    parser.add_argument("-n", "--runs", type=int, default=200, help="1テンプレートあたりの生成数")
    args = parser.parse_args()

    targets: list[Path] = []
    for raw in args.paths or [str(ROOT / "templates")]:
        path = Path(raw)
        targets.extend(sorted(path.rglob("*.yaml")) if path.is_dir() else [path])
    if not targets:
        print("テンプレートが見つかりません")
        return 1

    failed = 0
    ids: dict[str, Path] = {}
    for path in targets:
        errors, warnings, summary = check_template(path, args.runs)
        try:
            template_id = load_template(path).id
            if template_id in ids:
                errors.append(f"id「{template_id}」が {ids[template_id].name} と重複しています")
            ids[template_id] = path
        except (GijiError, OSError, ValueError):
            pass
        status = "NG" if errors else ("注意" if warnings else "OK")
        print(f"[{status}] {path.name}  {summary}")
        for message in errors:
            print(f"    誤り: {message}")
        for message in warnings:
            print(f"    警告: {message}")
        failed += bool(errors)

    print(f"\n{len(targets)}件中 {len(targets) - failed}件が合格")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
