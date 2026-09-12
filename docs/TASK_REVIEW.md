# タスク分類・入力縮約の基準

2026-09-06。ユーザー提供のタスク見直しコンテキストに基づく。本書と [TASKS.md](TASKS.md) を合わせて状態・目的・評価・入力・分割・完了証拠を管理する。

## Cloud優先の再分類方針（2026-09-06）

コード、設定、テスト、要約分析はCLOUDで実行し、実機画面、ADB接続、ローカルOCRモデルが完了条件に含まれるタスクはLOCALまたはHYBRIDとして残す。Cloudで代替できる部分だけを完了扱いにし、実機証拠が不足する部分は未確認として明示する。

## 評価方法

Token Costはクラウド入力量と反復回数、Data Countは件数、Data Sizeは容量、Repeatabilityは定型反復性、Compressibilityはローカル縮約性、Reasoning Requirementは判断の難度。以下のL/M/HはLOW/MEDIUM/HIGHの見積りであり、トークン実測ではない。

Token LOWは少数ファイルの明確な修正、MEDIUMは複数ファイルの設計・検証、HIGHは広域探索と多数の反復。件数は数十件以内/数百件/数千件以上、容量は数MB以下/数十〜数百MB/GB級を目安にする。

まず件数と容量、次に縮約可能性・反復性・トークン量、最後に推論の必要性を評価する。大量・大容量でもCloudで扱えるよう、入力を要約・分割して渡す。HIGH Token Costを理由に別実行先へ移さず、Cloud内でスクリプト・パーサー・LLMを組み合わせる。

## 優先順の評価

TaskとPurposeを一列に記載。Reasonは実行分類列に併記。入力・分割は同じIDで次表に対応する。

| ID | Task / Purpose | Token | Count | Size | Repeat | Compress | Reasoning | Recommended Execution / Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | 早期撤退の回数計上：上限遵守 | M | L | L | L | M | M | CLOUD：少量の状態制御 |
| C2 | 複数ボス選択：許容候補の反映 | M | L | L | L | M | M | CLOUD：引数と判定の接続 |
| C3 | 詳細からの復帰：左右取り違え防止 | M | L | L | L | M | M | CLOUD：遷移順の設計 |
| C4 | 結果表示：成功・失敗・停止を区別 | M | L | L | L | M | M | CLOUD：終了通知と出力の順序 |
| C5 | 指定回数：試行上限とパスポート確認の分離 | M | L | L | L | M | M | CLOUD：1〜1000回の境界値と独立引数の接続検証 |
| C6 | GUI保存：選択復元と破損対応 | M | L | L | L | M | M | CLOUD：永続化・異常時設計 |
| C7 | OCR照合：空文字・曖昧一致拒否 | M | L | L | L | M | M | CLOUD：文字列の判定ロジック |
| C8 | 分類と完了監査：漏れの管理 | M | L | L | L | H | H | CLOUD：根拠付きタスク分割 |
| L1 | 日本語OCR・全ギルドの実測 | H | M | M | H | H | L | HYBRID：CloudでROI・照合を確認し、Localで実画像・実機受入を確認 |
| L2 | 回帰テスト実行・集計 | M | L | L | H | H | L | CLOUD：pytest実行・失敗解釈・監査を一括実施 |
| H1 | ギルド横スクロール失敗の解消 | H | M | M | H | H | H | HYBRID：Cloudでコード・シミュレーション、Localで14ギルド受入 |
| H2 | 新規GitHub公開 | M | L | L | L | H | M | CLOUD：公開候補・履歴・公開手順をレビュー。認証操作の不足は未確認 |

## 最小入力と分割

| ID | Cloud-side Preprocessing | Cloud Input | Split Required / Suggested Tasks |
| --- | --- | --- | --- |
| C1 | ループと回数テスト抽出 | runnerと期待回数 | NO |
| C2 | 引数参照の抽出 | CLI→workflow→policyの関連関数 | NO |
| C3 | 復帰分岐抽出 | 初期画面・遷移順・期待エリア | NO |
| C4 | 最終出力1件抽出 | JSON形式とGUIキュー処理 | NO |
| C5 | 境界値テスト | attempts=1/2/99/100/1000、passports=0/1、CLI・GUIの結果 | NO |
| C6 | 一時設定で保存・復元試験 | 保存失敗と破損JSONの結果 | NO |
| C7 | 画像からローカルOCR | 数件の文字列・候補名・正解 | NO |
| C8 | rg・git diffで対象絞り込み | タスク一覧・関連差分・検証結果 | NO |
| L1 | ROI切出・OCR・誤読率と時間集計 | Local単位L1b-1〜4の画像、ラベル、OCR結果、ROI設定、誤読例 | YES：Localで取得し、Cloudで画像・結果を評価 |
| L2 | pytest -q | 失敗名・該当traceback | NO |
| H1 | ADB結果と前後画面差分の記録 | Local単位H1b-1〜5の座標・画面ID・変化量・理由 | YES：Localで取得し、Cloudで前後画面と安全停止を評価 |
| H2 | git ls-files・履歴・ignore・remote確認 | 公開候補と除外漏れ | YES：Cloudで履歴・公開候補・手順をレビュー。認証付き操作は未実施 |

画像総数と容量はCloud側で測定して見積りを更新する。大量ログ・画像・モデル・重複データ・リポジトリ全量は、Cloud内で抽出・集計・分割してから判断に使う。個別の入力上限を超える場合もCloud側で分割する。

## 完了監査

実際の呼出経路とテストを対応付ける。単体テスト成功を実機成功と扱わない。検索結果がないことを全件完了の根拠にしない。Cloudで代替できた検証と、実機・認証情報不足で未確認の検証を分けて記録する。全タスクをCLOUD分類にしても、証拠不足を完了扱いにはしない。

## Local実機タスクのCloud投入契約

- `task_id` は `TASKS.md` の分割IDを使用する。
- 1回の実機作業は30〜60分を目安にし、複数単位の結果を混ぜない。
- 必須項目は `run_id`、`serial`、`screen_before`、`screen_after`、`action`、`result`、`stop_reason`、`screenshots`、`timestamp`。
- OCRを含む場合は `text`、`confidence`、`bbox`、`expected_text`、`matched_name`、`elapsed_ms` を追加する。
- Cloud側はJSONL、画像マニフェスト、PNG、`summary.md` を入力として、成功・安全停止・未判定を分けて分析する。
- 実機結果がない状態、または記録項目が欠落した状態では、該当Localタスクを完了に変更しない。
