"""会員向けコンテンツ（tools/members.py と site/static/member.js）のテスト。"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

pytest.importorskip("cryptography")
import members  # noqa: E402

PRIVATE_TEMPLATE = """
id: secret-sum-001
title: 会員だけの合計
level: 3
access: member
pace: standard
tags: [for]
description: 関数 total は 1 から n までの和に k を足して返す。
params:
  n: {type: int, range: [3, 9]}
  k: {type: int, range: [1, 9]}
source: |
  ○整数型: total(整数型: n)
    整数型: s ← ${k}
    整数型: i
    for (i を 1 から n まで 1 ずつ増やす)
      s ← s ＋ i   // @add
    endfor
    return s
call: "total(${n})"
questions:
  - {type: return_value}
  - {type: var_at_line, line: add, var: s, pass: random}
explanation: |
  戻り値は ${result} です。
"""


@pytest.fixture()
def paths(tmp_path):
    public_templates = tmp_path / "templates"
    public_templates.mkdir()
    for name in ("loop-sum-001", "digit-sum-001", "max-index-001", "tally-001"):
        shutil.copy(ROOT / "templates" / "basic" / f"{name}.yaml", public_templates)
    p = members.Paths(private=tmp_path / "private", public=tmp_path / "public",
                      templates=public_templates, problems=tmp_path / "problems")
    p.private_templates.mkdir(parents=True)
    (p.private_templates / "secret-sum-001.yaml").write_text(PRIVATE_TEMPLATE, encoding="utf-8")
    return p


def test_sample_uses_public_templates_only_and_is_plaintext(paths):
    bundle = members.cmd_sample(paths, count=4)
    assert len(bundle["questions"]) == 4
    assert "secret-sum-001" not in {q["template_id"] for q in bundle["questions"]}
    assert json.loads(paths.sample.read_text(encoding="utf-8"))["id"] == "sample"
    with pytest.raises(members.MemberError):          # 作り直さない
        members.cmd_sample(paths, count=4)


def test_mock_is_deterministic_numbered_and_never_repeats_a_question(paths):
    first = members.cmd_mock(paths, "2026-11", count=5)
    second = members.cmd_mock(paths, "2026-11", count=5)
    assert (first["id"], second["id"]) == ("mock-001", "mock-002")
    assert first["title"].startswith("第1回") and second["title"].startswith("第2回")
    assert "secret-sum-001" in {q["template_id"] for q in first["questions"]}     # 先行公開中の題材も出る
    seen = [(q["source"], q["call"]) for b in (first, second) for q in b["questions"]]
    assert len(seen) == len(set(seen))
    # 1回の模試で同じアルゴリズムは1問だけ。本番形式（4〜6択）で、答えは選択肢の中にある
    for bundle in (first, second):
        ids = [q["template_id"] for q in bundle["questions"]]
        assert len(ids) == len(set(ids))
        for q in bundle["questions"]:
            assert 4 <= len(q["choices"]) <= 6 and q["answer"] in {c["label"] for c in q["choices"]}
            assert "giji-code" in q["program_html"] and "giji-trace" in q["review_html"]


def test_publish_encrypts_everything_and_keeps_plaintext_out_of_public(paths):
    members.cmd_mock(paths, "2026-11", count=5)
    members.cmd_early(paths, "secret-sum-001", "2026-11")
    result = members.cmd_publish(paths, "2026-11")
    assert result["changed"] and sorted(result["added"]) == ["early-secret-sum-001", "mock-001"]

    public_text = "".join(p.read_text(encoding="utf-8") for p in paths.public.rglob("*.json"))
    assert "会員だけの合計" not in public_text.replace("先行公開：会員だけの合計", "")   # 題名は目次に出す。中身は出さない
    assert "total(" not in public_text and result["passphrase"] not in public_text

    ring = json.loads(paths.keyring.read_text(encoding="utf-8"))
    keys = members.open_keyring(result["passphrase"].lower().replace("-", " "), ring)["keys"]   # 入力のゆれを吸収
    import base64
    for bundle_id, key in keys.items():
        box = json.loads((paths.data / f"{bundle_id}.json").read_text(encoding="utf-8"))
        assert json.loads(members.decrypt(base64.b64decode(key), box))["id"] == bundle_id
    with pytest.raises(Exception):
        members.open_keyring("AAAA-BBBB-CCCC-DDDD", ring)


def test_new_month_changes_passphrase_but_backnumbers_stay_readable_and_untouched(paths):
    members.cmd_mock(paths, "2026-11", count=5)
    november = members.cmd_publish(paths, "2026-11")
    old_file = (paths.data / "mock-001.json").read_bytes()
    old_ring = paths.keyring.read_bytes()

    again = members.cmd_publish(paths, "2026-11")                 # 同じ月にもう一度 → 何も変わらない
    assert not again["changed"] and again["passphrase"] == november["passphrase"]
    assert paths.keyring.read_bytes() == old_ring

    members.cmd_mock(paths, "2026-12", count=5)
    december = members.cmd_publish(paths, "2026-12")
    assert december["changed"] and december["passphrase"] != november["passphrase"]
    assert december["added"] == ["mock-002"]
    assert (paths.data / "mock-001.json").read_bytes() == old_file        # 公開済みのファイルは書き換えない

    ring = json.loads(paths.keyring.read_text(encoding="utf-8"))
    assert set(members.open_keyring(december["passphrase"], ring)["keys"]) == {"mock-001", "mock-002"}   # バックナンバーも開く
    with pytest.raises(Exception):                                # 先月の合言葉では今月の鍵束を開けない
        members.open_keyring(november["passphrase"], ring)
    index = json.loads(paths.index.read_text(encoding="utf-8"))
    assert [b["id"] for b in index["bundles"]] == ["mock-002", "mock-001"]        # 新しい月が上


def test_release_moves_template_to_public_and_marks_the_drill(paths):
    members.cmd_early(paths, "secret-sum-001", "2026-11")
    target = members.cmd_release(paths, "secret-sum-001")
    assert target.exists() and "access: free" in target.read_text(encoding="utf-8")
    assert not (paths.private_templates / "secret-sum-001.yaml").exists()
    members.cmd_publish(paths, "2026-12")
    index = json.loads(paths.index.read_text(encoding="utf-8"))
    assert index["bundles"][0]["public_path"] == "/algo/secret-sum-001/"


def test_browser_side_script_opens_what_python_encrypted(paths):
    """member.js を Node で動かし、実際の鍵束とファイルを開く（ブラウザと同じ Web Crypto）。"""
    if not shutil.which("node"):
        pytest.skip("node がありません")
    members.cmd_mock(paths, "2026-11", count=5)
    result = members.cmd_publish(paths, "2026-11")
    done = subprocess.run(
        ["node", str(ROOT / "tests" / "node_member_check.js"), str(paths.public), result["passphrase"],
         "mock-001", str(ROOT / "site" / "static" / "member.js")],
        capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["before"] is None and out["wrong"] is False and out["ok"] is True
    assert out["ids"] == ["mock-001"] and out["count"] == 5 and out["after"] is None


def test_private_folder_is_ignored_by_git_and_venv_line_is_kept():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "private/" in lines and ".venv/" in lines


def test_recover_restores_keys_and_bundles_from_public_files(paths):
    original = members.cmd_mock(paths, "2026-11", count=5)
    result = members.cmd_publish(paths, "2026-11")
    shutil.rmtree(paths.bundles)
    paths.keys.unlink()
    paths.passphrase.unlink()
    with pytest.raises(members.MemberError):
        members.cmd_recover(paths, "AAAA-BBBB-CCCC-DDDD")
    assert members.cmd_recover(paths, result["passphrase"]) == ["mock-001"]
    assert json.loads((paths.bundles / "mock-001.json").read_text(encoding="utf-8")) == original
    # 復旧のあとも、同じ月なら合言葉は変わらず、次の模試を足せる
    members.cmd_mock(paths, "2026-11", count=5)
    again = members.cmd_publish(paths, "2026-11")
    assert again["passphrase"] == result["passphrase"] and again["added"] == ["mock-002"]


def test_single_passphrase_opens_only_that_mock_and_adds_files_only(paths):
    """単品用の合言葉：その回の鍵だけを入れた鍵束を足す。暗号化済みの模試にも会員用の鍵束にも触らない。"""
    members.cmd_mock(paths, "2026-11", count=5)
    members.cmd_mock(paths, "2026-11", count=5)
    with pytest.raises(members.MemberError):               # 公開前の回には作れない
        members.cmd_single(paths, "mock-001")
    monthly = members.cmd_publish(paths, "2026-11")
    before = {p.name: p.read_bytes() for p in paths.data.glob("*.json")}
    ring_before = paths.keyring.read_bytes()

    single = members.cmd_single(paths, "mock-001", url="https://note.example/n/abc")
    assert single["changed"] and single["passphrase"] != monthly["passphrase"]
    assert {p.name: p.read_bytes() for p in paths.data.glob("*.json")} == before       # 既存のファイルはそのまま
    assert paths.keyring.read_bytes() == ring_before

    ring = json.loads((paths.single / "mock-001.json").read_text(encoding="utf-8"))
    assert list(members.open_keyring(single["passphrase"], ring)["keys"]) == ["mock-001"]   # この回の鍵だけ
    with pytest.raises(Exception):
        members.open_keyring(monthly["passphrase"], ring)
    with pytest.raises(Exception):                         # 単品の合言葉では、会員用の鍵束は開かない
        members.open_keyring(single["passphrase"], json.loads(paths.keyring.read_text(encoding="utf-8")))

    index = {b["id"]: b for b in json.loads(paths.index.read_text(encoding="utf-8"))["bundles"]}
    assert index["mock-001"]["single"] is True and index["mock-001"]["single_url"] == "https://note.example/n/abc"
    assert "single" not in index["mock-002"]
    assert single["passphrase"] not in "".join(p.read_text(encoding="utf-8") for p in paths.public.rglob("*.json"))

    # もう一度実行しても、月が替わっても、単品用の合言葉は変わらない。目次の印も残る
    assert members.cmd_single(paths, "mock-001")["passphrase"] == single["passphrase"]
    single_file = (paths.single / "mock-001.json").read_bytes()
    members.cmd_publish(paths, "2026-12")
    assert (paths.single / "mock-001.json").read_bytes() == single_file
    index = {b["id"]: b for b in json.loads(paths.index.read_text(encoding="utf-8"))["bundles"]}
    assert index["mock-001"]["single"] is True
    # 作り直すと変わる（漏れたとき用）
    renewed = members.cmd_single(paths, "mock-001", new_passphrase=True)
    assert renewed["passphrase"] != single["passphrase"] and renewed["url"] == "https://note.example/n/abc"


def test_browser_side_script_handles_single_passphrase(paths):
    if not shutil.which("node"):
        pytest.skip("node がありません")
    members.cmd_mock(paths, "2026-11", count=5)
    members.cmd_mock(paths, "2026-11", count=5)
    monthly = members.cmd_publish(paths, "2026-11")
    single = members.cmd_single(paths, "mock-002")
    done = subprocess.run(
        ["node", str(ROOT / "tests" / "node_member_check.js"), str(paths.public), monthly["passphrase"],
         "mock-001", str(ROOT / "site" / "static" / "member.js"), single["passphrase"], "mock-002"],
        capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["wrong"] is False and out["singleOk"] is True
    assert out["singleIds"] == ["mock-002"] and out["singleTitle"] == "mock-002"       # 単品ではその回だけ
    assert out["singleExpired"] is False and out["afterSingle"] is None
    assert out["ok"] is True and out["ids"] == ["mock-001", "mock-002"]                # 会員は全部
