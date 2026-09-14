# 配布用最小構成

このディレクトリは、配布時に含める最小構成の基準を示します。

配布ZIPのファイル名は `priconner_labyrinth_boss_gacha.zip` に固定します。実行入口、`src/`、実行に必要なライブタスク、`configs/`、正式テンプレート、依存定義、README、SECURITY、導入・運用手順だけを含みます。

配布物の実行環境はWindows専用です。BlueStacks 5、Windows版Python、Windows用ADBを使用します。

## ZIPからのセットアップ

### 1. ZIPを展開

`priconner_labyrinth_boss_gacha.zip` をWindowsの任意の作業フォルダーへ展開します。以降の操作は、展開後に `README.md` と `main.py` が見えるフォルダーで行います。

PowerShellで展開先へ移動する例:

```powershell
cd C:\path\to\priconner_labyrinth_boss_gacha
```

### 2. PythonとADBを準備

次をインストールしてください。

- Python 3.11系（インストール時にPATHへ追加）
- Android SDK Platform-Tools（ADB）
- BlueStacks 5（Windows版）

PowerShellで確認します。

```powershell
python --version
adb version
```

### 3. Python依存関係をインストール

展開先フォルダーで実行します。

```powershell
python -m pip install -r requirements.txt
```

### 4. BlueStacksを設定

BlueStacksで次を設定します。

1. Android Debug Bridge（ADB）を有効にする
2. 対象インスタンスのADBポートを確認する（通常は `5555`）
3. 横画面、解像度 `1280x720`、DPI `240` にする
4. ゲームを起動し、ログイン済みの状態にする

ADB接続を確認します。

```powershell
adb connect 127.0.0.1:5555
adb devices -l
adb -s 127.0.0.1:5555 shell wm size
adb -s 127.0.0.1:5555 shell wm density
```

対象端末が `device`、画面サイズが `1280x720`、DPIが `240` になっていることを確認してください。

### 5. GUIを起動

まずGUIを起動します。

```powershell
python main.py
```

GUIのADB serialは通常 `127.0.0.1:5555` です。ポートが異なる場合はGUI上で変更してください。

初回確認ではGUIの「試行回数」を `1` にし、ラビリンス入口画面で確認・実行します。認識と画面遷移に問題がなければ、本番用の試行回数へ変更してください。

### トラブルシューティング

- `python` が見つからない: PythonをPATHへ追加し、PowerShellを開き直します。
- `adb` が見つからない: Platform-ToolsをPATHへ追加します。
- `no devices/emulators found`: BlueStacksのADB、ポート、serialを確認します。
- 画面を認識できない: 横画面、`1280x720`、DPI `240`、表示倍率、ポップアップを確認します。

詳細な設定・運用手順は、同梱の [docs/SETUP.md](docs/SETUP.md) と [docs/OPERATIONS.md](docs/OPERATIONS.md) を参照してください。

テスト、実機キャプチャ、ADBログ、OCR結果、レポート、モデル、ローカル設定、取得元画像は配布対象に含めません。
