# B案への移行メモ（Stripe 定期課金 ＋ Cloudflare Workers）

会員の確認を「note＋合言葉」から「サイト内の決済＋メールのログインリンク」に移すための手順です。
**会員が20〜30人になる前**に移すのが目安です（note の会員は自動では引き継げず、入り直してもらうため）。

> このメモのコードは**設計の下書きで、実際の Stripe・Cloudflare では動かしていません**。
> 料金・無料枠・画面の名前は変わるので、作業の前に各サービスの公式ドキュメントで確かめてください。
> 「未検証」と書いた点は、特に確認が必要です。

## 0. 何が変わり、何が変わらないか

| | 今（A案） | B案 |
|---|---|---|
| 支払い・解約 | note | Stripe（Checkout とカスタマーポータル） |
| 会員の確認 | 合言葉 → `keyring.json` を開く | メールのログインリンク → Workers が会員かどうかを Stripe の状態で判断 |
| 鍵の表（模試の名前 → 鍵） | 合言葉で暗号化して公開 | Workers のシークレット。会員にだけ返す |
| 模試の中身（`site/members/data/`） | 暗号化して公開 | **そのまま** |
| 模試の作成（`tools/members.py mock / early`） | — | **そのまま** |
| 模試の画面（`site/static/mock.js`） | — | **そのまま**（合言葉の入力欄をメール欄に替えるだけ） |
| 差し替えるファイル | — | `site/static/member.js`（`keys()` `login()` `logout()` `expired()`） |

退会した人が古い合言葉で過去の模試を開ける、合言葉を共有できる、という A案の限界は、B案で解消します
（鍵の表を公開しなくなるため。ただし、移行前に公開した鍵束は履歴に残るので、**移行時に全部の模試の鍵を作り直す**。手順 6）。

## 1. 先に用意するもの（運営者の作業）

1. **特定商取引法に基づく表記のページ**（`content/tokushoho.md` を作り、フッターからリンク）。
   - 個人の場合、氏名・住所・電話番号を「請求があった場合は遅滞なく開示します」と書いて省略できる、と Stripe のヘルプにあります。
     ただし省略できるのは、**実際に遅滞なく開示できる場合だけ**です。請求が来たら本名・住所・電話番号を渡します。
   - 氏名まで省略して Stripe の審査に通るかは**未検証**（運営責任者名は省略できないとする体験談あり）。
   - 定期課金なので、申込みの最終確認画面に「金額・課金の間隔・解約の方法」などを表示する義務があります（特商法12条の6）。
     Stripe Checkout の標準画面だけで足りるかは**未検証**。消費者庁の「通信販売の申込み段階における表示についてのガイドライン」で確認する。
   - 必要な項目：販売価格、支払方法と時期、提供時期（決済後すぐ）、解約の方法、返金の方針、動作環境、連絡先（メール）。
2. **連絡用のメールアドレス**（ドメインのメール転送で `info@tracedrill.com` など。個人のアドレスは出さない）。
3. **Stripe アカウント**：本人確認書類と入金口座。申請フォームには本名・住所・電話番号を入力します（サイトに出す表記とは別）。
   審査は数営業日かかることがあるので、最初に申請します。
4. **Cloudflare アカウント**（ドメインと同じもの）と、手元に Node.js（`npx wrangler` を使うため）。
5. **メール送信サービス**：Workers からログインリンクを送るために必要。候補と無料枠は**未検証**（その時点で調べて決める）。
   送信元ドメインの設定（SPF・DKIM）が必要です。

## 2. 全体のしくみ

