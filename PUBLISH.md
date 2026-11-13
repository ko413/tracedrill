# 公開の手順

独自ドメイン（.com）＋ GitHub Pages ＋ Cloudflare Web Analytics で公開する手順です。
画面の文言や料金は変わることがあるので、各サービスの最新の案内も確認してください。

## 0. 手元で確認する

```
pip install -r requirements.txt
python build.py
python -m http.server -d dist      # http://localhost:8000 を開く
```

## 1. ドメインを取る（WHOIS に個人情報を出さない）

条件は「WHOIS 公開代行（または情報の非表示）が無料で付くこと」です。例として Cloudflare Registrar を使う場合：

1. Cloudflare のアカウントを作る（無料）。
2. ダッシュボードの「ドメインの登録」で希望の .com を検索して購入する。
   - 卸値での販売で、WHOIS の個人情報の非表示が無料で付きます。
   - Cloudflare で取ったドメインは、DNS も Cloudflare のものを使う決まりです。
3. 登録者情報（氏名・住所）は正確に入力する。入力しても、WHOIS には表示されません。

国内のレジストラ（お名前.com、ムームードメイン、Xserverドメインなど）を使う場合は、
申込み時に「Whois 情報公開代行」を有効にします。後から有効にすると有料になる所があります。

## 2. site.yaml を直す

```yaml
base_url: https://取得したドメイン      # 末尾に / を付けない
custom_domain: 取得したドメイン          # dist/CNAME が出力される
```

## 3. GitHub に置く

1. GitHub でリポジトリを作り、この一式を push する（`dist/` は .gitignore 済み）。
2. リポジトリの Settings → Pages → Build and deployment → Source を **GitHub Actions** にする。
3. main に push すると `.github/workflows/pages.yml` が動き、テスト → ビルド → 公開まで行う。

## 4. DNS を GitHub Pages に向ける

ドメインの DNS 設定に、次のレコードを足します。

| 種類 | 名前 | 値 |
|---|---|---|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | あなたのユーザー名.github.io |

- Cloudflare の DNS を使う場合、これらのレコードは「DNS のみ」（プロキシなし）にしておくと、
  GitHub 側の証明書の発行でつまずきにくくなります。
- 反映には最大で24時間ほどかかることがあります。

## 5. GitHub Pages にドメインを設定する

1. Settings → Pages → Custom domain に、取得したドメインを入力して保存する。
2. DNS の確認が通ったら、**Enforce HTTPS** にチェックを入れる。
3. ドメインの乗っ取りを防ぐため、アカウントの Settings → Pages で「ドメインの検証」もしておく。

## 6. 問い合わせ窓口を作る（個人のアドレスを出さない）

どちらか一方を `site.yaml` の `contact` に入れます。

- **フォーム**：Google フォームなどを作り、その URL を `form_url` に入れる。
- **サイト専用アドレス**：`info@ドメイン` のようなアドレスを作り、`email` に入れる。
  Cloudflare の DNS を使っているなら、メール転送の機能で個人のアドレスに転送できます
  （返信すると個人のアドレスが相手に見える点に注意）。

## 7. アクセス計測（Cookie なし）

1. Cloudflare のダッシュボードで Web Analytics を開き、サイト（ドメイン）を追加する。
2. 「手動で JS スニペットを設置」を選び、表示されたスニペットの中の `token` の値を控える。
3. `site.yaml` の `analytics.cloudflare_token` に入れて push する。全ページにタグが入ります。

## 8. 検索エンジンに知らせる

1. Google Search Console でドメインを登録する（DNS に TXT レコードを足す方式が確実）。
   HTML タグ方式を使うなら、`site.yaml` の `search_console.google_verification` に値を入れる。
2. 「サイトマップ」に `https://ドメイン/sitemap.xml` を送信する。
3. 共有用の画像は、X の投稿画面に URL を貼って表示を確認する。

## テンプレートを足すとき

1. `templates/basic/` に YAML を足す。
2. `content/algo/<id>.md` に解説（何をしているか／トレースのコツ／よくある間違い）を書く。
3. `python tools/validate_templates.py` で検査し、`python build.py` で確認する。
4. push する。`problems/` に増えた JSON も一緒にコミットする（これが公開済みの問題の本体）。

## 公開済みの問題について

- `problems/` の JSON は、一度作られたら書き換わりません。テンプレートを直しても既存の問題は変わりません。
- 誤りのある問題を直したいときは、その JSON を消してビルドします。同じ URL で新しい問題に入れ替わります。
- `problems/` を消したり .gitignore に入れたりしないでください。次のビルドで全問題が作り直されます。
- GitHub Actions では `python build.py --frozen` で動かしています。`problems/` にない問題があるとエラーで止まり、
  公開されません。その場合は、手元で `python build.py` を実行し、増えた JSON をコミットして push し直します。
