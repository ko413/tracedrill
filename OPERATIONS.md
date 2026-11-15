# 運用手順書

会員向け（模試・先行公開）の運用と、困ったときの対処をまとめています。
ここに書いてある作業は、特別な AI がなくても、コマンドをこの順に打てば終わるようにしてあります。

- 会員の仕組み：note のメンバーシップ（月額980円）＋サイトの合言葉
- 会員が解けるもの：毎月の模試、**過去のすべての模試（バックナンバー）**、先行公開ドリル
- かかる時間：毎月30〜40分

## 1. しくみ（知っておくこと）

| もの | 置き場所 | リポジトリに入れる？ |
|---|---|---|
| 模試・ドリルの中身（平文） | `private/bundles/` | **入れない** |
| 模試ごとの鍵 | `private/keys.json` | **入れない** |
| 今月の合言葉と履歴 | `private/passphrase.json` | **入れない** |
| 先行公開中のテンプレート | `private/templates/` | **入れない** |
| 暗号化した模試・ドリル | `site/members/data/` | 入れる |
| 目次（題名と問題数だけ） | `site/members/index.json` | 入れる |
| 鍵束（合言葉で開く。中身は模試ごとの鍵） | `site/members/keyring.json` | 入れる |
| 無料のサンプル模試（平文） | `site/members/sample.json` | 入れる |

- 会員は合言葉を入力する → ブラウザの中で鍵束を開く → 模試ごとの鍵で中身を開く。合言葉はどこにも送られません。
- 合言葉を変えると、鍵束だけが作り直されます。新しい鍵束には**これまでの全部の模試の鍵**が入るので、
  新しい合言葉ひとつでバックナンバーもすべて開きます。
- 模試の中身と暗号化したファイルは、一度作ったら作り直しません（`problems/` と同じ考え方）。

### この方式の限界（正直に）

- 合言葉を会員が他人に教えることは防げません。月1回の変更で、広がる範囲を1か月に抑えるだけです。
- 退会した人も、会員だったときの合言葉と当時の鍵束（公開リポジトリの履歴に残る）があれば、
  **その時点までの模試**は開けます。退会後に追加した模試は開けません。
- どちらも、会員が20〜30人になる前に Stripe＋Workers（B案）へ移れば解消します。

## 2. `private/` の控え（最初に必ず）

`private/` はリポジトリに入らないので、パソコンが壊れると失われます。次のどちらかで控えを取ってください。

- GitHub に**非公開**のリポジトリをもう1つ作り、`private/` の中身だけを入れる（無料）。
- クラウドのドライブ（iCloud、Google ドライブなど）に `private/` フォルダを毎月コピーする。

なくしたときは「5. 困ったとき」の「private/ をなくした」を見てください。先行公開中のテンプレート以外は取り戻せます。

## 3. 会員サービスを始める日（1回だけ）

用意済みのもの：サンプル模試、第1回・第2回の模試、先行公開ドリル2本（キュー、かっこの対応）、最初の合言葉。

1. note のメンバーシップが承認されたら、プランのページの URL を `site.yaml` の `members.note_url` に入れる。
2. 確認する。
   ```
   python tools/members.py status        # 合言葉と、公開用に暗号化済みの一覧が出る
   python -m pytest -q
   python build.py --frozen
   python -m http.server -d dist         # http://localhost:8000/members/ で合言葉を入れて開けるか確かめる
   ```
3. コミットして push する（`private/` が含まれていないことを `git status` で確かめる）。
   ```
   git add -A
   git status                            # private/ が一覧に出ていないこと
   git commit -m "会員ページとサンプル模試を追加"
   git push
   ```
4. 公開されたら https://tracedrill.com/members/ で、合言葉を入れて模試が開くことを確かめる。
5. note に**会員限定**の記事「今月の合言葉」を作り、`status` に出た合言葉を貼る（文面は `publish` 実行時にも表示されます）。
   この記事は毎月書き換えて使います。**無料部分に合言葉を書かない**こと。
6. note のプラン説明に、特典（毎月の模試・バックナンバー全部・先行公開）と https://tracedrill.com/mock/sample/ を書く。

開始が12月以降にずれた場合：最初の `publish` をもう一度 `--month 2026-12` で実行すれば、12月の合言葉になります。

## 4. 毎月の作業（月初・30〜40分）

`YYYY-MM` はその月（例 `2026-12`）。上から順に実行します。

