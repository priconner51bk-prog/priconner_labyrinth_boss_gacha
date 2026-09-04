# 実機テンプレートの準備

実機フローの画面判定には、`configs/live_screen_templates.json` が参照する画面テンプレートが必要です。テンプレートはゲーム画面を含むため、公開リポジトリへ追加せず、ローカルの `data/observations/live/` にだけ配置します。

## 準備手順

1. BlueStacks を検証済みの表示設定（Android クライアント `1280x720`）で起動します。
2. ADB 接続を確認します。
3. 各画面を手動で表示し、設定ファイルに記載された相対パスと同じ名前でキャプチャを保存します。
4. `configs/live_screen_templates.json` の `screens` と `targets` の全参照先が存在することを確認します。
5. `python main.py live --serial 127.0.0.1:5555 --default-models` で preflight を実行します。

## 確認コマンド

```powershell
$templatePaths = Select-String -Path configs/live_screen_templates.json -Pattern '"image"\s*:\s*"([^"]+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value }
$templatePaths | ForEach-Object { "$_ -> $(Test-Path $_)" }
```

不足がある場合は `screen_templates_unavailable` で停止します。キャプチャを Git に追加したり、他人のアカウント情報・端末情報を含む画像を共有したりしないでください。
