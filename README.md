# priconner_labyrinth_boss_gacha

『プリコネ』のラビリンスにおける、ボスガチャ処理を単体で管理・実行するプロジェクトです。

## 公開範囲と免責

このリポジトリは、個人の研究・検証およびコード管理を目的として公開しています。ゲーム内での自動操作を想定したコードを含むため、一般利用や第三者への提供を目的としたものではありません。

利用にあたっては、対象ゲームの利用規約・運営方針・プラットフォームの規約を必ず確認し、それらに反する用途では使用しないでください。利用によって発生したアカウント停止、データ消失、損害その他の問題について、作者は責任を負いません。ゲーム画面、画像、設定、ログなど第三者に帰属する情報の取り扱いにも、利用者自身が責任を持ってください。

なお、GitHub 上で公開されていることは、ゲーム運営からの許諾や推奨を意味しません。公開内容は予告なく変更・削除する場合があります。

## ライセンス

明示的なオープンソースライセンスは付与していません。利用・改変・再配布を行う場合は、作者の許可を得てください。セキュリティ上の注意は [SECURITY.md](SECURITY.md) を参照してください。

## 目的

- 対象ボスの判定と最大試行回数の制御
- 画面遷移のガード付きリトライ
- 実機操作を行わない単体テスト・判定デバッグ
- 内蔵した共通基盤（画面認識、OCR、ADB、設定）を利用した実機実行

画面キャプチャ、OCR、ADB 入力そのものは本プロジェクトに実装せず、外部から注入する構成です。実機処理は安全停止を優先し、画面や設定を確認できない場合は入力を行いません。

## ディレクトリ構成

```text
src/boss_gacha/                 ボスガチャのドメインロジック
scripts/debug_boss_gacha.py     ADB/OCR なしの判定デバッグ
scripts/task_boss_gacha_live.py ADB/OCR を使う実機エントリーポイント
tests/                          ボスガチャ専用テスト
docs/                           運用・開発手順
```

## 前提環境

このリポジトリは単体で動作する構成です。別リポジトリは実行時に必要ありません。PaddleOCR、ADB、および本 README に記載するローカル設定が必要です。詳細は [実機運用手順](docs/OPERATIONS.md) を参照してください。

## 環境整備手順

### 1. リポジトリを配置する

このプロジェクトを任意の作業フォルダーへ clone します。設定、画面認識、ADB/OCR の実行基盤はすべてリポジトリ内に含まれます。

```powershell
git clone <公開リポジトリのURL>
cd priconner_labyrinth_boss_gacha
```

`configs/`、`src/vision/`、`src/decision/`、`scripts/labyrinth_route.py` が存在することを確認します。

### 2. Python 環境を用意する

Python 3.11 系と、実機処理が要求する依存パッケージを用意します。PowerShell の例:

```powershell
cd D:\git\priconner_labyrinth_boss_gacha
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

依存定義を追加した場合は、その定義ファイルを優先してインストールしてください。GPU を使う場合は、PaddlePaddle と GPU ドライバーの対応を確認してください。

### 3. ADB クライアントを準備する

ADB は Android SDK Platform-Tools に含まれるコマンドラインツールです。実行する OS に対応した Platform-Tools を Android Developers の公式配布元から取得し、展開したディレクトリを PATH に追加します。パッケージマネージャーを使う場合も、`adb version` が実行できることを確認してください。

```powershell
# Windows PowerShell
adb version
```

```bash
# macOS / Linux
adb version
```

OS ごとの確認事項:

- Windows: `adb.exe` のあるディレクトリをユーザーまたはシステム PATH に追加します。必要に応じて Windows Defender ファイアウォールでローカル接続を許可します。
- macOS: Platform-Tools を PATH に追加し、ターミナルから `adb` を実行できるようにします。BlueStacks の対応状況と ADB ポートは使用する製品版を確認してください。
- Linux: Platform-Tools を PATH に追加します。USB 接続端末を使う場合は udev ルールが必要ですが、本プロジェクトの既定接続は TCP の localhost です。

### 4. BlueStacks の ADB を設定する

BlueStacks 側で、使用するインスタンスの ADB（Android Debug Bridge）接続を有効にします。設定画面の名称や場所は BlueStacks のバージョンによって異なるため、`ADB を有効化する設定` を確認してください。

本プロジェクトの既定値は `127.0.0.1:5555` です。BlueStacks 側で表示される ADB ポートが異なる場合は、実際のポートを `--serial` に渡します。

```powershell
# Android SDK platform-tools の adb.exe が PATH にあることを確認
adb version

