# GitHub 公開手順

このプロジェクトは GitHub の Public リポジトリへ公開済みです。アカウントのメールアドレスやゲームアカウント情報は、README、コミット本文、Issue に記載しません。

## 公開前確認

配布ZIPは `python scripts/build_distribution.py` で `distribution/priconner_labyrinth_boss_gacha.zip` に生成し、`python scripts/build_distribution.py --check` で確認します。許可リストと検査内容は [マニフェスト](../distribution/MANIFEST.md) を参照してください。実機キャプチャ、ログ、OCR結果、レポート、モデル、ローカル設定は含めません。

```powershell
git status --short
git branch --show-current
git ls-files
git grep -n -i -E "api[_-]?key|secret|token|password|passwd|private[_-]?key|authorization|bearer"
python -m pytest -q
python scripts/build_distribution.py --check
git diff --check
```

実行キャプチャ、OCR 結果、操作ログ、モデルファイルは `.gitignore` の対象です。公開前に `git ls-files` で含まれていないことを確認します。

## 公開済みリモートの更新

既存の `origin` を確認してから、検証済みの変更を更新します。`origin` を追加し直す必要はありません。

```powershell
git remote -v
git status --short
git push origin main
```

認証情報を URL に埋め込まないでください。GitHub CLI や credential manager など、利用環境で承認された認証方式を使用します。

## 公開後確認

- README の「対応OS」と「安全・ライセンス」が表示される
- `SECURITY.md` と README のライセンス方針が確認できる
- キャプチャ、ログ、秘密情報が公開されていない
- clone 後に `requirements.txt` と README の手順でテストできる
- Issue や Discussions に個人情報・ゲームアカウント情報が投稿されていない
