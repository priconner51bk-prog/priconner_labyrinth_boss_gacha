# 配布最小構成マニフェスト

生成物: `distribution/priconner_labyrinth_boss_gacha_gacha_minimal_20260913_v7.zip`
検査結果: 108エントリ、設定参照27件、参照切れ0件、除外対象混入0件。

## ZIP配布対象

- `main.py`
- `src/`
- `scripts/task*.py`
- `scripts/labyrinth_route.py`
- `scripts/live_cli_utils.py`
- `scripts/check_live_environment.py`
- `scripts/start_boss_gacha.ps1`
- `configs/`
- `data/template_migration/templates/`
- `data/observations/live/template_*.png`
- `requirements.txt`
- `README.md`
- `SECURITY.md`
- `docs/SETUP.md`
- `docs/OPERATIONS.md`
- `docs/CONFIGURATION.md`

## ZIPから除外

- `data/observations/live/` の実機キャプチャ、ログ、OCR結果（`template_*.png` を除く）
- `tests/`、`reports/`、`artifacts/`、`models/`、`local/`
- `data/template_migration/source/` と `crops/` の取得元画像・ROI作業画像
- 個人環境や実機状態を含むレポート

## 公開前の停止条件

- 必須の実行スクリプトまたはテストが未追跡の場合
- 配布対象とローカル専用の境界が未確認の場合
- clean cloneで依存関係・CLIヘルプ・検査・テストを確認できない場合
- 実機キャプチャ、ADBログ、アカウント情報が公開対象へ混入する場合

ZIP作成後は、内容一覧に上記の除外対象が混入していないことを確認する。

## 現行ZIPの扱い

旧v3/v4/v5/v6 ZIPは使用しない。v7はガチャ経路に必要な設定参照とテンプレートが一致していることを検査済み。
