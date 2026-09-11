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
- 内蔵した共通基盤（テンプレート画面認識、ADB、設定）を利用した実機実行

画面キャプチャとADB入力はアダプター経由で扱います。実機処理は安全停止を優先し、画面や設定を確認できない場合は入力を行いません。

## ボス候補と今回の対象

エリアには複数のボス候補が出現します。候補は設定ファイルの `order` 順（弱い順）で表示します。今回の既定の対象組み合わせは、grep で確認した設定に基づき次の2体です。

| エリア | ボス候補 | 今回の対象 |
| --- | --- | --- |
| 3 | マダムエレクトラ、フロストハウンド、ダークガーゴイル、グレーターゴーレム、ベノムサラマンドラ | ベノムサラマンドラ |
| 5 | キマイラ、ゴブリンロード、ラースドラゴン、アルティマガーディアン、ジャバウォック | ゴブリンロード |

候補一覧は `configs/boss_area3.json` と `configs/boss_area5.json`、対象組み合わせの既定値は `configs/labyrinth_target_policy.json` に分離して管理しています。複数候補を許容する場合は、CLIで同じエリアのオプションを複数回指定できます。ただし、対象を変更する場合はエリア3・5の両方を明示してください。

## ディレクトリ構成

```text
src/boss_gacha/                 ボスガチャのドメインロジック
scripts/debug_boss_gacha.py     ADBなしの判定デバッグ
scripts/task_boss_gacha_live.py ADB/テンプレートを使う実機エントリーポイント
tests/                          ボスガチャ専用テスト
docs/                           運用・開発手順
```

## 前提環境

このリポジトリは単体で動作する構成です。別リポジトリは実行時に必要ありません。ADB、OpenCV、および本 README に記載するローカル設定が必要です。詳細は [実機運用手順](docs/OPERATIONS.md) を参照してください。

## 環境整備手順

### 1. リポジトリを配置する

このプロジェクトを任意の作業フォルダーへ clone します。設定、テンプレート画面認識、ADB の実行基盤はすべてリポジトリ内に含まれます。

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

依存定義を追加した場合は、その定義ファイルを優先してインストールしてください。

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

#### BlueStacks 5（Windows）の推奨設定

1. BlueStacks を起動し、対象のゲームを入れるインスタンスを1つに決めます。複数インスタンスを同時に起動すると、接続先や画面キャプチャ対象を取り違えやすいため、最初の動作確認では対象インスタンスだけを起動します。
2. BlueStacks の設定（歯車）を開き、`詳細設定` または `Advanced` にある Android Debug Bridge（ADB）を有効にします。設定名はバージョンにより `Android デバッグを有効にする` など異なります。
3. 表示された ADB ポート番号を控えます。既定値は `5555` ですが、インスタンスごとに異なる場合があります。ポート番号が表示されない版では、BlueStacks の ADB設定を保存して再起動した後、`adb devices` または `adb connect` の結果で確認します。
4. 表示設定は横向き、解像度 `1280x720`、DPI `240` にします。解像度・表示倍率・縦横比を変更するとテンプレートやタップ座標が一致せず、安全停止することがあります。
5. ゲーム画面がBlueStacksのAndroidクライアント領域いっぱいに表示される状態にします。Windowsのタイトルバー、ウィンドウ位置、モニターの拡大率は座標基準ではありませんが、クライアント領域を隠す他のウィンドウは置かないでください。

#### DPI（Android density）

本プロジェクトの検証基準はDPI `240` です。DPIを変更するとゲーム内の文字・ボタン・レイアウトが変わり、同じ `1280x720` でも画像認識が失敗することがあります。Windows側の表示スケールではなく、BlueStacks内のAndroid表示密度を対象にしてください。

現在値は次で確認できます。

```powershell
adb -s 127.0.0.1:5555 shell wm density
```

出力された `Physical density`（物理値）と `Override density`（上書き値）を確認し、実効値が `240` になるようにします。`Override density` が表示されている場合は上書き設定が有効です。変更後はBlueStacksとゲームを再起動し、画面テンプレートのpreflightを実行して、画面比率・主要ボタン・OCR領域が一致することを確認します。

