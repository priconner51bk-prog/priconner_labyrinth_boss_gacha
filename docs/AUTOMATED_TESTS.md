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
| AT-11 | ポリシーパラメーター | 試行回数の上下限、対象ボス必須、許容ボス、初期試行回数 | 不正値は拒否し、許容値・代替ボス・欠損入力を正しく判定 | `tests/test_boss_gacha_controller.py`, `tests/test_boss_gacha_runner.py` |

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

## CI と依存バージョン

CI は Python 3.11 で `requirements-ci.txt` と `constraints-ci.txt` を使用する。後者にはテスト・Ruff・coverage とそれらの依存を固定した。ローカルでは次のコマンドで同じ検査範囲を確認する。Windows の既定文字コードが UTF-8 でない場合、`requirements.txt` 内の日本語コメントを pip が読めるよう `PYTHONUTF8` を設定する。

```powershell
$env:PYTHONUTF8 = "1"
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-ci.txt -c constraints-ci.txt
.venv\Scripts\python -m pip check
.venv\Scripts\python -m compileall -q main.py scripts src tests
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check main.py scripts src tests --select F,E9,F63,F7,F82,PLW1510
.venv\Scripts\python scripts/validate_screen_catalog.py
.venv\Scripts\python scripts/audit_safety.py
.venv\Scripts\python scripts/build_distribution.py --check
```

GUI テストを走らせる Linux CI では `python3-tk` と `xvfb` を導入し、pytest を `xvfb-run -a` で実行する。ローカルの GUI 環境がない場合だけ `--ignore=tests/test_main_gui.py` を指定し、その除外を結果に記録する。

依存更新時は Python 3.11 の新しい仮想環境で `requirements-ci.txt` を制約なしで導入し、`pip list --format=freeze` からこのプロジェクトに必要な直接・間接依存のバージョンを `constraints-ci.txt` に反映する。`pip check`、全pytest、同じ compile/Ruff コマンドを再実行してから固定値を更新する。OS 固有の依存は必要な OS で確認する。

## 分岐カバレッジ

`coverage` は `requirements-ci.txt` に含める。入力を送らないテストで次を実行する。

```powershell
python -m coverage erase
python -m coverage run --branch --source=boss_gacha,scripts.labyrinth_route,scripts.task_boss_gacha_live -m pytest -q --ignore=tests/test_main_gui.py
python -m coverage report -m src/boss_gacha/controller.py src/boss_gacha/runner.py scripts/labyrinth_route.py scripts/task_boss_gacha_live.py
```

2026-09-25、Python 3.11・固定依存・GUI 除外での基準値（文の網羅率と分岐網羅率を合わせた `Cover`）:

| 対象 | Cover | 未到達の主な箇所 |
| --- | ---: | --- |
| `src/boss_gacha/controller.py` | 92% | 不正な試行回数の下限、JSON 設定読込の一部 |
| `src/boss_gacha/runner.py` | 95% | 進捗通知コールバック例外、開始時に上限到達済みの経路 |
| `scripts/labyrinth_route.py` | 23% | 多数の画面遷移・ADB 操作経路。実機入力を伴う経路を単体試験で直接実行しない |
| `scripts/task_boss_gacha_live.py` | 65% | 画面観測失敗、未知画面、各 UI 遷移失敗などの一部 |

4 ファイル合計は 53%。判定器の対象エリア欠落と runner の画面ガード例外は、入力なしのテストを追加して安全停止と後続入力なしを確認した。低い配布・操作経路の数値を機械的に上げず、再現できる画面・ADB モックを用意したうえで未到達の安全分岐を追加検証する。

実機試験を行う場合も、初回は最大試行回数として `--passports 1` を使用します。ボスガチャは撤退運用のため、パスポートは消費しません。自動テストはADB入力を発生させません。