```
# 0. 状態の確認と、private/ の控え
python tools/members.py status

# 1. 今月の模試を1回分作る（第N回の番号は自動）
python tools/members.py mock --month YYYY-MM

# 2. 先月の先行公開テンプレートを、無料公開に切り替える（公開から1か月たったもの）
python tools/members.py release queue-ring-001          # 例。下の予定表のとおりに
#    → 解説は private/drafts/content/algo/<id>.md から content/algo/ へ移す（下書きがなければ、ほかの解説を写して書く）
python build.py                                         # 無料の問題が作られ、problems/ に固定される

# 3. 今月の先行公開ドリルを作る（月2本まで）
python tools/members.py early list-traverse-001 --month YYYY-MM      # 例

# 4. 暗号化して公開用フォルダに置く。新しい合言葉が表示される（控えておく）
python tools/members.py publish --month YYYY-MM

# 5. 検査してから公開
python -m pytest -q
python build.py --frozen
git add site/members problems templates content
git status                                              # private/ が出ていないこと
git commit -m "YYYY-MM の模試と先行公開"
git push
```

6. 公開されたら（2〜3分後）、https://tracedrill.com/members/ に**新しい合言葉**を入れて、今月の模試が開くことを確かめる。
7. **すぐに** note の会員限定記事を新しい合言葉に書き換える。push した時点で先月の合言葉は使えなくなるので、
   6 と 7 は続けて行います（会員が開けない時間を短くするため）。
8. `PDCA_LOG.md` に1行足し、`private/` の控えを取る。

### 先行公開の予定

月2本を会員に先に出し、1か月後に無料公開します。

| 月 | 会員に先行公開 | 無料公開に切り替え |
|---|---|---|
| 開始月 | queue-ring-001（キュー）、bracket-match-001（かっこの対応） | — |
| 2か月目 | list-traverse-001（リストをたどる）、list-insert-001（リストへの挿入） | queue-ring-001、bracket-match-001 |
| 3か月目 | tree-inorder-001（二分木をたどる）、graph-reach-001（たどれる頂点を数える） | 2か月目の2本 |
| 4か月目 | hash-probe-001（ハッシュ表への格納）、heap-insert-001（ヒープへの挿入） | 3か月目の2本 |
| 5か月目 | quick-partition-001（クイックソートの分割）、list-delete-001（リストからの削除） | 4か月目の2本 |
| 6か月目 | tree-height-001（二分木の高さ）、sieve-001（エラトステネスのふるい） | 5か月目の2本 |
| 7か月目以降 | 新しく作ったテンプレート（`private/templates/` に置く） | 前月の2本 |

- 新しい会員向けテンプレートは、まず `private/templates/` に置きます（`access: member`）。
  検査は `python tools/validate_templates.py private/templates/ファイル.yaml -n 200`。
- 先行公開する題材がない月は、手順 2・3 を飛ばしてかまいません。模試だけでも成立します。

### 模試の中身について

- 1回＝16問・80分。アルゴリズムが重ならないように選び、やさしい順に並べます。半分近くは中級以上から選びます。
- 公開中の無料問題や、過去の模試と同じ問題（同じプログラム・同じ値）は出ません。
- テンプレートが増えるほど、模試の題材も自動で増えます。

## 4-2. 模試を1回分だけ売る（単品用の合言葉）

月額に入らない人向けに、模試を1回ずつ売れます（note の有料記事など）。必要なときだけ行います。

```
python tools/members.py single mock-001 --url https://note.com/…（有料記事のURL）
python -m pytest -q
python build.py --frozen
git add site/members && git status && git commit -m "第1回の単品販売" && git push
```

- 表示された合言葉を、有料記事の**有料部分**に貼ります（文面も表示されます）。URL がまだないときは `--url` なしで作り、
  記事を作ってからもう一度 `--url` を付けて実行します（合言葉は変わりません）。
- この合言葉で開けるのは、その回だけです。月が替わっても変わりません。買った人は、記事を読み返せばいつでも開けます。
- 足されるのは `site/members/single/<名前>.json` と目次の印だけです。暗号化済みの模試と会員用の鍵束は変わりません。
- 会員ページの一覧では、まだ開けていない人に「この回だけ購入する（note）」のリンクが出ます。
- 合言葉が漏れたとき：`python tools/members.py single mock-001 --new-passphrase` → 公開 → 有料記事の合言葉を書き換える。
- 単品用の合言葉は `private/singles.json` にあります（`status` でも表示）。`recover` では戻らないので、控えに含めてください。
- 売る回は、発行から1か月以上たった回にすると、会員の価値（新しい回がすぐ解ける）を損ねません。

