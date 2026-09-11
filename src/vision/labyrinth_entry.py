"""ラビリンス入口画面の新規／途中再開判定。"""

from __future__ import annotations

from typing import Iterable, Any


def classify_labyrinth_entry(
    ocr_text: Iterable[str],
    *,
    departure_button_visible: bool,
) -> dict[str, Any]:
    """「出発」上の「挑戦中」表示から入口モードを判定する。

    判定不能な場合は ``screen_status=unknown`` を返し、オーケストレータの
    安全停止へ渡す。OCRの誤認識で新規出発へ進まないよう、挑戦中は完全一致
    ではなく正規化後の短い表示語だけを許容する。
    """
    tokens = {str(value).strip() for value in ocr_text if str(value).strip()}
    if not departure_button_visible:
        return {"screen_id": "unknown", "screen_status": "unknown", "reason": "departure_button_missing"}
    if "挑戦中" in tokens:
        return {
            "screen_id": "labyrinth_entry_active",
            "entry_mode": "resume",
            "challenge_active": True,
            "entry_action": "resume_existing_challenge",
            # 挑戦中は遷移先が一定でないため、固定スクリプトを呼ばず
            # ユーザー補助／画面再判定へ渡す。
            "resume_task": "task_user_assist",
        }
    if "出発" in tokens:
        return {
            "screen_id": "labyrinth_entry_new",
            "entry_mode": "new",
            "challenge_active": False,
            "entry_action": "start_new_challenge",
            "resume_task": "check_passports",
        }
    return {"screen_id": "unknown", "screen_status": "unknown", "reason": "entry_markers_missing"}
