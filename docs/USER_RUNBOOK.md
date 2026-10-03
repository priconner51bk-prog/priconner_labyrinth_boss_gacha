# ボスガチャ実行手順

## 起動からガチャ完了まで1コマンドで実行

保存済み設定でBlueStacks起動、プリコネ起動・再起動、ラビリンス入口への誘導、対象ボスガチャ、成功後のBlueStacks終了まで行います。Python操作ウィンドウを手動で操作する必要はありません。

```powershell
python scripts/task_run_boss_gacha_live.py
```

試行回数、ギルド、対象ボス、ADB serialは `.local_gui_settings.json` を読みます。上書きする場合は `--passports`、`--guild`、`--area3-boss`、`--area5-boss`、`--serial` を指定します。タイムアウトや通信エラーは最大3回で安全停止します。結果JSONの `status` が `matched` なら完了です。

## BlueStacks起動からラビリンス入口まで

次のコマンドで、BlueStacks起動、プリコネ起動・再起動、画面確認をしながらラビリンス入口まで進めます。ガチャ操作はしません。

```powershell
python scripts/task_prepare_boss_gacha_live.py
```

既定では `C:\Program Files\BlueStacks_nxt\HD-Player.exe` の `Nougat32` インスタンスを使います。GUIに保存したADB serialとADB実行ファイルを準備・ガチャ処理間で共有します。別の接続先を使う場合だけ `--serial` を指定してください。

結果JSONが `status: completed` かつ `screen_after: labyrinth_top` なら入口画面で停止し、ボスガチャ操作用のPython GUIが開いています。`safety_stop` が返った場合は表示された画面と理由を確認し、認識できない画面で操作を続けないでください。

## 手動で進める場合

### 1. BlueStacksとプリコネを起動

1. BlueStacksを起動する。
2. ADB接続を確認する。

```powershell
adb devices -l
```

`127.0.0.1:5555` が `device` と表示されることを確認する。

3. BlueStacksのホーム画面で「プリコネR」をクリックする。
4. プリコネのタイトル画面が表示されたら、「Touch To Start」をクリックする。

## 2. クエスト画面へ移動

1. タイトル画面からホーム画面が表示されるまで待つ。
2. ホーム画面下部の「クエスト」ボタンを押す。
3. クエスト画面が表示されたことを確認する。

## 3. ラビリンス入口へ移動

ホーム画面からクエスト入口へ移動する場合は、次を実行する。

```powershell
python scripts/task_launch_labyrinth_live.py --serial 127.0.0.1:5555
```

`status` が `completed` になり、ラビリンス入口画面が表示されることを確認する。

## 4. 実行前チェック

```powershell
python scripts/check_live_environment.py --serial 127.0.0.1:5555
```

次のチェックがすべて `ok: true` であることを確認する。

- ADB接続
- 端末状態
- 画面サイズ `1280x720`
- 画面テンプレート

## 5. ボスガチャを実行

現在の対象ボス設定で実行する例:

```powershell
python main.py live `
  --execute `
  --passports 1000 `
  --serial 127.0.0.1:5555 `
  --area3-boss "ベノムサラマンドラ" `
  --area5-boss "ゴブリンロード"
```

`--passports` はパスポート消費数ではなく、最大試行回数を表す。

## 6. 結果の扱い

- `matched`: 対象ボスを検出して終了
- `max_attempts`: 最大試行回数に到達
- `safety_stop`: 画面認識、ADB、画面遷移などに異常があり安全停止

`safety_stop` の場合は、画面を確認して原因を解消するまで `--execute` を再実行しない。

## 7. タイムアウト時

プリコネ起動後に「タイムアウトしました」と表示された場合:

1. タイトルへ戻る。
2. ネットワーク接続とプリコネの通信状態を確認する。
3. タイトル画面から再度「Touch To Start」を押す。
4. ホーム画面に戻ったら、クエスト、ラビリンス入口の順に進める。

## 注意

- 対応対象はBlueStacks 5、Android画面 `1280x720` を前提とする。
- 想定外の画面では操作を続けず、安全停止結果を確認する。
- ゲーム画面、OCR結果、端末情報、ログを無加工で外部共有しない。
