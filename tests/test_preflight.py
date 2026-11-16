"""tools/preflight.py（コミット前の確認）のテスト。小さな git リポジトリを作って確かめる。"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import preflight  # noqa: E402


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git がありません")
    (tmp_path / "problems" / "a-001").mkdir(parents=True)
    (tmp_path / "problems" / "a-001" / "01.json").write_text("{}", encoding="utf-8")
    (tmp_path / "site" / "members" / "data").mkdir(parents=True)
    (tmp_path / "site" / "members" / "data" / "mock-001.json").write_text("{}", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "a-001.yaml").write_text("id: a-001\n", encoding="utf-8")
    (tmp_path / "site.yaml").write_text("name: x\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".venv/\nprivate/\n", encoding="utf-8")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "passphrase.json").write_text(json.dumps(
        {"current": {"month": "2026-12", "passphrase": "ABCD-EFGH-JKMN-PQRS"},
         "history": [{"month": "2026-11", "passphrase": "TUVW-XYZ2-3456-789A"}]}), encoding="utf-8")
    (tmp_path / "private" / "keys.json").write_text(json.dumps({"mock-001": "S0VZS0VZS0VZS0VZS0VZ"}), encoding="utf-8")
    for command in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "first"]):
        subprocess.run(["git", *command], cwd=tmp_path, check=True)
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    return tmp_path


def test_clean_repository_passes(repo):
    changes = preflight.changed_files()
    assert changes == [] and preflight.check_frozen(changes) == [] and preflight.check_ignore() == []
    assert preflight.check_secrets() == [] and preflight.check_notation() == [] and preflight.check_site_yaml(changes) == []


def test_adding_problems_is_fine_but_changing_or_deleting_is_caught(repo):
    (repo / "problems" / "a-001" / "02.json").write_text("{}", encoding="utf-8")              # 追加はよい
    (repo / "site" / "members" / "data" / "mock-002.json").write_text("{}", encoding="utf-8")
    assert preflight.check_frozen(preflight.changed_files()) == []
    (repo / "problems" / "a-001" / "01.json").write_text('{"x": 1}', encoding="utf-8")        # 変更
    (repo / "site" / "members" / "data" / "mock-001.json").unlink()                           # 削除
    problems = preflight.check_frozen(preflight.changed_files())
    assert problems == ["problems/a-001/01.json（変更）", "site/members/data/mock-001.json（削除）"]


def test_renaming_a_published_problem_counts_as_deleting_it(repo):
    subprocess.run(["git", "mv", "problems/a-001/01.json", "problems/a-001/09.json"], cwd=repo, check=True)
    assert "problems/a-001/01.json（削除）" in preflight.check_frozen(preflight.changed_files())


def test_secrets_in_committable_files_are_caught(repo):
    (repo / "PDCA_LOG.md").write_text("今月の合言葉は abcd… ではなく ABCDEFGHJKMNPQRS です\n", encoding="utf-8")   # ハイフンなしでも
    (repo / "notes.txt").write_text("先月: TUVW-XYZ2-3456-789A / 鍵 S0VZS0VZS0VZS0VZS0VZ\n", encoding="utf-8")
    problems = preflight.check_secrets()
    assert "PDCA_LOG.md に 合言葉（2026-12 分） が入っています" in problems
    assert "notes.txt に 合言葉（2026-11 分） が入っています" in problems
    assert "notes.txt に 鍵（mock-001） が入っています" in problems
    assert not any(p.startswith("private/") for p in problems)          # private/ の中は対象外


def test_private_folder_and_gitignore_lines_are_checked(repo):
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    assert ".gitignore に private/ の行がありません" in preflight.check_ignore()
    subprocess.run(["git", "add", "-f", "private/keys.json"], cwd=repo, check=True)
    assert any("git に登録されています" in p for p in preflight.check_ignore())


def test_unconfirmed_notation_and_site_yaml_changes_are_caught(repo):
    (repo / "templates" / "b-001.yaml").write_text("source: |\n  while (p が 未定義でない)\n", encoding="utf-8")
    assert preflight.check_notation() == ["templates/b-001.yaml に「未定義でない」があります"]
    (repo / "site.yaml").write_text("name: y\n", encoding="utf-8")
    assert len(preflight.check_site_yaml(preflight.changed_files())) == 1
