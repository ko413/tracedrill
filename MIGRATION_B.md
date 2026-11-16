# B案への移行（Stripe の定期課金 ＋ Cloudflare Workers）

会員の確認を「note＋合言葉」（A案）から「サイトで入会＋メールでログイン」（B案）に移すための手順です。

**今の状態（2026-11-16）**：コードとテストはできています。**公開はしていません**。サイトは A案のまま動いていて、
`site.yaml` を変えないかぎり、B案のコードはどのページからも読み込まれません。
1月にやることは、下の A〜G の「設定と公開」だけです。

> **確かめていないこと**：本物の Stripe・Cloudflare・メール送信サービスには、一度もつないでいません（偽物を相手にしたテストだけ）。
> 画面の名前、コマンドの書き方、料金、無料枠は変わります。「未検証」と書いた点と各コマンドは、作業の前に公式の説明で確かめてください。
> Claude Code に頼むときは、「`npx wrangler --help` と公式ドキュメントでコマンドを確かめてから」と伝えます。

## 0. 何が変わり、何が変わらないか

| | A案（今） | B案 |
|---|---|---|
| 支払い・解約 | note | Stripe（決済ページと「支払い・解約」ページ） |
| 会員の確認 | 合言葉で鍵束（`keyring.json`）を開く | メールのリンクでログイン → Workers が Stripe の状態を見て、鍵の表を返す |
| 模試の作成（`tools/members.py`）と暗号化の方式 | — | **変わらない** |
| 模試のファイル（`site/members/data/`） | — | **変わらない**（作り直さない） |
| 模試の画面（`mock.js`） | — | 入会ボタン・メール欄・「支払い・解約」が増えるだけ |
| 退会した人 | 古い合言葉で、退会前の模試は開ける | 期間が終わると、どの模試も開けない |

切り替えは `site.yaml` の `members.method` で行います。

| `method` | 動き | いつ使うか |
|---|---|---|
| `passphrase`（既定） | A案だけ。今と同じ | 今 |
| `both` | 合言葉と、サイトでの入会の**両方**が使える | 移行の期間（note の会員が残っている間） |
| `stripe` | サイトでの入会だけ。合言葉の欄は出ない | note を閉じたあと |

`both`・`stripe` にするには、`members.api_url`（Workers の URL）と、`content/tokushoho.md`・`content/privacy.md` が必要です。
どれかが欠けていると、ビルドがエラーで止まります（特商法の表記なしで決済を始めないため）。

## しくみ

```
[サイト tracedrill.com]                  [Workers api.tracedrill.com]              [Stripe]
 入会ボタン ───────────────────────────→ POST /checkout ───────────────────────→ 決済ページ（月額）
 （支払い後に戻る ?joined=…）───────────→ POST /claim   … 支払い済みを確かめ、ログイン済みにする
                                          POST /webhook ←─────────────────────── 契約の変化の通知（署名つき）
                                            └ Stripe の今の状態を読み直して、KV に保存
 メールアドレス ────────────────────────→ POST /login   … 会員なら、15分・1回だけ使えるリンクをメールで送る
 （メールのリンク ?login=…）────────────→ POST /session … ログイン済みにする（Cookie。30日）
 模試の一覧 ────────────────────────────→ GET /keys     … 会員なら鍵の表を返す。会員でなければ返さない
 「支払い・解約」────────────────────────→ POST /portal  → Stripe の管理ページ（カード変更・解約・領収書）
```

- Workers が保存するのは、メールアドレスのハッシュ、Stripe の顧客の番号、契約の状態だけです。メールアドレスそのものとカードの情報は保存しません。
- 支払いに失敗している間（Stripe の状態が `past_due`）は開けません。カードを直して支払えると、また開けます。
- 解約しても、支払い済みの期間の終わりまでは開けます。
- Webhook が届かなくても、12時間以上前の状態のまま鍵は渡しません（Stripe に確かめ直します）。
- コードは `worker/`、サイト側は `site/static/member-b.js`。入口の一覧は `worker/README.md`。

## 秘密の値（リポジトリ・チャットに書かない）

| 名前 | 中身 | 置き場所 |
|---|---|---|
| `STRIPE_SECRET_KEY` | Stripe の制限付きキー（必要な権限は D-2） | Workers のシークレット |
| `STRIPE_WEBHOOK_SECRET` | Webhook の署名を確かめる値（`whsec_…`） | Workers のシークレット |
| `MAIL_API_KEY` | メール送信サービスのキー | Workers のシークレット |
| 鍵の表 | `private/keys.json` の中身 | Workers の KV（`keytable`） |

