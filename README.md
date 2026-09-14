# priconner_labyrinth_boss_gacha

『プリコネ』ラビリンスのボスガチャ処理を、画面認識と安全停止付きで管理・実行するプロジェクトです。

## 対応OS

Windows専用です。BlueStacks 5、PowerShell、Windows版Python、Windows用Android SDK Platform-Tools（ADB）を前提にしています。macOS、Linux、他のAndroidエミュレーターは対応・検証していません。

## まず読む

1. [ZIPからのセットアップとBlueStacks設定](docs/SETUP.md)
2. [実機運用手順](docs/OPERATIONS.md)
3. [設定と対応範囲](docs/CONFIGURATION.md)
4. [ドキュメント一覧](docs/INDEX.md)

初回はGUIを起動し、ラビリンス入口画面を認識できることを確認してください。GUIの「試行回数」欄で、確認時は `1`、本番時は必要な回数を設定できます。

配布ZIPを使う場合は、`priconner_labyrinth_boss_gacha.zip` を展開し、展開先をPowerShellの作業フォルダーにしてから[セットアップ手順](docs/SETUP.md)を実行してください。

GUIの起動:

```powershell
python main.py
```

CLIで実行する場合は `--passports N` で最大試行回数を指定できます。これはパスポート消費数ではありません。ボスガチャは撤退運用のため、パスポートは消費しません。

## 対応範囲

- 主な検証対象: BlueStacks 5（Windows）、ラビリンスのエリア3・5、難易度10
- 画面条件: 横画面、Android解像度 `1280x720`、DPI `240`
- 開始地点: ラビリンス入口画面（新規挑戦または再開を選択できる画面）
- 対象外ボス: 撤退確認を行い、入口へ戻って次の試行へ進む
- 対象ボス: `matched` で処理を終了
- 認識不能・ADB異常・想定外画面: `safety_stop` で入力を停止

対応外のエリア、難易度、画面レイアウトは未検証です。更新後は[セットアップ](docs/SETUP.md)と[運用手順](docs/OPERATIONS.md)を再確認してください。

## ファイル構成

- `main.py`: GUIとCLIの入口
- `src/`: ボスガチャ、画面認識、判断、安全停止の実装
- `configs/`: 対象ボス、ギルド、画面認識などの設定
- `data/template_migration/templates/`: 画面認識用テンプレート
- `scripts/`: preflight、起動、診断、実機タスク
- `docs/`: 詳細資料

## 開発・テスト

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

実機を操作しない判定デバッグは[自動テスト](docs/AUTOMATED_TESTS.md)と[開発手順](docs/DEVELOPMENT.md)を参照してください。

GitHubへのpushとPull Requestでは、`.github/workflows/ci.yml` によりcompile、テスト、ruff、画面カタログ、安全監査を自動実行します。

GUIを使う場合は、プロジェクトルートで `python main.py` を実行します。ADB serialの初期値はCLIと同じ `127.0.0.1:5555` です。

## 安全・ライセンス

ゲームの利用規約・運営方針を確認し、自己責任で使用してください。テンプレート、ゲーム画面、ログ、OCR結果、端末情報を無加工で再配布・共有しないでください。明示的なオープンソースライセンスは付与していません。詳細は[SECURITY.md](SECURITY.md)を参照してください。
