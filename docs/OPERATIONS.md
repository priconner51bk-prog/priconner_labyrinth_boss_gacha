# 実機運用手順

## 実行前チェック

1. `priconner_labyrinth_boss_gacha` を clone し、プロジェクトルートから実行します。
2. ADB Platform-Tools が PATH にあり、`adb version` が成功することを確認します。
3. エミュレーターが起動し、ADB 接続できることを確認します。
4. `configs/` の対象ボス、ギルド、画面テンプレートが実行環境に合っていることを確認します。
5. 画面テンプレートが不足していないことを確認します。入口画面から実行する通常のボスガチャではOCRモデルは不要です。ホーム画面から入口へ移動する `task_launch_labyrinth_live.py` を使う場合だけ、別途PaddleOCRサービスの準備が必要です。

ADB の接続確認例:

```powershell
adb connect 127.0.0.1:5555
adb devices
```

実行前の一括診断:

```powershell
python scripts/check_live_environment.py --serial 127.0.0.1:5555
```

JSON の `ok` が `true` になるまで `--execute` は付けません。

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
python main.py live --serial 127.0.0.1:5555
```

ここで ADB、画面テンプレート、またはローカルモジュールの import に失敗する場合は、入力を有効にしないで原因を解消します。

## 実行

許容するボスはエリアごとに 1 つ以上指定します。`--passports N` はボスガチャ処理の最大試行回数を指定する互換引数で、既定値は1000回です。ボスガチャは撤退運用のため、パスポートは消費しません。試験時は `--passports 1` を指定します。結果は成功（`matched`）、失敗（`max_attempts`）、停止（`safety_stop`）に分かれます。

既定の対象はエリア3の `ベノムサラマンドラ` とエリア5の `ゴブリンロード` です。各エリアには他の候補もあるため、候補一覧は `configs/boss_area3.json` と `configs/boss_area5.json` を確認してください。複数候補を許容する場合は、同じオプションを繰り返します。

対象外のボスを検出した場合は撤退確認を行い、入口へ戻って次の試行に進みます。対象ボスを検出した場合は `matched` で終了します。対象ボス未検出のまま最大試行回数に達した場合は `max_attempts`、画面認識・遷移・ADBの確認に失敗した場合は `safety_stop` で終了します。いずれの場合も、終了後の画面を確認してから次の操作を行ってください。

```powershell
python main.py live `
  --execute --passports 10 --serial 127.0.0.1:5555 `
  --area3-boss "ベノムサラマンドラ" `
  --area5-boss "ゴブリンロード"
```

GUIでは難易度と認識モデルを選択せず、現在対応している難易度10とテンプレート判定を固定使用します。

GUIを使う場合は、プロジェクトルートで次を実行します。

```powershell
python main.py
```

GUIのADB serial初期値はCLIと同じ `127.0.0.1:5555` です。環境のポートが異なる場合は画面上で変更してください。

ホーム画面から入口へ移動する補助コマンドを使う場合だけ、`requirements-ocr.txt` を追加インストールしてください。

## 途中復帰

再開画面の指定は不要です。開始・再開とも現在のゲーム画面を内部で自動判定し、対応する処理地点から再開します。画面が曖昧、または挑戦中状態の入口だけでは復帰地点を特定できない場合は、ADB入力を行わず安全停止します。

## 安全停止とログ

ADB、画面観測、許容ボス、テンプレート、画面遷移、対象ボス名などを確認できない場合は、入力を行わず終了します。

実行ログは本プロジェクトの `data/observations/live/` に保存されます。主なファイルは `boss_gacha_operations.jsonl`（操作記録）、`boss_gacha_operations.md`（人向け操作記録）、`boss_gacha_timing.jsonl`（待機時間）、`task_boss_gacha_*.png`（デバッグキャプチャ）です。

## 異常時

1. 画面が想定外なら、まず ADB 入力を止めます。
2. JSON の `status` と `reason` を保存します。
3. キャプチャ・テンプレート一致結果・本プロジェクトの設定変更を確認します。
4. 原因を特定できるまで `--execute` で再実行しません。

## OS ごとの注意

- Windows は BlueStacks と ADB の組み合わせを主な検証対象とします。
- macOS / Linux は ADB クライアントの動作を確認できますが、BlueStacks 本体の提供状況と画面キャプチャ方式は環境ごとに異なります。
- OS が変わる場合は、ADB 接続だけでなく画面サイズ、DPI、テンプレート、キャプチャ結果を preflight で再確認します。
