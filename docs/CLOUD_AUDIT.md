# Cloud作業の検証記録

2026-09-06。全タスクをCloud実行として監査する。対象はC1〜C8、ギルド横スクロール、日本語OCR・全ギルド検証、GitHub公開。Cloud側のコード・テスト・設計レビューと、不足証拠を分離して記録する。

| 要件 | 実装・成果物 | 確認した証拠 |
| --- | --- | --- |
| C1 早期撤退回数 | runner.py | test_early_rejection_counts_each_attempt_and_stops_at_100：100回で終了 |
| C2 複数許容 | live_workflow.py・実機CLI引数接続 | test_second_allowed_left_boss_is_not_rejected、誤撤退防止テスト |
| C3 左右復帰 | live_workflow.py | test_resume_from_right_detail_reopens_left_before_reading：マップ復帰→左開き直し→OCR |
| C4 結果表示 | main.py・CLI最終JSON | test_final_result_is_processed_before_exit：3種類の結果が終了後も保持される |
| C5 回数指定 | 実機CLI→runner | `--attempts` 1〜1000。CLI・Controller・GUIの境界テスト |
| C6 保存復元 | main.py | 4種の破損JSON、保存・復元、置換失敗時の既存設定保持 |
| C7 OCR照合 | name_matching.py | test_name_matching.py：空文字・断片・曖昧一致を拒否 |
| C8 分類 | TASK_REVIEW.md・TASKS.md・README | 全IDに6評価軸、理由、最小入力、分割方針を対応付け |
| H1 Cloud側 | guild_selection.py・画面プローブ・ADBガード | 複数行結合・隣接カード拒否・14開始位置の走査モデル・固定見出し優先・再試行テスト |
| H2 Cloud側 | PUBLISHING.md | remote未設定、著者メール2種類、履歴の対象ファイル名検査結果を記録 |

| L1 Cloud側 | labyrinth_ocr_regions.json・OCR adapter・OCR/名前照合テスト | ROI定義、正規化座標、信頼度・曖昧一致拒否を確認。実画像はリポジトリ内にないため実機OCR精度は未確認 |
| L2 Cloud側 | pytest・ADBモック | ADB接続チェックをモックした対象回帰テストが成功。実機不要のCLI検証を確認 |

## Cloud側完了境界

- 完了：設計、コード修正、テスト、失敗原因の整理、タスク分類、公開候補のレビュー。
- 未確認：実機画面・ADB・ローカルOCRモデルからの証拠が未提供の検証。
- 未実施：認証付きGitHub公開操作。Cloud側では公開候補・履歴・手順レビューまで完了。
- 回帰確認：`PYTHONPATH=src;.; pytest -q` で56件成功（2026-09-06）。
- 追加回帰確認：`python -m pytest -q tests/test_boss_gacha_controller.py tests/test_live_cli_limits.py tests/test_main_gui.py tests/test_boss_gacha_runner.py tests/test_boss_gacha_live_workflow.py` で36件成功。1000回上限、ADBチェックのモック、GUI引数接続を確認。

## 2026-09-06 Cloud実行結果

- 全56テスト成功。
- リポジトリ内のPNG/JPG/JPEG実画像は0件。日本語OCRの実画像精度と実機ギルド受入は、Cloudだけでは判定不能。
- Git remoteは未設定。公開候補・除外方針・手順レビューは完了しているが、公開先URLと認証がないためpushは未実施。
- 秘密情報スキャンは、コード中の一般語（`token`等）を除き、実値の混入なしを確認するには追加の目視レビューが必要。

## Cloudで継続するが、証拠不足のため未確認

- 14ギルドのカード名と実画面OCRを照合し、選択成功または停止理由を記録する。現在は実機画像がないため、スワイプ1回で1カード以上進むというテスト仮定をCloudシミュレーションで確認済み、実測は未確認。
- ギルド名や閉じるボタンの実画像認識、開始→ボス判定→撤退の一連動作、停止と再開を検証する。
- 表示サイズ1280x720以外のOCR座標・ROIは未検証。難易度の自動変更は未対応。
- 新規公開先と著者メールの公開方法をCloudで決定できる入力が不足している。Git履歴は変更していない。

実機結果が仮定に反する場合は、失敗ケースを縮約してH1/L1から追加のCloud修正へ戻す。現在の回帰テスト成功は、全ギルド実機成功を意味しない。

## 実機確認からCloudへ渡す分割単位

以下はCloud完了タスクの再実施ではなく、未確認の実機・ADB・OCR証拠だけを収集するLocal/HYBRID作業である。各単位は30〜60分を目安にし、未認識画面、ADB異常、OCR低信頼、座標不一致が発生した場合は入力を続けず安全停止する。