#### 接続先の指定

同一PC上のBlueStacksへ接続する場合は `127.0.0.1:<ポート>` を使用します。複数インスタンスを使う場合は、それぞれのADBポートを混同しないようにし、実行時の `--serial` と同じ値を使います。外部ネットワークへADBを公開したり、`0.0.0.0` で待ち受けたりする設定は使用しないでください。

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

画面認識は座標とテンプレートに依存するため、BlueStacks のウィンドウサイズ、DPI、ゲーム内表示倍率、縦横比を、検証済みの環境から変更しないでください。ADB 操作ではタイトルバーやウィンドウ枠を基準にせず、Android クライアント画面の解像度を取得して `1280x720` 基準の座標を自動補正します。画面比率が異なる場合は誤操作防止のため安全停止します。

### 5. テンプレートを準備する

実機テンプレートは `configs/live_screen_templates.json` から参照します。テンプレートが不足・不一致の場合は入力せず安全停止します。OCRモデルの準備は不要です。

### 実行前の前提状態

- 対応対象は Windows 上の BlueStacks 5 を主な検証環境とします。BlueStacksのバージョンを更新した場合は、ADB接続、画面サイズ、DPI、テンプレートを再確認してください。
- BlueStacksの対象インスタンスを起動し、ゲームへログインした状態にします。ゲームが起動していない場合は、先に手動で起動してください。
- 実機処理はラビリンスの入口画面（新規挑戦または挑戦中の再開を選択できる画面）から開始します。別の画面では入口までの遷移を自動で推測しません。
- 対象アプリのパッケージ名が必要な診断では、`adb -s 127.0.0.1:5555 shell pm list packages` で確認した値を指定します。パッケージ名は環境により異なるため、READMEに固定値は記載しません。

### 初回確認と安全停止時の対応

最初は必ず `--execute` なしで起動し、ADB接続、画面比率、入口画面、主要テンプレートの認識結果を確認します。`--execute` は実際のタップやスワイプを有効にするため、画面が一致していることを確認してから使用してください。

`safety_stop` になった場合は、BlueStacksの対象インスタンス、ADB serial、解像度 `1280x720`、DPI `240`、ゲーム画面、テンプレート配置の順に確認します。画面が曖昧なまま再実行せず、ゲームを入口画面へ戻してから再度preflightを実行してください。ログとキャプチャは `data/observations/live/` に保存されますが、ゲーム画面や端末情報を含む可能性があるため、共有・公開前に確認してください。

ADBが `offline`、`unauthorized`、または表示されない場合は、次を順に実行します。

```powershell
adb disconnect 127.0.0.1:5555
adb kill-server
adb start-server
adb connect 127.0.0.1:5555
adb devices -l
```

それでも直らない場合はBlueStacksを再起動し、ADB設定とポート番号を再確認します。

```powershell
python main.py live --serial 127.0.0.1:5555
```

### 6. preflight で確認する

`--execute` を付けずに起動し、現在画面の認識結果だけを確認します。この段階では ADB の入力操作は行いません。

```powershell
$env:PYTHONPATH = "$PWD\src"
python main.py live --serial 127.0.0.1:5555
```

画面 ID が取得でき、エラーや安全停止理由がないことを確認してから、[実機運用手順](docs/OPERATIONS.md) の実行手順へ進みます。

画面テンプレートの画像は実機キャプチャから準備します。これらにはゲーム画面が含まれるため、`data/observations/live/` にローカル保存し、GitHub には commit しません。テンプレートが未配置の場合、preflight は `screen_templates_unavailable` で安全停止します。

ADB、解像度、テンプレートの不足をまとめて確認する場合は、次を実行します。

```powershell
python scripts/check_live_environment.py --serial 127.0.0.1:5555
```

## 追加で確認しておく項目

公開・運用を安定させるには、次の情報も README または `docs/` に残すと便利です。

