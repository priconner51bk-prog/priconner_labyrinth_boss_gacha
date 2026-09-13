# 配布最小構成マニフェスト

生成物: `distribution/priconner_labyrinth_boss_gacha_minimal_ocr_removed_20260913.zip`
検査結果: 230エントリ、設定参照62件、除外対象混入なし。

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
- `requirements-ocr.txt`（ホーム画面から入口へ移動する場合のみ）
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
