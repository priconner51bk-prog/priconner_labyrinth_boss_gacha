# Local入力契約

この文書は、実機・ADB・実画像が必要な確認をCloud側で代替完了しないための入力契約である。
Localは実機結果だけを記録し、Cloudは受領後の集計・比較・原因分析を行う。

## 共通ルール

- 1行1イベントのJSONLとする。
- `task_id` は `docs/TASKS.md` の分割IDを使用する。
- `run_id` は実機作業単位で一意にする。
- `result` は `success`、`safety_stop`、`input_missing` のいずれかにする。
- 画面未認識、ADB異常、OCR低信頼、座標不一致の場合は入力を続けず `safety_stop` にする。
- CloudはPNGの存在だけで実機結果を推測せず、JSONLと画面系列を突合する。

## H1b: ギルド選択

Local入力例（1ギルド1行）：

```json
{"task_id":"H1b-2","run_id":"20260906-001","guild":"ギルド名","page":1,"swipe_direction":"right","swipe_count":0,"serial":"emulator-5554","wm_size":"1280x720","screen_before":"guild_select","screen_after":"guild_confirm","ocr":{"text":"ギルド名","confidence":0.98,"bbox":[100,200,300,260]},"tap_point":[200,230],"result":"success","screenshot_path":"artifacts/h1b-2-001-before.png","safety_reason":null}
```

Cloud再開条件：対象ギルドごとの行、操作前後PNG、`screen_before/after`、OCR信頼度が揃っていること。
Cloud期待結果：対象ギルドと選択結果が一致し、隣接カード誤選択がないことを集計できる。

受領前検査：`python scripts/validate_h1b_inputs.py artifacts/guild_results.jsonl --task-id H1b-2 --require-files`。
H1b-2/H1b-3は各4行、H1b-4/H1b-5は各3行を要求する。成功行は `guild_select -> guild_confirm`、OCR文字列と対象ギルドの一致、tap座標を必須とし、非成功行は安全停止理由を必須とする。

## L1b: OCR評価

Local入力は次の3ファイルで受け取る。

- `images.jsonl`：`image_id`、`screen_id`、`resolution`、`source_path`、`visible_roi`
- `labels.jsonl`：`image_id`、`area`、`expected_text`、`canonical_name`、`roi`、`label_confidence`
- `ocr_results.jsonl`：`image_id`、`text`、`confidence`、`bbox`、`matched_name`、`accepted`、`elapsed_ms`、`error`

Cloud再開条件：各 `image_id` が3ファイルで一意に対応し、画像パスが存在すること。
Cloud期待結果：正解ラベルとの一致率、候補照合の受理率、低信頼・不一致件数を集計できる。
実画像がない状態では、OCR精度や正解率を判定しない。

## L1c: 統合フロー・安全停止

L1c-1〜L1c-4は各1行を同じJSONLへ格納し、Cloud受領前に `python scripts/validate_l1c_inputs.py artifacts/l1c_results.jsonl --require-files` を実行する。4 task_id、run_id、画面系列、正常系OCR、対象外撤退、安全停止時の入力0件、撤退後再判定、全スクリーンショットの存在が揃うまで完了扱いにしない。

Local入力例（1フロー1行）：

```json
{"task_id":"L1c-3","run_id":"20260906-002","screen_sequence":["guild_select","unknown"],"trigger":"unknown_screen","ocr_confidence":null,"input_count":0,"result":"safety_stop","stop_reason":"screen_not_recognized","screenshots":["artifacts/l1c-3-002-before.png","artifacts/l1c-3-002-stop.png"]}
```

Cloud再開条件：操作ログ、画面系列、入力件数、安全停止理由、対応PNGが揃っていること。
Cloud期待結果：安全停止条件に該当するケースで入力件数が0であり、理由と画面系列が整合すること。

## C9c: エラー画面からタイトルへ復帰

C9cはエラー文と「タイトルへ」ボタンが同時に見える実画面を1件だけ受け取り、`python scripts/validate_c9c_input.py artifacts/c9c_error_recovery.jsonl --require-files` で検査する。成功は `startup_error` からタイトルまたは既知の起動画面への遷移、ボタン入力ちょうど1回、停止理由なしを必須とする。安全停止は入力0〜1回と停止理由を必須とし、再表示時の追加入力を許可しない。

Cloud再開条件：タイムゾーン付き取得時刻、表示エラー文、ボタン矩形、前後screen_id、入力回数、スクリーンショット、操作ログが揃うこと。実画像なしに文言・座標・遷移を推測しない。

## C9a: 起動途中から既知画面へ遷移

C9aは `startup_splash -> title -> 既知画面` の実機系列を1件だけ受け取り、`python scripts/validate_c9a_input.py artifacts/c9a_startup_transition.jsonl --require-files` で検査する。成功は起動途中画面がtitleより前、titleの出現と入力が各1回、待機時間が正の上限内、最終screen_idが系列末尾と一致することを必須とする。安全停止はtitle入力0〜1回と停止理由を必須とする。

Cloud再開条件：タイムゾーン付き取得時刻、screen_id系列、待機時間と上限、title入力回数、最終画面、2枚以上のスクリーンショット、操作ログが揃うこと。未知画面、title再出現、timeoutを成功扱いしない。

## C9b: 起動時のお知らせを閉じる

C9bはお知らせと閉じるボタンが同時に見える実画面を1件だけ受け取り、`python scripts/validate_c9b_input.py artifacts/c9b_notice_close.jsonl --require-files` で検査する。成功は `startup_notice` から既知のガチャ開始画面への遷移、閉じる入力ちょうど1回、停止理由なしを必須とする。安全停止は入力0〜1回と停止理由を必須とし、画面変化なし・再表示時の追加入力を許可しない。

Cloud再開条件：タイムゾーン付き取得時刻、お知らせ種別、閉じるボタン矩形、前後screen_id、入力回数、操作前後PNG、操作ログが揃うこと。実画像なしにお知らせ種別・座標・遷移を推測しない。

## Local側の確認手順

1. ADB接続と解像度を確認する。
2. 期待 `screen_id` を確認してから、許可された操作を1回ずつ行う。
3. 各操作の前後で画面、OCR、入力結果を記録する。
4. 安全停止条件に該当したら操作を中断し、`safety_stop` として保存する。
5. JSONL、PNG、要約をCloudへ渡す。

## Cloud側の受領後処理

1. JSONLの必須項目と画像パスを検査する。
2. 画面系列と操作ログを突合する。
3. 成功・安全停止・入力不足を分離して集計する。
4. 欠落や不整合があればタスクを完了にせず、追加Local入力を返す。
