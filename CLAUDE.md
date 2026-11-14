# CLAUDE.md — このリポジトリで作業するときのルール

擬似言語トレースドリル（https://tracedrill.com）のリポジトリです。作業の前に、必ずこのファイルを最後まで読んでください。
迷ったら、変更せずに運営者（Zerrrr）に確認します。返答は日本語で、短く、選択肢を示してから進めます。

## 絶対に守ること（6つ）

1. **`problems/` の既存ファイルを変更・削除・改名しない。** 公開済みの問題は URL と中身を固定している。
   足してよいのは新しいファイルだけで、それも手で書かず `python build.py` に作らせる。
   テンプレートを直しても既存の問題は変わらない（新しく作る問題にだけ反映される）。それが正しい動作。
2. **`site/members/data/` の既存ファイルと `private/bundles/` の既存ファイルも変更・削除しない。** 配布済みの模試は固定。
3. **`.gitignore` の `.venv/` と `private/` の行を消さない。**
4. **秘密をリポジトリに入れない。** `private/`（模試の平文・鍵・合言葉・先行公開中のテンプレート）はコミットしない。
   合言葉、鍵、API キー、Stripe や Cloudflare のシークレットを、コード・設定・コミットメッセージ・Issue・PDCA_LOG.md に書かない。
5. **変更したら、コミットの前に次の2つを通す。** 通らないままコミット・push しない。
   ```
   python -m pytest -q
   python build.py --frozen
   ```
   `--frozen` が「problems/ に保存されていない問題があります」で止まったら、`python build.py`（--frozen なし）を1回実行して
   新しい問題を作り、`problems/` の**新しいファイルだけ**が増えたことを `git status` で確かめてからコミットする。
6. **1回の作業で変えるのは1つのことだけ。** 終わったら `PDCA_LOG.md` に1行足す。

## してはいけないこと

- `git push --force`、履歴の書換え、`git clean`、`rm -rf` で `problems/`・`private/`・`site/members/` を消すこと。
- テストを通すために、テストを消す・緩める・skip にすること（テストが間違っていると考えたら、理由を添えて確認する）。
- リポジトリを private にする前提の変更（GitHub Pages の無料枠を使うため public のまま）。
- 運営者の氏名・住所・電話番号・個人のメールアドレスをサイトやリポジトリに書くこと。
- IPA の試験問題の文章・プログラムを写すこと（問題はすべて自作のテンプレートから作る）。
- 営業メールや外部への投稿を自動で送ること（集客は検索・note・X からの流入だけ）。
- 新しい有料サービス・外部サービスへの登録や、費用が発生する設定。

## 全体のしくみ（30秒で）

- `giji/` … 擬似言語の処理系（字句解析 → 構文解析 → 実行とトレース）と、問題の生成（generator.py）、本番形式（exam.py）。
- `templates/basic/*.yaml` … 問題のテンプレート（無料公開）。1ファイル＝1問題セット。
- `private/templates/*.yaml` … 会員に先行公開中のテンプレート（リポジトリ外）。
- `problems/<テンプレートid>/NN.json` … 生成して固定した問題。ページはここから作る。
- `build.py` … 静的サイトを `dist/` に出力。`site.yaml` が設定、`site/templates/` が HTML の型、`site/static/` が CSS と JS。
- `tools/members.py` … 会員向けの模試・先行公開ドリルを作り、暗号化して `site/members/` に置く。
- `site/static/member.js` … 会員の確認（今は合言葉）。確認方法を変えるときはこのファイルだけ差し替える。
- `site/static/mock.js` … 模試の画面。
- 公開は GitHub Actions（`.github/workflows/pages.yml`）。main に push すると、テスト → `build.py --frozen` → GitHub Pages。

設計の理由は `README.md` の「設計上の判断」、毎月の作業と障害対応は `OPERATIONS.md` にある。

## よくある作業の手順

### A. 文言・見た目を直す（content/、site/templates/、site/static/）
1. 直す → `python build.py --no-ogp` → `python -m http.server -d dist` で確認。
2. 「絶対に守ること 5」の2つを通す → コミット。

