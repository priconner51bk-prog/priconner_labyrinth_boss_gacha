"""原因・対策・再実行条件を安全停止結果に付与する。"""

from __future__ import annotations

_KNOWN = {
    "guild_mismatch": {
        "cause": "選択したギルドと画面上のギルドが一致しない。",
        "countermeasure": "ギルド画面を再取得し、表示名を確認してから選択する。",
        "retry_condition": "ギルド名が一意に一致すること。",
    },
    "notice_did_not_close": {
        "cause": "確認済みの通知が閉じなかった。",
        "countermeasure": "画面を再取得し、対象ボタンを1回だけ再確認する。",
        "retry_condition": "通知が表示され、one tapで消えること。",
    },
    "destination_panel_not_confirmed": {
        "cause": "scan時と移動時の画面が同一パネルだと証明できない。古いscan、アニメーション差分、またはパネル移動不一致の可能性がある。",
        "countermeasure": "現在画面をfresh scanし、対象ノードをOCRで再確認してから再実行する。古いfingerprintだけでタップしない。",
        "retry_condition": "boss_map確認、fresh scan、対象ノードのpanel座標・種別一致、移動後画面証跡が揃うこと。",
    },
    "map_graph_not_derivable": {
        "cause": "検出ノードだけでは安全な経路を構成できない。",
        "countermeasure": "現在画面から再スキャンし、開始ノード・接続・終端を再取得する。推測で移動しない。",
        "retry_condition": "開始ノードから終端までの経路がpreflightで導出できること。",
    },
    "map_nodes_not_recognized": {
        "cause": "マップ上の操作対象ノードをOCRまたは終端検出で確認できない。",
        "countermeasure": "画面を再取得し、boss_map確認後にOCRを再実行する。未確認の座標は操作しない。",
        "retry_condition": "対象ノードの種別・座標・信頼度が確認できること。",
    },
}


def analyze_safety_stop(reason: str) -> dict[str, str]:
    """Return actionable analysis for a safety-stop reason."""
    reason_class = "guild_mismatch" if reason.startswith("guild_mismatch:") else reason
    known = _KNOWN.get(reason_class)
    if known is not None:
        return {"reason_class": reason_class, **known}
    return {
        "reason_class": "unclassified",
        "cause": "安全停止理由の詳細分析が未登録。",
        "countermeasure": "Preserve screen, input, exception, and previous state before classifying and retrying.",
        "retry_condition": "原因と再実行条件が記録され、同じ条件で安全確認できること。",
    }


def enrich_safety_stop(event: dict) -> dict:
    """Attach analysis only to safety-stop events; preserve other events."""
    if event.get("status") != "safety_stop":
        return event
    enriched = dict(event)
    enriched["analysis"] = analyze_safety_stop(str(event.get("reason", "unknown")))
    return enriched