# BlueStacks の ADB ポートへ接続（ポートは環境に合わせて変更）
adb connect 127.0.0.1:5555
adb devices
```

`adb devices` に対象端末が `device` として表示されることを確認します。`offline`、`unauthorized`、または何も表示されない場合は、BlueStacks の起動状態、ADB 設定、ポート、Windows ファイアウォールを確認してください。

接続を解除・再接続する場合:

```bash
adb disconnect 127.0.0.1:5555
adb kill-server
adb start-server
adb connect 127.0.0.1:5555
adb devices -l
```

診断には次のコマンドも使えます。`wm size` の結果が、テンプレートや ROI を作成した画面サイズと一致することを確認してください。

```bash
adb -s 127.0.0.1:5555 get-state
adb -s 127.0.0.1:5555 shell wm size
adb -s 127.0.0.1:5555 shell wm density
```

画面認識は座標・テンプレート・OCR 領域に依存するため、BlueStacks のウィンドウサイズ、DPI、ゲーム内表示倍率、縦横比を、検証済みの環境から変更しないでください。ADB 操作ではタイトルバーやウィンドウ枠を基準にせず、Android クライアント画面の解像度を取得して `1280x720` 基準の座標を自動補正します。画面比率が異なる場合は誤操作防止のため安全停止します。

### 5. OCR を準備する

標準の日本語モデルを使う場合は、実行時に `--default-models` を指定します。標準モデルは、ゲーム画面の短い日本語ラベルでの実測結果を優先して `PP-OCRv4` mobile を使用します。独自モデルを使う場合は検出モデルと認識モデルを両方指定します。

```powershell
python main.py live `
  --serial 127.0.0.1:5555 --default-models
```

### 6. preflight で確認する

`--execute` を付けずに起動し、現在画面の認識結果だけを確認します。この段階では ADB の入力操作は行いません。

```powershell
$env:PYTHONPATH = "$PWD\src"
python main.py live --serial 127.0.0.1:5555 --default-models
```

画面 ID が取得でき、エラーや安全停止理由がないことを確認してから、[実機運用手順](docs/OPERATIONS.md) の実行手順へ進みます。

画面テンプレートの画像は実機キャプチャから準備します。これらにはゲーム画面が含まれるため、`data/observations/live/` にローカル保存し、GitHub には commit しません。テンプレートが未配置の場合、preflight は `screen_templates_unavailable` で安全停止します。

ADB、解像度、テンプレートの不足をまとめて確認する場合は、次を実行します。

```powershell
python scripts/check_live_environment.py --serial 127.0.0.1:5555
```

## 追加で確認しておく項目

公開・運用を安定させるには、次の情報も README または `docs/` に残すと便利です。

- 対応 Python、PaddleOCR、PaddlePaddle、OpenCV、Pydantic のバージョン
- Windows・macOS・Linux ごとの BlueStacks 対応範囲と既知の制限
- 画面解像度、DPI、ゲーム内表示倍率などの検証済み環境
- `configs/` の各設定ファイルの役割と変更方法
- 終了コードと JSON の `status` / `reason` の一覧
- OCR モデルの取得先、配置方法、ライセンス
- ログ・スクリーンショットの個人情報確認と削除方法
- 実機を操作しないテスト方法と、実機での最終確認手順
- ライセンス、問い合わせ先、Issue で受け付けない内容

