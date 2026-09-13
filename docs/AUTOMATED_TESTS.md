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
| AT-10 | テンプレート照合品質 | 保存済み実機キャプチャと14カード | 各カードの照合スコアが0.82以上 | `tests/test_live_selection_rules.py` |
| AT-11 | ポリシーパラメーター | 試行回数の上下限、対象ボス必須、許容ボス、初期試行回数 | 不正値は拒否し、許容値・代替ボス・欠損入力を正しく判定 | `tests/test_boss_gacha_parameters.py` |

## 実機試験: 全ギルドの判定・選択

| ID | 対象 | 試験方法 | 合格条件 | 実施結果 |
| --- | --- | --- | --- | --- |
| LIVE-GUILD-01 | 14ギルドのテンプレート判定 | ギルド選択画面で各カードを表示し、登録テンプレートと設定名を1件ずつ照合 | 対象ギルド名が完全一致し、隣接カードとの誤照合を採用しない | 14/14 合格 |
| LIVE-GUILD-02 | 14ギルドの選択操作 | 各ギルドを表示した状態で選択点をタップし、次画面への遷移を確認 | 選択したギルドと遷移後のギルドが一致し、誤タップ・安全停止がない | 14/14 合格 |
| LIVE-GUILD-03 | 全走査経路 | 左端・右端・中央の各開始位置からカルーセルを左右走査 | 14ギルドを重複なく検出し、各ギルドを選択可能 | 14/14 合格 |

対象ギルド（`configs/labyrinth_guild_order.json`）:
美食殿、トゥインクルウィッシュ、サレンディア救護院、王宮騎士団（NIGHTMARE）、リトルリリカル、自警団（カオン）、フォレスティエ、ルーセント学院、カルミナ、ディアボロス、牧場、財団、キャラバン、ラビリンス。

実施前に `python scripts/check_live_environment.py --serial 127.0.0.1:5555` が成功することを確認する。実施コマンドは `python scripts/task_select_guild_live.py --serial 127.0.0.1:5555` とし、各ギルドについてOCR判定、タップ座標、遷移後画面を記録する。確認画面から一覧へ戻る場合は `python scripts/task_cancel_guild_selection_live.py --serial 127.0.0.1:5555` を使用する。失敗時は操作を継続せず安全停止とする。

今回の実機確認では、美食殿の選択後に `guild_confirm` へ遷移し、追加したキャンセルタスクで `guild_select` へ復帰できることを確認した。

## 実行コマンド

```powershell
python -m pytest -q tests/test_live_selection_rules.py tests/test_boss_gacha_controller.py tests/test_boss_gacha_runner.py tests/test_boss_gacha_live_workflow.py tests/test_guild_selection.py
```

カバレッジ確認:

```powershell
python -m coverage run -m pytest -q tests --ignore=tests/test_main_gui.py
python -m coverage report -m src/boss_gacha/*.py
```

実機試験を行う場合も、初回は最大試行回数として `--passports 1` を使用します。ボスガチャは撤退運用のため、パスポートは消費しません。自動テストはADB入力を発生させません。