- 対応 Python、OpenCV、Pydantic のバージョン
- Windows・macOS・Linux ごとの BlueStacks 対応範囲と既知の制限
- 画面解像度、DPI、ゲーム内表示倍率などの検証済み環境
- `configs/` の各設定ファイルの役割と変更方法
- 終了コードと JSON の `status` / `reason` の一覧
- テンプレート画像の取得先、配置方法、ライセンス
- ログ・スクリーンショットの個人情報確認と削除方法
- 実機を操作しないテスト方法と、実機での最終確認手順
- ライセンス、問い合わせ先、Issue で受け付けない内容

未完了タスクと優先順位は [docs/TASKS.md](docs/TASKS.md) で管理します。

## セットアップとテスト

リポジトリ直下で実行します。

```powershell
python -m pytest -q
```

判定デバッグは、観測結果 JSON を指定して実行します。

```powershell
python scripts/debug_boss_gacha.py --help
python scripts/debug_boss_gacha.py --observations path\to\observations.json
```

## `main.py` から実行する

引数なしで起動すると操作ウィンドウが開きます。ウィンドウの「開始」は確認ダイアログの後に ADB 入力を有効にした実機処理を開始し、「停止（即時）」は実行中のプロセスを直ちに終了します。停止・異常終了後は「再開（自動判定）」を押すと、現在画面を内部判定して再開します。画面が曖昧な場合は安全停止します。

入力する項目は ADB serial、今回の試行回数、ギルド、エリア 3/5 の許容ボスです。ギルドはゲーム内カード表記で `configs/labyrinth_guild_starting_members.json` に登録された全候補から選択でき、既定値は美食殿です。難易度は現在対応している既定値に固定しています。既定の試行上限は1000回です。ボスガチャは撤退運用のため、パスポートは消費しません。開始前に BlueStacks の接続と対象画面を確認してください。

実機処理は、ラビリンスの入口画面（新規挑戦または挑戦中の再開を選択できる画面）を表示した状態から開始してください。開始時に現在画面を再取得し、入口画面であることと新規／再開モードを確認してから次の操作へ進みます。入口画面を確認できない場合は、ADB入力を行わず安全停止します。ホーム画面から入口まで移動する場合は `python scripts/task_launch_labyrinth_live.py --serial 127.0.0.1:5555` を使用します。

GUIで選択したADB serial、試行回数、ギルド、ボスのチェック状態は、次回起動時にローカル設定から復元します。この設定ファイルは端末固有情報を含むためGitHubへ公開しません。

```powershell
python main.py
```

既存の CLI モードも利用できます。既存スクリプトのオプションはそのまま後ろに渡されます。

```powershell
# ADBを使わない判定デバッグ
python main.py debug --observations path\to\observations.json

# 実機 preflight（入力なし）
python main.py live --serial 127.0.0.1:5555

# 利用枚数と対象ボスを指定した実機実行
python main.py live --execute --passports 1 `
  --area3-boss "ボス名" --area5-boss "ボス名"
```

各モードの全オプションは `python main.py debug --help` または `python main.py live --help` で確認できます。

## 実機実行

最初は必ず preflight（`--execute` なし）で画面認識だけを確認します。

```powershell
python main.py live --serial 127.0.0.1:5555
```

入力を有効にする場合は、利用枚数、エリア 3/5 の許容ボスを明示します。

```powershell
python main.py live `
  --execute --passports 1 `
  --area3-boss "ボス名" --area5-boss "ボス名"
```

`--passports N` は、パスポート消費数ではなく、ボスガチャ処理の最大試行回数を指定する互換引数です。既定値は1000回で、試験時は `--passports 1` を指定します。ボスガチャは撤退するためパスポートを消費しません。結果は `matched`、`max_attempts`、`safety_stop` として区別されます。実機操作の全オプションと復帰方法は [docs/OPERATIONS.md](docs/OPERATIONS.md) を参照してください。

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

- BlueStacks のスクリーンショット、操作ログ、タイミングログ
- ADB のシリアル番号、端末情報、個人環境が分かる設定やエクスポート
- 大容量のモデルファイル
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