## セットアップとテスト

リポジトリ直下で実行します。

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q
```

判定デバッグは、観測結果 JSON を指定して実行します。

```powershell
python scripts/debug_boss_gacha.py --help
python scripts/debug_boss_gacha.py --observations path\to\observations.json
```

## `main.py` から実行する

引数なしで起動すると操作ウィンドウが開きます。ウィンドウの「開始」は ADB 入力を有効にした実機処理を開始し、「停止（即時）」は実行中のプロセスを直ちに終了します。停止・異常終了後は再開画面を選び、「再開」を押してください。

入力する項目は ADB serial、パスポート枚数、エリア 3/5 の許容ボスです。開始前に BlueStacks の接続と対象画面を確認してください。

```powershell
python main.py
```

既存の CLI モードも利用できます。既存スクリプトのオプションはそのまま後ろに渡されます。

```powershell
# ADBを使わない判定デバッグ
python main.py debug --observations path\to\observations.json

# 実機 preflight（入力なし）
python main.py live --serial 127.0.0.1:5555 --default-models

# 利用枚数と対象ボスを指定した実機実行
python main.py live --execute --passports 10 --default-models `
  --area3-boss "ボス名" --area5-boss "ボス名"
```

各モードの全オプションは `python main.py debug --help` または `python main.py live --help` で確認できます。

## 実機実行

最初は必ず preflight（`--execute` なし）で画面認識だけを確認します。

```powershell
python main.py live --serial 127.0.0.1:5555 --default-models
```

入力を有効にする場合は、利用枚数、エリア 3/5 の許容ボスを明示します。

```powershell
python main.py live `
  --execute --passports 10 --default-models `
  --area3-boss "ボス名" --area5-boss "ボス名"
```

`--passports 0`、許容ボス未指定、画面不一致、OCR モデル未設定などの場合は安全停止します。実機操作の全オプションと復帰方法は [docs/OPERATIONS.md](docs/OPERATIONS.md) を参照してください。

## Git での変更手順

変更前に作業ツリーを確認し、関係のない変更を混ぜないでください。

```powershell
git status --short
git diff -- README.md docs/
python -m pytest -q
git diff --check
```

コミットメッセージは変更内容が分かる短い命令形にし、実機操作を伴う変更では対象画面・安全停止条件・検証結果を本文に残します。レビュー前の確認項目は [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)、GitHub 公開手順は [docs/PUBLISHING.md](docs/PUBLISHING.md) を参照してください。

### 公開前チェック

GitHub に push する前に、次のようなファイルをコミット対象から外してください。これらは `.gitignore` でも除外しています。

- BlueStacks のスクリーンショット、OCR 結果、操作ログ、タイミングログ
- ADB のシリアル番号、端末情報、個人環境が分かる設定やエクスポート
- OCR モデルや大容量のモデルファイル
- `.env`、API キー、トークン、パスワード、秘密鍵
- Python の仮想環境、キャッシュ、IDE の個人設定

公開前には、少なくとも次のコマンドで対象ファイルと秘密情報らしき文字列を確認してください。

```powershell
git status --short
git ls-files
rg -n -i "api[_-]?key|secret|token|password|passwd|private[_-]?key|client[_-]?secret|authorization|bearer" -S . -g '!*.pyc'
```

過去のコミットに秘密情報を含めてしまった場合は、ファイルを削除するだけでは不十分です。該当トークンを失効・再発行し、Git 履歴の除去方法を確認してから公開してください。

## 安全上の注意

- `--execute` は ADB 入力を有効化するため、確認なしに使用しないでください。
- 実機処理中に画面が想定外になった場合は、処理を継続せず安全停止させます。
- `data/observations/live/` のキャプチャや操作ログには実行環境の情報が含まれる可能性があるため、共有前に内容を確認してください。