| Task ID | 実機作業 | 目安 | 期待結果 | Cloud投入物 |
| --- | --- | ---: | --- | --- |
| H1b-1 | ADB・解像度・テンプレート・guild_select基準取得 | 30分 | `device`、1280x720、画面認識、基準PNG | `JSONL 1行 + 基準PNG` |
| H1b-2 | 登録ギルド1〜4の選択受入 | 45分 | 各ギルド成功または安全停止 | `guild_result JSONL 4行 + PNG` |
| H1b-3 | 登録ギルド5〜8の選択受入 | 45分 | 各ギルド成功または安全停止 | `guild_result JSONL 4行 + PNG` |
| H1b-4 | 登録ギルド9〜11の選択受入 | 45分 | 各ギルド成功または安全停止 | `guild_result JSONL 3行 + PNG` |
| H1b-5 | 登録ギルド12〜14の選択受入 | 45分 | 各ギルド成功または安全停止 | `guild_result JSONL 3行 + PNG` |
| L1b-1 | OCR評価用実機画像の収集 | 45分 | 5〜10件の対象画像とマニフェスト | `image_manifest.jsonl + PNG` |
| L1b-2 | OCR正解ラベル・ROI付与 | 45分 | 画像ごとの正解テキスト、エリア、ROI | `labels.jsonl + PNG` |
| L1b-3 | 実機OCR測定 | 45分 | OCR出力、信頼度、照合、処理時間 | `ocr_results.jsonl + CSV` |
| L1b-4 | 低信頼・誤読ケース再確認 | 45分 | 例外原因と再判定結果 | `exceptions.jsonl + 比較PNG` |
| L1c-1 | 正常系の選択〜ボス名OCR | 60分 | 一連の画面系列とボス名記録 | `end_to_end.jsonl + PNG` |
| L1c-2 | 対象外ボスの撤退フロー | 60分 | 撤退確認までの安全な記録 | `withdraw.jsonl + PNG` |
| L1c-3 | 未知画面・低信頼OCRの安全停止 | 45分 | 入力なし、安全停止理由あり | `safety_stop.jsonl + PNG` |
| L1c-4 | 撤退後の再開・再判定 | 60分 | 再開地点、左右再判定、操作記録 | `resume.jsonl + PNG` |
| L1c-5 | Cloud投入用マニフェスト作成 | 30分 | 欠落・個人情報を確認済みの一式 | `manifest.json + results.jsonl + summary.md` |

### Cloud投入JSONLの共通形式

```json
{"task_id":"H1b-2","run_id":"20260906-001","serial":"127.0.0.1:5555","screen_before":"guild_select","screen_after":"guild_confirm","target":"ギルド名","ocr":[{"text":"...","confidence":0.91,"bbox":[0,0,0,0]}],"action":{"type":"swipe_or_tap","point":[0,0],"swipe_count":1},"result":"success|safety_stop","stop_reason":null,"screenshots":["path"],"timestamp":"2026-09-06T00:00:00+09:00"}
```

Cloud側では、`results.jsonl` と画像マニフェストを突合し、画面遷移、OCR信頼度、座標、停止理由を分析する。`result=safety_stop` は失敗ではなく、停止条件が正しく働いたかを別評価する。

## 2026-09-06 14:02 C9a Cloud実装

- `startup_splash` をタイトルとは別の待機専用screen_idとして識別する。
- 起動途中は期限付きで観測し、title入力は最大1回、既知画面確認後だけ後続処理へ進む。
- 未知画面、title再出現、待機上限、入力失敗では追加操作せず安全停止する。
- 関連回帰39件成功。12:30-14:30の端末予約中のためADB・画面取得・アプリ操作は行わず、実機系列の確認は予約終了後へ延期した。

## 2026-09-06 15:29 C9c Cloud準備

- エラー画面からタイトルへ戻る実機結果の受入validator、入力例、最小テストを追加した。

## 2026-09-06 15:38 C9c 受入境界補強

- `title_button_bbox` が順序付きで1280x720内に収まること、画像・操作ログのパスが空でないことを受入条件へ追加した。
- 実機操作は行っていない。C9cは実エラー画面と前後screen_id、操作ログの入力待ちを継続する。

## 2026-09-06 15:49 C9b Cloud準備

- `scripts/validate_c9b_input.py`、入力例、回帰テストを追加し、お知らせ種別、1280x720内の閉じるボタン矩形、単発入力、既知ガチャ開始画面への遷移、操作前後PNG、操作ログを受入条件に固定した。
- 実機操作は行っていない。C9bは実お知らせ画面と前後screen_id、操作ログの入力待ちを継続する。
- 成功時は`startup_error`、表示エラー文、ボタン矩形、入力ちょうど1回、既知の起動画面への遷移、証跡ファイルを必須とする。
- 安全停止時は入力を最大1回に制限し、停止理由を必須化した。対象エラー実画像がないため実装・完了判定は行っていない。
- 2テスト成功。予約外だがADB・画面取得・画面操作・アプリ起動は行っていない。

## 2026-09-06 15:59 C9a 受入契約

- `scripts/validate_c9a_input.py`、入力例、回帰テスト5件を追加し、`startup_splash -> title -> 既知画面` の順序、待機上限、titleの単発入力、最終画面、証跡ファイルを検査可能にした。
- 入力例はvalidatorを通過し、対象テストは5件成功した。実機操作は行っていない。
- C9aは実機のscreen_id系列、2枚以上のPNG、操作ログが `--require-files` を通るまで `WAITING_LOCAL_INPUT` を継続する。