## 4-3. 数字の見方（模試の開始・採点）

アクセス計測（Cloudflare Web Analytics）はページの閲覧しか数えられないので、模試を始めたとき・採点したときに
アドレスを切り替えて、1回の閲覧として数えています。Cloudflare の画面の「パス」で、次の4つを見ます。

| パス | 意味 |
|---|---|
| `/mock/sample/` | サンプル模試のページを開いた |
| `/mock/sample/started/` | 「始める」を押した |
| `/mock/sample/graded/` | 「採点する」を押した（時間切れを含む） |
| `/members/started/`、`/members/graded/` | 会員の模試・ドリルで同じこと |

- 「開いた → 始めた → 採点した」の割合を、毎週 `PDCA_LOG.md` に書きます。
- 同じ人が開き直すと、もう一度数えられます。おおよその傾向として読みます。
- 数えられているかは、公開後に自分で1回サンプル模試を始めて、5〜10分後に Cloudflare の画面で確かめます。
- やめたいとき：`site/templates/mock.html` と `members.html` の `data-step-base="…"` を消します。

## 5. 困ったとき

| 起きたこと | 対処 |
|---|---|
| 会員から「合言葉が違うと出る」 | ① note の記事の合言葉が最新か（`python tools/members.py status` と見比べる）。② サイトが新しい鍵束で公開されているか（GitHub の Actions が緑か）。③ それでもだめなら、本人に「全部大文字・ハイフンなしでも可」と伝える（全角・小文字・空白は自動で直ります）。 |
| 合言葉が外に漏れた・SNS に書かれた | `python tools/members.py publish --month YYYY-MM --new-passphrase` → テスト → ビルド → push → note の記事を書き換える。 |
| `publish` が「鍵が private/keys.json にありません」で止まる | `private/` が欠けています。控えから戻すか、下の「private/ をなくした」を実行。 |
| `private/` をなくした | `python tools/members.py recover 今の合言葉`（note の記事にある合言葉）。鍵と模試の中身が戻ります。先行公開中のテンプレートは控えから戻すか、書き直します。 |
| `mock` が「16問そろいませんでした」 | テンプレートが足りません。通常は起きません（今は33種類）。`templates/basic/` を消していないか確かめる。 |
| `mock` や `early` が「すでにあります」 | 作り直しはしません。もう1回分ほしいときは、もう一度 `mock` を実行すれば次の回（第N+1回）ができます。 |
| `build.py --frozen` が「保存されていない問題があります」 | `python build.py`（--frozen なし）を1回実行 → `problems/` の新しいファイルをコミット。 |
| Actions が赤い（公開されない） | Actions の画面でどの段階かを見る。テストなら手元で `python -m pytest -q`、ビルドなら `python build.py --frozen` を実行して同じエラーを出し、直す。直るまで、サイトは前の状態のまま動き続けます。 |
| 間違って `private/` をコミット・push した | すぐに合言葉を変える（上の「漏れた」と同じ）。その回までの模試の中身は公開されたものとして扱い、次の月から新しい模試で価値を保つ。履歴の書換え（force push）は自分では行わず、落ち着いて手順を調べてから。 |
| 会員から返金・解約の相談 | 支払いと解約は note の中で行われます。note のヘルプの手順を案内します。 |
| 模試の問題に誤りの指摘 | 配布済みの模試は書き換えません。note の会員限定記事に訂正を書き、原因のテンプレートを直します（次回以降の問題に反映）。 |

## 6. 確認方法を B案（Stripe＋Cloudflare Workers）に移すとき

会員が20〜30人になる前が目安です。変えるのは「鍵束の渡し方」だけで、模試の中身・暗号化・画面はそのまま使います。

- 今：`site/static/member.js` が、合言葉で `keyring.json` を開いて鍵の表を得る。
- B案：`member.js` の `keys()` と `login()` を、「Workers にログイン状態を問い合わせ、会員なら鍵の表を受け取る」に差し替える。
  `keyring.json` は公開をやめ、鍵の表は Workers のシークレットに置く。
- `mock.js`、`tools/members.py` の `mock`・`early`、`site/members/data/` は変更不要。

詳しい手順は `MIGRATION_B.md` にあります。
