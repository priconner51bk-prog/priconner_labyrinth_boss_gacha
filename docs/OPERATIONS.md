# 実機運用手順

## 実行前チェック

1. `priconner_labyrinth_boss_gacha` を clone し、プロジェクトルートから実行します。
2. ADB Platform-Tools が PATH にあり、`adb version` が成功することを確認します。
3. エミュレーターが起動し、ADB 接続できることを確認します。
4. `configs/` の対象ボス、ギルド、画面テンプレート、OCR 領域が実行環境に合っていることを確認します。
5. OCR モデルを用意します。標準モデルを使う場合は `--default-models` を指定します。

ADB の接続確認例:

```powershell
adb connect 127.0.0.1:5555
adb devices
```

Windows、macOS、Linux のいずれでも ADB コマンドは同じです。BlueStacks の ADB ポートが既定値と異なる場合は、`adb connect <host>:<port>` と実行し、以後のコマンドおよび `main.py live` に同じ接続先を指定します。

```bash
adb -s 127.0.0.1:5555 get-state
adb -s 127.0.0.1:5555 shell wm size
adb -s 127.0.0.1:5555 shell wm density
```

タップ・スワイプ座標は Android クライアント画面の `1280x720` を基準に自動補正されます。BlueStacks のタイトルバー、外枠、デスクトップ上の位置は座標計算に使用しません。取得した画面比率が基準と異なる場合は、誤操作を避けるため処理を停止します。

## preflight

`--execute` を付けずに実行すると、現在画面の認識結果を JSON で出力して終了します。

```powershell
python scripts/task_boss_gacha_live.py --serial 127.0.0.1:5555 --default-models
```

ここで ADB、画面テンプレート、またはローカルモジュールの import に失敗する場合は、入力を有効にしないで原因を解消します。

## 実行

許容するボスはエリアごとに 1 つ以上指定します。`--passports` は今回の処理で使用してよい枚数です。

```powershell
python scripts/task_boss_gacha_live.py `
  --execute --passports 10 --serial 127.0.0.1:5555 `
  --default-models `
  --area3-boss "エリア3のボス名" `
  --area5-boss "エリア5のボス名"
```

必要に応じて `--guild`、`--difficulty`、`--det-model`、`--rec-model` を指定できます。`--default-models` と個別 OCR モデル指定を同時には使いません。

## 途中復帰

挑戦中に手動操作で復帰した場合は、現在画面を `--resume-screen` で明示します。指定した画面と実際の画面が一致しなければ安全停止します。

対応値は `guild_select`、`guild_confirm`、`bonus`、`item_reward`、`initial_char`、`boss_map`、`boss_detail`、`withdraw_confirm` です。

## 安全停止とログ

ADB、画面観測、許容ボス、OCR モデル、画面遷移、対象ボス名などを確認できない場合は、入力を行わず終了します。

実行ログは本プロジェクトの `data/observations/live/` に保存されます。主なファイルは `boss_gacha_operations.jsonl`（操作記録）、`boss_gacha_operations.md`（人向け操作記録）、`boss_gacha_timing.jsonl`（待機時間）、`task_boss_gacha_*.png`（デバッグキャプチャ）です。

## 異常時

1. 画面が想定外なら、まず ADB 入力を止めます。
2. JSON の `status` と `reason` を保存します。
3. キャプチャ・OCR 結果・本プロジェクトの設定変更を確認します。
4. 原因を特定できるまで `--execute` で再実行しません。

## OS ごとの注意

- Windows は BlueStacks と ADB の組み合わせを主な検証対象とします。
- macOS / Linux は ADB クライアントの動作を確認できますが、BlueStacks 本体の提供状況、画面キャプチャ方式、GPU/OCR の対応は環境ごとに異なります。
- OS が変わる場合は、ADB 接続だけでなく画面サイズ、DPI、OCR モデル、キャプチャ結果を preflight で再確認します。
