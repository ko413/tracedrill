# drafts/legal/ — 公開前の下書き

ここにあるファイルは**公開されません**（ビルドは `content/` だけを読みます）。
公開するときは、【　】をすべて埋めてから `content/` に移します（手順は `MIGRATION_B.md` の B）。

| ファイル | 移す先 | 公開される URL |
|---|---|---|
| `tokushoho.md` | `content/tokushoho.md` | `/tokushoho/` |
| `privacy.md` | `content/privacy.md` | `/privacy/` |

- `content/` に置くと、フッターにリンクが自動で出ます。
- `python tools/preflight.py` は、`content/` に【　】が残っていると NG にします（埋め忘れたまま公開しないため）。
- どちらも**法律の専門家が確認したものではありません**。根拠にした資料と、運営者が自分で確かめる点は、
  各ファイルの下の「公開前に確かめること」と `MIGRATION_B.md` の「運営者が確認すること」にあります。
  公開するときは、「公開前に確かめること」から下を消してください（`---8<---` の行から下）。
