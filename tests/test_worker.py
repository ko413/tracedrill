"""会員の確認・B案（worker/ と site/static/member-b.js）のテストを、pytest からまとめて動かす。

中身のテストは Node で書いてある（Workers と同じ JavaScript の実行環境で確かめるため）。Node がなければ飛ばす。
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
node = pytest.mark.skipif(not shutil.which("node"), reason="node がありません")


def run_node(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)


def node_test_counts(output: str) -> tuple[int, int]:
    """node --test の出力から（通った数, 失敗した数）を読む。

    Node の版によって、まとめの行の頭が「# pass 34」（TAP 形式）だったり「ℹ pass 34」（spec 形式）だったりするので、
    行の頭の記号は問わない（「ℹ」は文字の仲間に分類され、\\W では拾えないので、空白までを読み飛ばす）。見つからなければ -1。
    """
    def count(word: str) -> int:
        found = re.findall(rf"^(?:\S+[ \t]+)?{word}[ \t]+(\d+)[ \t]*$", output, re.M)
        return int(found[-1]) if found else -1
    return count("pass"), count("fail")


def test_node_test_summary_is_read_in_both_output_styles():
    tap = "ok 34 - x\n1..34\n# tests 34\n# suites 0\n# pass 34\n# fail 0\n# cancelled 0\n"
    spec = "✔ x (1.2ms)\nℹ tests 34\nℹ suites 0\nℹ pass 33\nℹ fail 1\nℹ cancelled 0\n"
    assert node_test_counts(tap) == (34, 0) and node_test_counts(spec) == (33, 1)
    assert node_test_counts("何も出なかった") == (-1, -1)


@node
def test_worker_tests_pass():
    # 出力の形式を TAP に固定する（Node の版や、端末かどうかで既定の形式が変わるため）
    done = run_node("--test", "--test-reporter=tap", "worker/test/worker.test.js")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
    passed, failed = node_test_counts(done.stdout)
    assert passed >= 30 and failed == 0, done.stdout[-1500:]


@node
def test_site_module_for_plan_b_works_alone_and_beside_the_passphrase_module():
    done = run_node("tests/node_member_b_check.js")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
    result = json.loads(done.stdout)
    assert all(result.values()), result


def test_worker_source_and_config_hold_no_secrets():
    """秘密の値は env から受け取る。コードと設定ファイルには、名前しか出てこない。"""
    source = (ROOT / "worker" / "src" / "index.js").read_text(encoding="utf-8")
    config = (ROOT / "worker" / "wrangler.toml").read_text(encoding="utf-8")
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "MAIL_API_KEY"):
        assert f"env.{name}" in source and name not in config
    assert not re.search(r"(sk|rk)_(live|test)_|whsec_[0-9A-Za-z]", source + config)
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert ".dev.vars" in ignore and "node_modules/" in ignore and ".wrangler/" in ignore