- 登録するコマンドは、**1行だけで実行**し、値は聞かれてから貼ります（コマンドの中に値を書かない。履歴に残るため）。
- Claude Code には、値を見せません。登録は運営者が自分で行います。
- `python tools/preflight.py` は、Stripe の鍵の形や `.dev.vars` がコミットの対象に入っていると NG にします。

## 1月に決めること（人が決める）

| 決めること | 選択肢・目安 | いつまでに |
|---|---|---|
| 氏名を特商法の表記に出すか | `drafts/legal/tokushoho.md` の「公開前に確かめること 1」。Stripe に問い合わせて決める | A の前 |
| 価格 | 月額980円のままか。note より手数料が低い分（下の「手数料」）を値下げに回すか | C の前 |
| 返金の方針 | 下書きは「返金しない。サイトの不具合のときは返金する」 | B の前 |
| 連絡用のメールアドレス | `info@tracedrill.com` など。受信できること | B の前 |
| メール送信サービス | コードは Resend 向け。別の会社にするなら `worker/src/index.js` の `sendLoginMail` を直す | C の前 |
| 利用規約を作るか | 作れば、決済のときに同意のチェックを必須にできる（`TERMS_URL`）。なくても動く | D の前 |
| 移行の期間 | `both` を何か月続けるか。目安は1〜2か月 | F の前 |
| note の会員への優遇 | 移行した人に1か月無料（Stripe のクーポン）など。なしでもよい | F の前 |
| 単品販売をどちらで売るか | note のまま（`OPERATIONS.md` 4-2）か、Stripe か。Stripe 側はコードあり・画面のボタンは未実装 | 急がない |
| 法人プランの形 | 席数ごとの月額／請求書払い／問合せのみ。未実装（`worker/README.md`） | 問合せが来てから |

## 運営者が確認すること（法律・規約）

| 確かめること | 根拠 |
|---|---|
| 氏名・住所・電話番号は「請求があれば遅滞なく開示」で省略できる。ただし請求が来たら、すぐに開示する | 消費者庁 通信販売広告Q&A Q15・Q17 https://www.no-trouble.caa.go.jp/qa/advertising.html |
| Stripe は、個人事業主の販売事業者名・所在地・電話番号の省略を認めているが、運営統括責任者とメールアドレスには省略の記載がない（**氏名を出さずに審査に通るかは未検証**） | Stripe ヘルプ https://support.stripe.com/questions/how-to-create-and-display-a-commerce-disclosure-page?locale=ja-JP |
| 月額制なので、申込みの最終確認の画面に、価格・毎月の請求・解約の方法が出ていること（決済ページを自分の目で見る） | 消費者庁 通信販売 https://www.no-trouble.caa.go.jp/what/mailorder/ 、Stripe ヘルプ https://support.stripe.com/questions/guidelines-under-the-revised-specified-commercial-transactions-act-to-be-enforced-in-june-2022?locale=ja-JP |
| 支払時期、自動更新の条件、動作環境は、表記から省略できない | 消費者庁 通信販売（省略できる事項の表） |
| プライバシーポリシー：運営者の氏名・住所の扱い、国外の会社への提供（**未検証**） | 個人情報保護委員会のガイドライン https://www.ppc.go.jp/personalinfo/legal/ |
| Stripe で売ってよい商品か（デジタルコンテンツの月額制）。**未検証** | Stripe の利用規約と、禁止・制限されている業種の一覧（Stripe の公式サイトで確認） |
| note の規約：note の会員を外部の決済へ案内してよいか。**未検証** | note の利用規約とヘルプ（公式で確認）。心配なら、案内はサイトの会員ページだけに書く |

`drafts/legal/` の2つの下書きは、法律の専門家が確認したものではありません。

---

## 手順

時間の目安は、A：30分＋審査待ち、B：1時間、C：1時間、D：1〜2時間、E：30分、F：30分。1日でやらず、D までを先に済ませます。

### A. 申し込む（審査に日数がかかるので最初に）

1. `drafts/legal/tokushoho.md` の「公開前に確かめること 1」を読み、Stripe のサポートに氏名の扱いを問い合わせる。
2. Stripe のアカウントを作り、本人確認と入金口座を登録する（フォームには本名・住所・電話番号を入力する。サイトの表記とは別）。
3. 連絡用のメールアドレスを用意する（受信できることを確かめる）。
4. メール送信サービスのアカウントを作り、送信元のドメイン（`tracedrill.com`）を認証する（DNS に SPF・DKIM の行を足す。Cloudflare の DNS の画面）。
   Resend の無料枠は、月3,000通・1日100通・1ドメイン（2026年11月に第三者の記事で確認。**公式の料金ページで再確認**）。
