# worker/ — 会員の確認・B案（Stripe の定期課金＋Cloudflare Workers）

**まだ公開していません。** サイトは今も A案（note＋合言葉）で動いていて、このフォルダはサイトのビルドにも公開にも使われません。
設定・公開・移行の手順は、リポジトリの `MIGRATION_B.md` にあります。

| ファイル | 中身 |
|---|---|
| `src/index.js` | Workers のコード（入会、Webhook、ログイン、鍵の表、支払い・解約） |
| `test/worker.test.js` | テスト。Stripe・メール・KV は偽物で、外へは何も送らない |
| `wrangler.toml` | 設定。秘密の値は書かない（【　】は KV の id と価格の ID で、秘密ではない） |
| `package.json` | テストの実行用。追加のパッケージはない |

## テスト

```
node --test worker/test/worker.test.js
```

`python -m pytest -q` と `python tools/preflight.py` からも実行されます（Node がなければ飛ばします）。

## 秘密の値

コード・`wrangler.toml`・コミット・チャットに書きません。本番は `npx wrangler secret put 名前`、手元の確認は `worker/.dev.vars`
（`.gitignore` 済み）に置きます。名前の一覧は `MIGRATION_B.md` の「秘密の値」。
`python tools/preflight.py` は、Stripe の鍵の形（`sk_live_…` `whsec_…` など）や `.dev.vars` がコミットの対象に入っていると NG にします。

## 入口

| 入口 | だれが呼ぶか | すること |
|---|---|---|
| `POST /checkout` | 会員ページ | Stripe の決済ページを作り、URL を返す |
| `POST /webhook` | Stripe | 署名を確かめ、Stripe の今の状態を読み直して保存する |
| `POST /claim` | 会員ページ（決済から戻ったとき） | 支払い済みを確かめ、ログイン済みにする |
| `POST /login` | 会員ページ | ログイン用のリンクをメールで送る（会員でなくても返事は同じ） |
| `POST /session` | 会員ページ（メールのリンクを開いたとき） | リンクの番号を確かめ、ログイン済みにする |
| `GET /keys` | 会員ページ | 会員なら鍵の表を返す。ここが「会員かどうかの確認」 |
| `POST /portal` | 会員ページ | Stripe の「支払い・解約」ページの URL を返す |
| `POST /logout` | 会員ページ | ログインを消す |

## 後から足すとき

- **単品販売**：`PLANS` に `"single": {"price": "price_…", "mode": "payment", "bundles": ["mock-001"]}` を足す。コードとテストは入っている
  （買った回の鍵だけを返す）。会員ページに「この回だけ購入する」ボタンを足す作業が残っている（`MemberBilling.checkout('single', 'mock-001')`）。
- **法人プラン**：何を開けるかの判断は `entitlement()` の1か所。席の数だけメールアドレスを登録する形なら、
  `member:<ハッシュ>` に「どの契約の席か」を持たせ、`entitlement()` に条件を足す。請求書払いは Stripe の Invoicing を使う（未実装・未検証）。
