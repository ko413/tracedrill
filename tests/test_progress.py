"""学習記録（site/static/progress.js）のテスト。中身は Node で確かめる。Node がなければ飛ばす。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not shutil.which("node"), reason="node がありません")
def test_learning_record_works_with_and_without_storage():
    done = subprocess.run(["node", "tests/node_progress_check.js"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-1000:]
    result = json.loads(done.stdout)
    assert len(result) >= 20 and all(result.values()), result


def test_learning_record_stores_nothing_but_id_result_and_time():
    """保存するのは識別子・結果・日時だけ。合言葉や問題の中身に触れる処理が入っていないこと。"""
    source = (ROOT / "site" / "static" / "progress.js").read_text(encoding="utf-8")
    assert source.count("setItem(") == 2 and "sessionStorage" not in source and "cookie" not in source
    assert "{ r: correct ? 'ok' : 'ng', t: Math.floor(Date.now() / 1000) }" in source
    for word in ("member-passphrase", "MemberAuth", "fetch(", "XMLHttpRequest", "sendBeacon"):
        assert word not in source, word