5. Stripe・Cloudflare・GitHub・メール送信サービスの二段階認証を設定する。

### B. 特商法の表記とプライバシーポリシーを公開する

A案のままでも公開できます（Stripe の審査では、表記のページが見られる状態になっている必要があります）。

```
cd ~/giji-trainer
source .venv/bin/activate
git pull
cp drafts/legal/tokushoho.md content/tokushoho.md
cp drafts/legal/privacy.md content/privacy.md
```

1. `content/tokushoho.md` と `content/privacy.md` を開き、【　】をすべて埋める。
2. どちらも、`<!-- ---8<---` の行から下（「公開前に確かめること」）を消す。
3. `content/privacy.md` の「当サイトで入会した場合」は、F で `both` にするまで消しておく（消した部分は `drafts/legal/privacy.md` に残っている）。

```
python tools/preflight.py
git add content/tokushoho.md content/privacy.md
git commit -m "特定商取引法に基づく表記とプライバシーポリシーを追加"
git push
```

`preflight` は、【　】や `---8<---` が残っていると NG にします。公開後、フッターのリンクから2つのページが開くことを確かめます。

### C. Cloudflare と Stripe（テスト環境）を設定する

Node.js が必要です（`node --version` が 20 以上）。

```
cd ~/giji-trainer/worker
npx wrangler login
npx wrangler kv namespace create MEMBERS
```

1. 表示された `id` を、`worker/wrangler.toml` の `id = "【KV の id】"` に入れる。
2. Stripe の**テスト環境**で、商品「擬似言語トレースドリル 会員」と、価格（月額・税込980円・日本円・継続）を作る。
   価格の ID（`price_…`）を、`worker/wrangler.toml` の `【Stripe の価格 ID（price_…）】` に入れる（価格の ID は秘密ではない）。
3. Stripe の「カスタマーポータル」を有効にする（解約、支払い方法の変更、請求履歴を許可。解約は「期間の終わりに解約」にする）。
4. Stripe の「設定 → Checkout と Payment Links」で、返金のポリシーの表示を設定する。
   同じ顧客が二重に契約できないようにする設定があれば、有効にする（**未検証**：設定の名前と有無を確かめる）。
5. `MAIL_FROM` を、A-4 で認証したドメインのアドレスにする（`worker/wrangler.toml`）。

### D. 手元で、Stripe のテスト環境につないで確かめる

**D-1. 手元用の秘密の値**（`worker/.dev.vars`。`.gitignore` 済みで、コミットされません）

テキストエディタで `worker/.dev.vars` を作り、次の4行を書きます（値は自分で貼る。Claude Code には見せない）。

```
STRIPE_SECRET_KEY=（テスト環境のシークレットキー）
STRIPE_WEBHOOK_SECRET=（D-3 で表示される値）
MAIL_API_KEY=（メール送信サービスのキー）
SITE_URL=http://localhost:8000
```

**D-2. 制限付きキー**（本番では、権限を絞ったキーを使う）：必要な権限は、Checkout Sessions（書き込み）、Customers（読み取り）、
Subscriptions（読み取り）、Customer portal（書き込み）。**未検証**：権限の名前は Stripe の画面で確かめる。足りないと 403 になる。

**D-3. 動かす**（ターミナルを3つ使う）

1つ目（Workers）：
```
cd ~/giji-trainer/worker
npx wrangler kv key put --binding=MEMBERS keytable --path=../private/keys.json --local
npx wrangler dev --port 8787
```

2つ目（Stripe の通知を手元へ転送。Stripe CLI が必要。表示された `whsec_…` を `.dev.vars` に入れ、1つ目を止めて起動し直す）：
```
stripe login
stripe listen --forward-to localhost:8787/webhook
```

3つ目（サイト。手元用の設定ファイルを作ってビルドする。`site.yaml` は変えない）：
```
cd ~/giji-trainer
source .venv/bin/activate
cp site.yaml /tmp/site-b.yaml
```
`/tmp/site-b.yaml` の `members:` に、`method: both` と `api_url: http://localhost:8787` の2行を足してから：
```
python build.py --no-ogp --config /tmp/site-b.yaml --out /tmp/dist-b
python -m http.server 8000 -d /tmp/dist-b
```

**D-4. 確かめること**（http://localhost:8000/members/ ）

