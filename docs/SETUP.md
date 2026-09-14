# v12 ZIPからのセットアップとBlueStacks設定

## 対応環境

Windows専用です。以下の組み合わせだけを対応・検証しています。

- Windows 10/11
- BlueStacks 5（Windows版）
- Python 3.11系（64-bit推奨）
- Android SDK Platform-Tools（ADB）

macOS、Linux、他のAndroidエミュレーターは対象外です。

## 1. ZIPを展開する

配布ZIP `priconner_labyrinth_boss_gacha.zip` を任意の作業フォルダーへ展開します。以降のコマンドは、`README.md` と `main.py` がある展開先のフォルダーで実行します。

PowerShellで展開先へ移動する例:

```powershell
cd C:\path\to\priconner_labyrinth_boss_gacha
```

`main.py` が見つからない場合は、ZIPを二重に展開していないか、現在のフォルダーが正しいか確認してください。

## 必要な環境

- Windows上のBlueStacks 5を検証対象とします。正確なバージョンはBlueStacks設定のバージョン情報で確認してください。
- Python 3.11系をインストールし、PowerShellで `python --version` が実行できる状態にします。
- Android SDK Platform-Tools（ADB）をインストールし、PowerShellで `adb version` が実行できる状態にします。
- BlueStacksの対象インスタンスは最初の確認時は1つだけ起動します。

PythonとADBのインストール時にPATHへ追加する設定が表示された場合は有効にしてください。既に別バージョンのPythonが入っている場合でも、`python --version` で3.11系が選ばれていることを確認します。

## 2. Python依存関係を導入する

展開先フォルダーでPowerShellを開き、次を実行します。

```powershell
python -m pip install -r requirements.txt
```

開発・テストも行う場合は、任意で仮想環境を使えます。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

PowerShellの実行ポリシーで有効化が拒否された場合は、仮想環境を使わず最初のインストール方法を使用してください。

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

ラビリンス入口画面を表示し、まずGUIから確認します。GUIの「試行回数」は初回確認では `1` にしてください。

```powershell
python main.py
```

ホーム画面から入口へ移動する場合:

```powershell
python scripts/task_launch_labyrinth_live.py --serial 127.0.0.1:5555
```

このコマンドはホーム画面から入口へ移動するテンプレート方式の補助機能です。OCRサービスや追加のOCR依存は不要です。

GUIを使う場合:

```powershell
python main.py
```

GUIのADB serial初期値は `127.0.0.1:5555` です。

## セットアップ完了の判定

次の3点を満たせば、基本セットアップは完了です。

1. `python --version` が3.11系を表示する
2. `adb devices -l` に対象端末が `device` と表示される
3. `python main.py live --serial 127.0.0.1:5555` が安全停止せず、入口画面を認識する

初回確認ではGUIの確認・実行ボタンを使い、試行回数を `1` にしてください。認識結果と画面状態を確認してから、本番の試行回数に変更します。CLIを使う場合は `--execute` なしのpreflightを先に実行します。

## よくある問題

- `python` が見つからない: Pythonをインストールし、PATHを追加してPowerShellを開き直します。
- `adb` が見つからない: Platform-ToolsのフォルダーをPATHに追加するか、`-AdbPath` を指定します。
- `no devices/emulators found`: BlueStacksのADBを有効にし、ポート番号と `--serial` の値を一致させます。
- 画面サイズ・DPIが違う: BlueStacksを `1280x720`、DPI `240` に戻してから再確認します。
- 入口画面を認識できない: ゲームをログイン済みにし、横画面、表示倍率、フルスクリーン、通知・ポップアップを確認します。

ゲーム、BlueStacks、Windows、Python依存パッケージを更新した場合は、ADB、解像度、DPI、テンプレート認識を再確認します。スリープ・画面ロック・自動再起動を避け、通知やポップアップは実行前に処理してください。

現在使用しているBlueStacks設定を維持する限り、既存のテンプレートをそのまま使用できます。テンプレートの再取得は、解像度・DPI・表示設定またはゲーム画面レイアウトが変わった場合だけ行ってください。
