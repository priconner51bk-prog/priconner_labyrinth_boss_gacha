# GitHub 公開手順

このプロジェクトは GitHub の Public リポジトリへ公開できます。アカウントのメールアドレスやゲームアカウント情報は、README、Git 設定、コミット本文、Issue に記載しません。

## 公開前確認

```powershell
git status --short
git branch --show-current
git ls-files
git grep -n -i -E "api[_-]?key|secret|token|password|passwd|private[_-]?key|authorization|bearer"
python -m pytest -q
git diff --check
```

実行キャプチャ、OCR 結果、操作ログ、モデルファイルは `.gitignore` の対象です。公開前に `git ls-files` で含まれていないことを確認します。

## リモート設定と push

GitHub 上で空の Public リポジトリを作成し、その URL を使って実行します。

```powershell
git remote add origin https://github.com/<account>/<repository>.git
git remote -v
git push -u origin main
```

認証情報を URL に埋め込まないでください。GitHub CLI や credential manager など、利用環境で承認された認証方式を使用します。

## 公開後確認

- README 冒頭の「公開範囲と免責」が表示される
- `SECURITY.md` と README のライセンス方針が確認できる
- キャプチャ、ログ、秘密情報が公開されていない
- clone 後に `requirements.txt` と README の手順でテストできる
- Issue や Discussions に個人情報・ゲームアカウント情報が投稿されていない