- [ ] 「サイトで入会する」→ Stripe の決済ページに、**月額980円・毎月自動で更新・解約の方法・特商法の表記へのリンク**が出ている
- [ ] テスト用のカード（Stripe の説明にある番号）で支払う → 会員ページに戻り、すぐに模試が開く
- [ ] ログアウト → メールアドレスを入力 → メールが届く → リンクを開くとログインできる。同じリンクは2回使えない
- [ ] 会員でないメールアドレスを入力 → 画面の返事は同じ。メールは届かない
- [ ] 「支払い・解約」→ 解約 → 「○月○日まで解けます」と出て、まだ開く
- [ ] Stripe の画面で契約を今すぐ終了 → 開かなくなる
- [ ] 支払いに失敗するテスト用のカードに替える → 開かなくなり、「お支払いを確認できませんでした」と出る → カードを直すと開く
- [ ] 合言葉（今月の合言葉）でも、今までどおり開く
- [ ] スマホの幅でも、ボタンが押しやすく、横にはみ出さない。会員ページに顔文字が出ていない
- [ ] 別のブラウザでメールからログインできる

うまくいかないときは、1つ目のターミナルの記録と、Stripe の画面の「開発者 → イベント」「Webhook」を見ます。

### E. 本番に置く（この時点では、まだサイトからは使われない）

1. Stripe の**本番環境**で、C-2〜C-4 と同じ設定をする。価格の ID を `worker/wrangler.toml` に入れ直す。
2. `worker/wrangler.toml` の最後の3行（`[[routes]]`、`pattern`、`custom_domain`）の「# 」を外す。
3. 次のコマンドを、**1行ずつ**実行する（値は聞かれてから貼る）。

```
cd ~/giji-trainer/worker
```
```
npx wrangler secret put STRIPE_SECRET_KEY
```
```
npx wrangler secret put MAIL_API_KEY
```
```
npx wrangler deploy
```

4. Stripe の本番環境で、Webhook の送り先 `https://api.tracedrill.com/webhook` を追加する。送るイベント：
   `checkout.session.completed`、`customer.subscription.created`、`customer.subscription.updated`、`customer.subscription.deleted`、
   `invoice.paid`、`invoice.payment_failed`。表示された署名の値（`whsec_…`）を登録する。

```
npx wrangler secret put STRIPE_WEBHOOK_SECRET
```

5. 鍵の表を置く。

```
npx wrangler kv key put --binding=MEMBERS keytable --path=../private/keys.json --remote
```

6. コミットする（`wrangler.toml` には秘密の値がないので、コミットしてよい）。

```
cd ~/giji-trainer
python tools/preflight.py
git add worker/wrangler.toml
git commit -m "Workers の設定（KV の id、価格の ID、公開先）"
git push
```

7. `https://api.tracedrill.com/keys` をブラウザで開き、`{"error":"signed_out"}` と出ることを確かめる（動いている印）。

### F. サイトを切り替える（`both`：合言葉とサイトでの入会の両方）

1. `content/privacy.md` に、「当サイトで入会した場合」の項を戻す（`drafts/legal/privacy.md` から写し、【　】を埋める）。
2. `site.yaml` の `members:` に2行を足す。

```
  method: both
  api_url: https://api.tracedrill.com
```

3. 確かめて、公開する。

```
python tools/preflight.py --allow-site-yaml
git add site.yaml content/privacy.md
git commit -m "会員ページ：サイトでの入会を追加（合言葉も引き続き使える）"
git push
```

`--allow-site-yaml` は、「site.yaml を書き換えていない」の確認だけを外します（設定を意図して変える、この手順と G のときだけ使う）。

4. 公開後、本物のカードで自分が入会し、D-4 の上から3つを本番で確かめる。確かめたら「支払い・解約」から解約し、Stripe の画面で返金する。
5. note の会員限定記事で案内する（文面の例は下）。

**案内の例**（note の会員限定記事）

> 【お知らせ】サイトで直接入会できるようになりました
> ○月○日から、擬似言語トレースドリルの会員ページ（https://tracedrill.com/members/ ）で、クレジットカードで直接入会できるようになりました。
> サイトで入会すると、合言葉の入力が要らなくなり、メールアドレスだけでログインできます。料金は月額【980】円で、内容は同じです。
> note のメンバーシップは、【○月○日】に終了します。それまでは、これまでどおり合言葉でご利用いただけます。
> **サイトへ移る方へ**：二重のお支払いにならないよう、サイトで入会したら、note のメンバーシップを退会してください
> （note の「メンバーシップ」の画面から退会できます。退会した月の末日までは note 側も有効です）。
> ご不明な点は【連絡用のメールアドレス】までご連絡ください。

