# セットアップとBlueStacks設定

## 必要な環境

- Windows上のBlueStacks 5を主な検証対象とします。正確なバージョンはBlueStacks設定のバージョン情報で確認してください。
- Python 3.11系、`requirements.txt`、Android SDK Platform-Tools（ADB）を準備します。
- BlueStacksの対象インスタンスは最初の確認時は1つだけ起動します。

## BlueStacks設定

1. 詳細設定またはAdvancedでAndroid Debug Bridge（ADB）を有効にします。
2. 対象インスタンスのADBポートを確認します。既定値は `5555` ですが環境により異なります。
3. 横画面、Android解像度 `1280x720`、DPI `240` にします。
4. ゲーム内表示倍率、フルスクリーン設定、BlueStacksのクライアント領域を変更しないでください。
5. ゲームを手動で起動し、ログイン済みにします。

```powershell
adb version
adb connect 127.0.0.1:5555
adb devices -l
adb -s 127.0.0.1:5555 shell wm size
adb -s 127.0.0.1:5555 shell wm density
```

対象serialが `device`、画面サイズが `1280x720`、実効densityが `240` であることを確認します。ADBを外部ネットワークへ公開しないでください。

## 初回実行

ラビリンス入口画面を表示し、まず入力なしで確認します。

```powershell
python main.py live --serial 127.0.0.1:5555
```

ホーム画面から入口へ移動する場合:

```powershell
python scripts/task_launch_labyrinth_live.py --serial 127.0.0.1:5555
```

このコマンドはホーム画面から入口へ移動する補助機能で、PaddleOCRサービスを使用します。入口画面を手動で表示できる場合は、通常の `main.py live` 実行だけでよく、OCRの追加準備は不要です。

ホーム画面からの移動も使う場合は、追加で次を実行します。

```powershell
python -m pip install -r requirements-ocr.txt
```

GUIを使う場合:

```powershell
python main.py
```

GUIのADB serial初期値は `127.0.0.1:5555` です。

ゲーム、BlueStacks、Windows、Python依存パッケージを更新した場合は、ADB、解像度、DPI、テンプレート認識を再確認します。スリープ・画面ロック・自動再起動を避け、通知やポップアップは実行前に処理してください。