```
[サイト（GitHub Pages）]                [Workers: api.tracedrill.com]            [Stripe]
 会員ページ ── 入会ボタン ───────────→ POST /checkout ───────────────────────→ Checkout（月額980円）
                                                                              │ 決済
                                         POST /webhook ←───────────────────── イベント通知（署名つき）
                                           └ KV に「メール → 顧客ID・状態」を保存
 メール入力 ───────────────────────────→ POST /login
                                           └ 会員なら、15分有効のログインリンクをメールで送る
 メールのリンク ─────────────────────────→ GET /session?token=…
                                           └ 30日有効のセッションを発行し、会員ページへ戻す
 member.js keys() ──────────────────────→ GET /keys（セッションつき）
                                           └ Stripe の状態が有効なら、鍵の表を返す
 「支払い・解約」ボタン ─────────────────→ POST /portal → Stripe のカスタマーポータルへ
```

- セッションは、サイト（tracedrill.com）と API（api.tracedrill.com）が同じドメインの下なので Cookie で持てます
  （`Domain=tracedrill.com; Secure; HttpOnly; SameSite=Lax`）。うまくいかなければ、トークンを `localStorage` に持たせて
  `Authorization` ヘッダーで送る方式に替えます。
- KV に入れるもの：`member:<メールのハッシュ>` → `{customer, status, current_period_end}`、
  `token:<乱数>` → メール（15分で消える）、`session:<乱数>` → メール（30日で消える）。
- 無料枠の目安：Workers は1日10万リクエスト、KV は1日の書き込み1,000回（2026年11月時点。会員数百人なら十分）。

## 3. Workers が持つ秘密（リポジトリに入れない）

`npx wrangler secret put 名前` で登録します。コード・`wrangler.toml`・チャットに貼りません。

| 名前 | 中身 |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe のシークレットキー（できれば権限を絞った制限付きキー） |
| `STRIPE_WEBHOOK_SECRET` | Webhook の署名を確かめるための値 |
| `KEY_TABLE` | 鍵の表（`private/keys.json` の中身そのまま） |
| `MAIL_API_KEY` | メール送信サービスのキー |
| `SESSION_SECRET` | セッションの署名用の乱数 |

毎月 `publish` のあとに、`KEY_TABLE` を新しい `private/keys.json` で更新する作業が増えます
（`npx wrangler secret put KEY_TABLE < private/keys.json`）。

## 4. 作るもの（順番に）

Workers のコードはサイトとは別のフォルダ（`worker/`）に置き、テストを先に書きます。

1. **Stripe の設定**（テスト環境で）：商品「会員」、価格 月額980円、カスタマーポータルを有効化（解約・カード変更を許可）。
2. **`POST /checkout`**：Checkout セッション（`mode: subscription`）を作り、URL を返す。成功時の戻り先は `/members/?joined=1`。
3. **`POST /webhook`**：署名を確かめてから処理する（確かめずに信じない）。扱うイベント：
   `checkout.session.completed`（会員登録）、`customer.subscription.updated` / `deleted`（状態の更新）、`invoice.payment_failed`（支払い失敗）。
   同じイベントが2回届いても結果が変わらないように書く。
4. **`POST /login`**：メールが会員なら、ログインリンクを送る。**会員でなくても同じ返事を返す**（誰が会員かを外から調べられないように）。
   同じメールへの送信は、数分に1回までに制限する。
5. **`GET /session`**：トークンを確かめて消し、セッションを発行して `/members/` へ戻す。
6. **`GET /keys`**：セッションのメールの状態が `active`（または `trialing`）なら `KEY_TABLE` を返す。そうでなければ 401。
7. **`POST /portal`**：カスタマーポータルの URL を返す。
8. **CORS**：`https://tracedrill.com` からだけ受け付ける。
9. **`site/static/member.js` の差し替え**（下の下書き）と、会員ページの文言（「合言葉」→「メールアドレス」、入会ボタン、支払い・解約ボタン）。

### member.js の下書き（未検証）