### G. note を閉じる（移行の期間が終わったら）

1. note のメンバーシップの新規の受付を止め、予告した日に閉じる（note の手順は、その時点のヘルプで確かめる。**未検証**）。
2. `site.yaml` の `method: both` を `method: stripe` に変え、F-3 と同じように公開する。合言葉の欄が出なくなる。
3. `OPERATIONS.md` の 4 から、note の記事の作業（D・F-2）を外す。

**古い合言葉について**：`stripe` にしたあとも、`site/members/keyring.json` は残ります（毎月の `publish` が、だれにも知らせない新しい合言葉で作り直します）。
note の元会員は、最後に知らされた合言葉で、**その時点までの模試**を開けることがあります（端末に合言葉が残っている間）。新しい模試は開けません。
これを止めるには、全部の模試を新しい鍵で暗号化し直す必要がありますが、「配布済みの模試は書き換えない」決まりの例外になるので、
実装していません。必要になったら、設計を示して了承を得てから作ります（`BACKLOG.md`）。

---

## 毎月の作業はこう変わる（`both` の間）

`OPERATIONS.md` の 4 の B（`publish`）のあと、E（push）の前に、鍵の表を置き直す1行が増えます。

```
cd ~/giji-trainer/worker
npx wrangler kv key put --binding=MEMBERS keytable --path=../private/keys.json --remote
cd ~/giji-trainer
```

- これを忘れると、サイトで入会した会員だけ、新しい回が一覧で開けません（合言葉の会員は開けます）。気づいたら、上の1行を実行すれば直ります。
- `stripe` にしたあとは、合言葉の変更と note の記事の作業がなくなります。
- 月に1回、Stripe の画面で「支払いの失敗」「不審請求の申し立て」を見ます。

## うまくいかなかったとき（戻し方）

`site.yaml` の `method` と `api_url` の2行を消して公開すれば、A案に戻ります（合言葉はずっと有効なままです）。
Workers は置いたままで構いません（サイトから呼ばれなくなるだけ）。
サイトで入会済みの人がいる場合は、戻す前に、Stripe の画面で契約を止めて返金し、メールで連絡します。

| 起きたこと | 見るところ・対処 |
|---|---|
| 入会したのに開かない | Stripe の「Webhook」で失敗していないか。`STRIPE_WEBHOOK_SECRET` が本番の値か。鍵の表を置いたか（E-5） |
| ログインのメールが届かない | メール送信サービスの記録。送信元ドメインの認証。迷惑メール。同じ宛先には2分に1通まで |
| 決済ページが開かない | `PLANS` の価格の ID が本番のものか。`STRIPE_SECRET_KEY` の権限（D-2） |
| ログインしても、すぐ切れる | ブラウザが Cookie を拒んでいないか。`api.tracedrill.com` と `tracedrill.com` が同じドメインの下にあること |
| Workers の記録を見たい | `cd worker` のあと `npx wrangler tail`（秘密の値とメールアドレスは記録に出さない作りです） |

## 手数料の目安（2026年11月に調べた値。移行の前に公式で再確認）

- Stripe：カード決済 3.6% ＋ 定期課金の機能 0.7%（推定）。980円あたり約42円 → 手取り約938円。
- note：約838円（推定）。差は1人あたり月およそ100円。
- 不審請求の申し立てには、1件ごとの手数料がかかるとする情報があります（**未検証**）。
- Cloudflare Workers・KV の無料枠は、会員が数百人までなら足りる見込みです（推定。**公式の料金ページで再確認**）。

## テストで確かめてあること・いないこと

| 確かめてある（偽物の Stripe・メール・KV で） | 確かめていない（本物が必要） |
|---|---|
| 入会、更新、解約の予約、期間の終わり、支払い失敗と回復、入り直し | Stripe の審査、本物の決済、本物の Webhook の中身 |
| Webhook：署名なし・違う署名・古い署名の拒否、2回届いたとき、逆の順番、処理の失敗 | Stripe の API の版による項目の違い（期間の終わりの置き場所は、2通りに対応済み） |
| ログイン：会員でない人への同じ返事、リンクは1回・15分、送りすぎの制限、Cookie の属性 | メールが実際に届くこと、迷惑メールに入らないこと |
| 会員ページの画面（360px・1280px）：入会、メールでログイン、支払い失敗の表示、ログアウト、合言葉との同居 | Safari・スマホの実機での Cookie の動き |
| `passphrase` のままなら、公開されるページが今と1文字も変わらないこと | wrangler のコマンド、Cloudflare の画面の操作 |
