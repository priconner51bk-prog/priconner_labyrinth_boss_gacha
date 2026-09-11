# 設定と対応範囲

## 対象設定

- `configs/boss_area3.json`: エリア3のボス候補
- `configs/boss_area5.json`: エリア5のボス候補
- `configs/labyrinth_target_policy.json`: 対象ボスの既定値
- `configs/labyrinth_guild_starting_members.json`: ギルドと初期メンバー
- `configs/live_screen_templates.json`: 画面テンプレートと認識領域
- `configs/runtime_settings.json`: ADB serialなどの共通設定

主な検証対象はエリア3・5、難易度10です。対象ボスはCLI引数で明示でき、候補名は設定ファイルの表記をそのまま使用します。対応外のエリア、難易度、画面レイアウトは未検証です。

設定変更後はJSON構文、preflight、最大試行回数を小さくした実機確認の順に検証します。ADB serial、端末情報、個人環境のパス、実行キャプチャは設定ファイルへ保存・公開しないでください。

## 処理結果

- `matched`: 対象ボスを検出して終了
- `max_attempts`: 対象ボス未検出のまま最大試行回数に到達
- `safety_stop`: ADB、画面認識、テンプレート、画面遷移などの確認に失敗

対象外ボスは撤退確認後にラビリンス入口へ戻ります。ボスガチャは撤退運用で、パスポートは消費しません。