```js
(function () {
  'use strict';
  var API = 'https://api.tracedrill.com';
  var cache = null;

  async function fetchKeys() {
    var response = await fetch(API + '/keys', { credentials: 'include' });
    if (response.status === 401) return null;          // ログインしていない、または会員でない
    if (!response.ok) throw new Error('keys');
    return (await response.json()).keys;
  }

  window.MemberAuth = {
    method: 'email',
    keys: async function () { cache = cache || await fetchKeys(); return cache; },
    // input はメールアドレス。リンクを送るだけなので、その場では会員にならない（false を返し、画面は「メールを確認」と表示）
    login: async function (input) {
      await fetch(API + '/login', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: input }) });
      return false;
    },
    logout: function () { cache = null; fetch(API + '/logout', { method: 'POST', credentials: 'include' }); },
    expired: async function () { return false; },
    open: /* 今の member.js の open をそのまま写す（模試ファイルの復号。確認方法に関係しない） */ null
  };
})();
```

`mock.js` 側で変えるのは、`login()` が false のときの文言（「メールを送りました。届いたリンクを開いてください」）だけです。

## 5. 公開前の確認（Stripe のテスト環境で、全部できてから本番へ）

- [ ] テスト用カードで入会 → メールのリンク → 会員ページで模試が開く
- [ ] カスタマーポータルで解約 → 期間の終わりまでは開く → 期間が過ぎたら開かない
- [ ] 支払い失敗のテストカード → 開かなくなる → カードを直すと開く
- [ ] 会員でないメールでログイン → 会員と同じ返事。メールは届かない
- [ ] 使用済み・期限切れのログインリンク → 開かない
- [ ] Webhook に署名のない要求を送る → 拒否される
- [ ] 別のブラウザ・スマホでログインできる
- [ ] `python -m pytest -q` と `python build.py --frozen` が通る
- [ ] 特商法のページがフッターから開ける。Checkout の画面に金額・毎月の課金・解約方法が出ている

## 6. 切り替えの日

1. **全部の模試の鍵を作り直す**（古い鍵束が公開リポジトリの履歴に残っているため）。
   これは「暗号化済みファイルは書き換えない」決まりの、ただ1回の例外です。運営者が決めて実行します。
   `tools/members.py` に `rekey` コマンドを足す（`private/bundles/` の平文から、新しい鍵で `site/members/data/` を作り直す）。
2. `site/members/keyring.json` を削除し、新しい鍵の表を `KEY_TABLE` に登録する。
3. `member.js` と会員ページを差し替えて公開する。
4. note の会員限定記事で告知する：「○月○日から、サイトで直接入会する形に変わります。note のメンバーシップは○月末で終了します」。
   二重に払わせないよう、**note 側の退会の方法と時期をはっきり書く**。移行の月は、note の会員にも最後の合言葉の代わりに
   無料の期間（Stripe のクーポンなど）を用意すると親切です。
5. note のメンバーシップの新規受付を止め、月末に閉じる（note の手順は、その時点のヘルプで確認）。

## 7. うまくいかなかったとき（戻し方）

`member.js` と会員ページを前の版に戻し、`keyring.json` を `python tools/members.py publish --new-passphrase` で作り直せば、
A案に戻ります（鍵を作り直したあとでも、`private/keys.json` が新しい鍵になっていれば動きます）。
Stripe で入会済みの人がいる場合は、戻す前に個別に連絡し、返金します。

## 8. 毎月の作業はこう変わる

- 合言葉の変更と note の記事の書き換えが**なくなる**。
- `publish` のあとに `KEY_TABLE` の更新が**増える**（コマンド1つ）。
- 月1回、Stripe の画面で「支払い失敗」「不審な申し立て」を確認する。

## 9. 手数料の目安（2026年11月に調べた値。移行前に公式で再確認）

- Stripe：カード決済 3.6% ＋ 定期課金の機能（Billing）0.7%。980円あたり約42円 → 手取り約938円。
- note：約838円（プラットフォーム利用料10%＋決済手数料）。差は1人あたり月およそ100円。
- 不正利用の申し立て（チャージバック）があると、1件1,500円の手数料がかかるとする情報あり（第三者の記事。未検証）。
