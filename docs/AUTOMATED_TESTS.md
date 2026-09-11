# 自動テスト項目

ボスガチャのテンプレート判定・安全停止・試行回数を、実機入力なしで確認する項目一覧です。

| ID | 対象 | 確認内容 | 合格条件 | 対応テスト |
| --- | --- | --- | --- | --- |
| AT-01 | ギルド名行結合 | 複数行カード名、隣接カード、低信頼入力 | 対象カードだけを選択点に変換し、曖昧入力は拒否 | `tests/test_guild_selection.py` |
| AT-02 | ギルド走査 | 固定順序、左右スワイプ、開始位置差 | 全ギルドを走査でき、1回のスワイプが1カード単位 | `tests/test_guild_selection.py` |
| AT-03 | 報酬画面分類 | 出発ボーナスと撤退確認の類似画面 | 報酬画面を `bonus` と分類し、撤退確認に誤分類しない | `tests/test_live_selection_rules.py` |
| AT-04 | ボス組み合わせ | 対象外ボスと対象ボス | 対象外は `withdraw_and_retry`、一致は `matched` | `tests/test_live_selection_rules.py` |
| AT-05 | 試験回数上限 | 1回相当および1000回上限 | 1000回目まで許可し、1001回目は設定できない | `tests/test_live_selection_rules.py`, `tests/test_boss_gacha_controller.py` |
| AT-06 | ランナー状態遷移 | retry、matched、safety stop | 状態と試行回数が一致し、例外を成功扱いしない | `tests/test_boss_gacha_runner.py`, `tests/test_boss_gacha_live_workflow.py` |
| AT-07 | OCR非依存 | 実行スクリプトのテンプレート専用経路 | OCRモデルを初期化せず、未一致時は安全停止 | `tests/test_live_selection_rules.py` と静的参照確認 |
| AT-08 | 全ギルド走査 | 設定済み14ギルドの全開始位置・全目的位置 | 固定順序の走査で全組み合わせが目的位置へ到達 | `tests/test_live_selection_rules.py` |
| AT-09 | 全カードテンプレート | 設定済み14ギルドのカード画像 | 全ギルドがASCII名テンプレートへ対応付く | `tests/test_live_selection_rules.py` |

## 実行コマンド

```powershell
python -m pytest -q tests/test_live_selection_rules.py tests/test_boss_gacha_controller.py tests/test_boss_gacha_runner.py tests/test_boss_gacha_live_workflow.py tests/test_guild_selection.py
```

実機試験を行う場合も、初回は `--passports 1` を使用します。自動テストはADB入力を発生させません。
