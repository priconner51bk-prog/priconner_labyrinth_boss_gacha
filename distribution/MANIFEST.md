# 配布ZIPマニフェスト

生成物: `distribution/priconner_labyrinth_boss_gacha.zip`

生成・検査: `python scripts/build_distribution.py` / `python scripts/build_distribution.py --check`

実測: **102エントリ**（ファイル101件と `SHA256SUMS.json` 1件）

ZIP SHA-256: `24adb940b8e04eff993d4ceac6aecfebc340c54136385f62511397aac19dcf64`

`SHA256SUMS.json` は全101ファイルのソースSHA-256を記録する。検査コマンドはZIP内ファイルと現行ソースのハッシュを全件照合し、ZIP全体も固定時刻・固定順序・無圧縮で再生成してバイト単位で比較する。

## 配布境界

- `main.py`、`requirements.txt`、配布用の `README.md` と `SECURITY.md`
- `docs/SETUP.md`、`docs/OPERATIONS.md`、`docs/CONFIGURATION.md`
- GUI/CLI、BlueStacks起動、プリコネ再起動、入口移動に必要な `scripts/`、`src/boss_gacha/`、`src/contracts/`、`src/decision/`、`src/vision/` の明示許可ファイル
- 実行経路で参照する `configs/` の6件
- 全ボス名・ギルド名テンプレートと `configs/live_screen_templates.json` が参照する画像

許可リストの正本は [生成スクリプト](../scripts/build_distribution.py) の `FILES` と `files()`。展開済みの `distribution/` 直下の作業コピーはZIPの入力に使用しない。

## 自動検査

- ZIPエントリの許可リスト完全一致、`.pyc`・`__pycache__`・`*.egg-info`・旧機能ファイル・ローカル証跡の混入0件
- Markdown相対リンクと画面設定の参照画像に欠落0件
- 一時ディレクトリへ展開後、GUIランチャー・live CLI・実行CLI・環境検査CLIの `--help` 成功
- ADBを存在しないコマンドに指定したオフラインpreflightで、端末未接続として終了し、画面テンプレート検査のみ成功
- CIで `python scripts/build_distribution.py --check` を実行

実機へのADB入力はこの検査に含めない。実機確認は `docs/TASKS.md` の QV-07 に従う。
