# 配布最小構成マニフェスト

## 必須の公開対象

- `main.py`
- `src/`
- `scripts/task_boss_gacha_live.py`
- `scripts/labyrinth_route.py`
- `scripts/live_cli_utils.py`
- `scripts/check_live_environment.py`
- `scripts/start_boss_gacha.ps1`
- `configs/`
- `requirements.txt`
- `requirements-ocr.txt`（ホーム画面から入口へ移動する場合のみ）
- `README.md`
- `SECURITY.md`
- `docs/SETUP.md`
- `docs/OPERATIONS.md`
- 最小回帰テスト

## ローカル専用

- `data/observations/live/` の実機キャプチャ、ログ、OCR結果
- `data/template_migration/source/` と `crops/` の取得元画像・ROI作業画像
- 個人環境や実機状態を含むレポート

## 公開前の停止条件

- 必須の実行スクリプトまたはテストが未追跡の場合
- 配布対象とローカル専用の境界が未確認の場合
- clean cloneで依存関係・CLIヘルプ・検査・テストを確認できない場合
- 実機キャプチャ、ADBログ、アカウント情報が公開対象へ混入する場合

現時点では、必須候補の一部が未追跡のため、公開可能とは判定しない。
