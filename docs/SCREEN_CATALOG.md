# 画面認識カタログ

このカタログは `configs/live_screen_templates.json`、`AdbTemplateScreenProbe._SCREEN_TARGETS`、`ADB_SCREEN_COORDINATES` の対応関係を確認するための索引です。座標系はADB画面の1280×720です。

## 起動・入口

| screen_id | 役割 | 入力条件 |
| --- | --- | --- |
| `startup_splash` | 起動ロゴ | 待機のみ |
| `title` | タイトル | タイトル認識後の開始入力1回 |
| `notice` | お知らせ | 専用の閉じるテンプレート一致時のみ |
| `startup_error` | 起動エラー | 専用のタイトルへテンプレート一致時のみ |
| `quest_menu` / `labyrinth_top` | ラビリンス入口 | 画面固有ラベル一致時のみ |
| `guild_select` / `guild_confirm` | ギルド選択 | OCRまたは専用確認ボタン一致時のみ |

## ガチャ・マップ

`bonus`、`initial_char`、`character_join`、`boss_map`、`boss_detail`、`withdraw_confirm`、`move_confirm`、`event_confirm`、`event_battle_choice`、`item_reward`、`relic_choice` を管理します。共通の「閉じる」は画面IDだけで使わず、画面固有ターゲットを優先します。

## 戦闘・ショップ

`battle_tile_normal`、`battle_party`、`battle_party_ready`、`battle_victory`、`battle_reward`、`character_bonus`、`ex_equipment`、`ex_auto_dialog`、`ex_equipment_conflict`、`shop`、`shop_purchase_confirm`、`shop_purchase_complete`、`shop_exit_confirm` を管理します。

## 機械検査

```powershell
python scripts/validate_screen_catalog.py
```

重複JSONキー、ROIと座標の画面外、未登録画面、画面に許可されない操作ラベル、参照されないターゲットを検出します。エラーがある画面は実行可能画面へ追加しません。warningは不足テンプレートの準備項目です。