### B. テンプレートを足す・直す
1. `templates/basic/` に YAML を書く（書き方は README.md「テンプレートの書き方」。既存の似たものを写して直すのが早い）。
2. `python tools/validate_templates.py templates/basic/新しいファイル.yaml -n 200` で **[OK]** か **[注意]** になるまで直す。
   - 「空欄補充: …でも同じ結果になる」→ その誤答（distractors）を別のものに替える。
   - 「採用率」が 20% 未満 → params の範囲か quality の条件を見直す。
3. `content/algo/<id>.md` に解説（何をしているか／トレースのコツ／よくある間違い）を書く。
4. `python build.py` で問題を作って固定 → `git status` で `problems/` に新しいフォルダだけが増えたことを確かめる。
5. 「絶対に守ること 5」の2つを通す → コミット。
- 既存テンプレートを直すとき：公開済みの問題は変わらない。値の範囲を狭めると `--frozen` が止まることがあるので、広げる方向で直す。

### C. 毎月の模試と先行公開（月初・約30分）
`OPERATIONS.md` の「毎月の作業」をその順番どおりに実行する。要点だけ：
```
python tools/members.py status                         # 今の状態を確認
python tools/members.py mock --month YYYY-MM           # 今月の模試を1回分作る
python tools/members.py release 先月の先行公開のid       # 先行公開を終えて無料公開へ（1か月たったもの）
python build.py                                        # ↑で無料公開したテンプレートの問題を作って固定
python tools/members.py early 今月の先行公開のid --month YYYY-MM
python tools/members.py publish --month YYYY-MM        # 暗号化。新しい合言葉が表示される
python -m pytest -q && python build.py --frozen
git add site/members problems templates content && git commit && git push
```
- `publish` が表示する合言葉は、**運営者が note の会員限定記事に貼る**。Claude Code は合言葉をどこにも書き写さない。
- push して公開された時点で、先月の合言葉は使えなくなる。note の記事の更新は公開の直後に行う（運営者の作業）。

### D. 週1回の改善（PDCA）
1. 運営者から、その週の数字（Cloudflare Web Analytics、note、Search Console）をもらう。数字を推測で作らない。
2. `PDCA_LOG.md` の直近の行を読み、前回の変更の結果を「結果」欄に書く。
3. 改善案を2〜3個、効果の見込みと作業量つきで示し、運営者が選んだ1つだけを実施する。
4. 実施 → テストとビルド → コミット → `PDCA_LOG.md` に1行足す。

## 判断に迷いやすい点

- `site.yaml` は運営者の手元の版が正しい（note の URL、計測のトークンなどが入っている）。項目を足すとき以外は書き換えない。
- 顔文字は `site/static/kaomoji.js` にだけ書く（全部で10個前後）。出す場所は、正解・不正解の表示（練習形式と今日の1問）、
  今日の1問の見出し、ヒントのボタン、サンプル模試の採点結果、トップの説明文の最後、の5か所だけ。
  問題文・選択肢・解説・トレース表・本番形式・会員ページには出さない。タイ文字・アラビア文字・結合記号を含む顔文字は、
  端末によって崩れるので、使う前に運営者に実機で確かめてもらう。

- 擬似言語の表記（記号、キーワード、「の商」「未定義」など）は `giji/notation/fe-2023.yaml` にまとめてある。
  表記を変えるときは、IPA が公開している問題冊子の「擬似言語の記述形式」を運営者に確認してもらう。記憶で決めない。
- 仕様にない動作（負の数の割り算、未定義の扱いなど）は README.md「決めた動作」と「設計上の判断」に従う。
- 新しいテンプレートで「が 未定義でない」は使わない（IPA の公開問題で確認できなかった書き方）。
  `if (… が 未定義)` と `繰返し処理を終了する` の組合せで書く。例：`private/templates/list-traverse-001.yaml`。
- 処理系（`giji/`）を直すときは、直す前後で `python build.py --frozen --no-ogp --out /tmp/a` と `/tmp/b` を作り、
  `diff -r /tmp/a /tmp/b` が空であること（公開済みページが1文字も変わらないこと）を確かめる。
- 大きな変更（処理系の拡張、会員の確認方法の変更、ページ構成の変更）は、設計を先に文章で示して了承を得てから実装する。
