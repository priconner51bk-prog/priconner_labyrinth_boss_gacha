"""実機ボスガチャ実行コマンド（task_）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

SUBPROJECT = Path(__file__).resolve().parents[1]
ROOT = SUBPROJECT
sys.path.insert(0, str(SUBPROJECT / "src"))
sys.path.insert(0, str(SUBPROJECT))

from boss_gacha import (BossGachaController, BossGachaPhaseCoordinator,
                        BossGachaPolicy, LiveBossGachaWorkflow,
                        GuardedLiveActions)
from decision.operation_log import OperationLogger
from decision.timing import AdaptiveWaitPolicy
from decision.timing_trace import TimingTrace
from vision.capture import AdbScreenCapture
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.roi import NormalizedROI
from vision.template_screen_probe import load_template_probe_config
from scripts.labyrinth_route import (ADB_BUTTON_COORDINATES,
                                     run_adb_coordinate_sequence,
                                     run_adb_swipe,
                                     screen_coordinate)
from scripts.live_cli_utils import screen_error_message


def _boss_names() -> dict[str, set[str]]:
    """Return canonical boss names and OCR aliases grouped by canonical name."""
    names: dict[str, set[str]] = {}
    for filename in ("boss_area3.json", "boss_area5.json"):
        data = json.loads((ROOT / "configs" / filename).read_text(encoding="utf-8"))
        for item in data.get("bosses", []):
            canonical = str(item["name"])
            names[canonical] = {canonical, *(str(alias) for alias in item.get("ocr_aliases", []))}
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="画面ガード付きボスガチャ（最大100回）")
    parser.add_argument("--execute", action="store_true", help="ADB入力を有効化（省略時はpreflightのみ）")
    parser.add_argument("--passports", type=int, default=100, help="今回許可する試行回数（1試行につき1枚消費、既定値:100）")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--guild", help="出発時に選択するギルド（省略時は設定のpreferred_guilds先頭）")
    parser.add_argument("--difficulty", type=int, choices=range(1, 11), default=10,
                        help="難易度（既定値: 10。現在の画面操作は難易度10を想定）")
    parser.add_argument("--area3-boss", action="append", default=[],
                        help="エリア3で許容するボス名。複数指定可")
    parser.add_argument("--area5-boss", action="append", default=[],
                        help="エリア5で許容するボス名。複数指定可")
    parser.add_argument("--det-model", type=Path)
    parser.add_argument("--rec-model", type=Path)
    parser.add_argument("--default-models", action="store_true", help="PaddleOCR標準日本語モデルを使用")
    args = parser.parse_args()
    if args.passports < 0:
        parser.error("--passports must be non-negative")

    live_dir = ROOT / "data" / "observations" / "live"
    trace = TimingTrace(live_dir / "boss_gacha_timing.jsonl", task="task_boss_gacha")
    capture = AdbScreenCapture(serial=args.serial, timing_trace=trace)
    try:
        probe = load_template_probe_config(ROOT / "configs" / "live_screen_templates.json", capture)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "safety_stop",
            "reason": "screen_templates_unavailable",
            "error": str(exc),
            "execute": args.execute,
        }, ensure_ascii=False))
        return 2
    def observe_screen_stable() -> str | None:
        # BlueStacks may return one empty frame during a transition. Keep the
        # retry window short, but long enough to avoid ending the whole gacha
        # before the first stable screen observation.
        for attempt in range(8):
            try:
                observed = probe.observe_screen()
            except Exception:
                observed = None
            if observed:
                return observed
            if attempt < 7:
                time.sleep(0.10)
        return None
    try:
        screen_id = observe_screen_stable()
    except Exception as exc:
        # A missing ADB device is a normal preflight failure, not a traceback
        # and never a reason to attempt input.
        print(json.dumps({"status": "safety_stop", "reason": f"screen_observation_failed:{type(exc).__name__}", "error": screen_error_message(exc, args.serial), "execute": args.execute}, ensure_ascii=False))
        return 2
    print(json.dumps({"screen_id": screen_id, "execute": args.execute}, ensure_ascii=False))
    if screen_id is None:
        print(json.dumps({
            "status": "safety_stop",
            "reason": "screen_not_recognized",
            "execute": args.execute,
        }, ensure_ascii=False))
        return 2
    if not args.execute:
        return 0
    if args.passports <= 0:
        print(json.dumps({"status": "safety_stop", "reason": "passport_count_not_positive"}, ensure_ascii=False))
        return 2
    if not args.area3_boss or not args.area5_boss:
        print(json.dumps({"status": "safety_stop", "reason": "allowed_bosses_not_configured"}, ensure_ascii=False))
        return 2

    # ギルドは設定を唯一の既定値とし、CLI指定で上書きする。座標・表示テンプレートが
    # 未登録のギルドは tap() が安全停止するため、未確認座標を推測して入力しない。
    guild_config = ROOT / "configs" / "labyrinth_guild_starting_members.json"
    try:
        guild_data = json.loads(guild_config.read_text(encoding="utf-8"))
        preferred = guild_data.get("selection_policy", {}).get("preferred_guilds", [])
        default_guild = str(preferred[0]).strip() if preferred else "フォレスティエ"
    except Exception:
        default_guild = "フォレスティエ"
    guild_label = (args.guild or default_guild).strip()
    if not guild_label:
        print(json.dumps({"status": "safety_stop", "reason": "guild_not_configured"}, ensure_ascii=False))
        return 2

    # Resolve resume/new-departure state before loading OCR models.  Resume
    # assistance must be immediate and must not wait on model initialization.
    if screen_id == "labyrinth_top":
        try:
            if probe.target_visible("挑戦中"):
                    print(json.dumps({
                        "status": "safety_stop",
                        "reason": "challenge_active_screen_is_ambiguous",
                        "screen_id": screen_id,
                    }, ensure_ascii=False))
                    return 2
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"challenge_state_observation_failed:{type(exc).__name__}"}, ensure_ascii=False))
            return 2

    if args.default_models:
        ocr = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn")
    elif args.det_model and args.rec_model:
        ocr = PaddleOCRAdapter(str(args.det_model), str(args.rec_model), device="cpu", language="jpn")
    else:
        print(json.dumps({"status": "safety_stop", "reason": "ocr_model_not_configured"}, ensure_ascii=False))
        return 2

    operation_log = OperationLogger(live_dir / "boss_gacha_operations.jsonl", live_dir / "boss_gacha_operations.md")
    policy = BossGachaPolicy.from_json(ROOT / "configs" / "labyrinth_target_policy.json")
    policy = BossGachaPolicy(
        target_bosses={"3": args.area3_boss[0], "5": args.area5_boss[0]},
        allowed_bosses={"3": tuple(args.area3_boss), "5": tuple(args.area5_boss)},
        max_attempts=policy.max_attempts,
    )
    names = _boss_names()
    roi_data = json.loads((ROOT / "configs" / "labyrinth_ocr_regions.json").read_text(encoding="utf-8"))
    roi = NormalizedROI.model_validate(roi_data["regions"]["boss_detail_name"]["normalized"])
    frame_index = {"value": 0}

    def wait_screen(expected: str) -> bool:
        # 画面遷移の上限は2.0秒。6秒固定だった旧実装では空振り時に
        # 1操作あたり数秒を余分に消費していた。実測95%が1.2秒以内
        # なので、空振りは早く安全停止する。
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            observed = observe_screen_stable()
            if observed == expected or (expected == "bonus" and observed == "item_reward"):
                return True
            time.sleep(0.08)
        return False

    def tap(screen: str, label: str) -> bool:
        def dynamic_guild_point() -> tuple[int, int] | None:
            """Find a configured guild label from OCR when no template exists.

            Guild cards are dynamic artwork, so a stale screenshot template is
            not reliable.  OCR is restricted to this one selection action and
            requires a confident bounding box; otherwise the action is refused.
            """
            if screen != "guild_select":
                return None
            wanted = re.sub(r"\s+", "", label)
            path = live_dir / "task_boss_gacha_guild_select_ocr.png"
            # ギルドカードは横スクロール式。現在表示分を確認し、見つから
            # なければ画面ガード付きで最大4ページだけ送る。
            # 前回の試行位置を問わず、左右両方向を走査する。ページャは
            # 端で止まるため、反対向きも含めて最大9回で全ギルドを覆う。
            directions = [((250, 400), (1100, 400))] * 8 + [((1100, 400), (250, 400))] * 8
            for page in range(len(directions) + 1):
                try:
                    capture.capture(path)
                    lines = ocr.recognize(str(path))
                except Exception:
                    return None
                for line in lines:
                    text = re.sub(r"\s+", "", line.text)
                    if line.confidence < 0.55 or not line.bbox or wanted not in text:
                        continue
                    left, top, right, bottom = line.bbox
                    if right <= left or bottom <= top:
                        continue
                    # OCRはギルド名の文字位置を返す。入力先は同じカードの
                    # 下部にある「選択する」ボタンなので、文字の下へ固定量
                    # だけ移し、カード外への誤入力を範囲で拒否する。
                    button_y = max(520, min(600, bottom + 75))
                    return ((left + right) // 2, button_y)
                if page >= len(directions):
                    break
                try:
                    swipe_start, swipe_end = directions[page]
                    run_adb_swipe(swipe_start, swipe_end, serial=args.serial,
                                  healthcheck=True,
                                  screen_guard=lambda: observe_screen_stable() == "guild_select",
                                  task_name="guild_select_page_scan", timing_trace=trace)
                except Exception:
                    return None
            return None

        # 画面IDの切替直後は背景テンプレートだけ先に一致することがある。
        # 対象ROIが実際に現れるまで短時間だけ再確認し、空振りを入力しない。
        deadline = time.monotonic() + 8.0
        dynamic_point = None
        # 「閉じる」は画面ごとに別のROIテンプレートを持つ。論理上の
        # ラベルは共通のまま、表示確認だけ画面固有の別名へ切り替える。
        probe_label = label
        if label == "閉じる" and screen == "bonus":
            probe_label = "出発ボーナス閉じる"
        elif label == "閉じる" and screen == "item_reward":
            probe_label = "アイテム報酬閉じる"
        def dynamic_close_point() -> tuple[int, int] | None:
            if label != "閉じる" or screen not in {"boss_detail", "bonus", "item_reward"}:
                return None
            path = live_dir / "task_boss_gacha_close_ocr.png"
            try:
                capture.capture(path)
                lines = ocr.recognize(str(path))
            except Exception:
                return None
            for line in lines:
                if line.confidence >= 0.70 and line.bbox and "閉じる" in re.sub(r"\s+", "", line.text):
                    left, top, right, bottom = line.bbox
                    if 400 <= (left + right) // 2 <= 850 and 500 <= (top + bottom) // 2 <= 700:
                        return ((left + right) // 2, (top + bottom) // 2)
            return None
        def dynamic_withdraw_ok_point() -> tuple[int, int] | None:
            if label != "撤退確認OK" or screen != "withdraw_confirm":
                return None
            path = live_dir / "task_boss_gacha_withdraw_confirm_ocr.png"
            try:
                capture.capture(path)
                lines = ocr.recognize(str(path))
            except Exception:
                return None
            text = "".join(re.sub(r"\s+", "", line.text) for line in lines if line.confidence >= 0.60)
            if "終了確認" not in text:
                return None
            for line in lines:
                if line.confidence < 0.60 or not line.bbox:
                    continue
                if re.sub(r"\s+", "", line.text).upper() not in {"OK", "ＯＫ"}:
                    continue
                left, top, right, bottom = line.bbox
                point = ((left + right) // 2, (top + bottom) // 2)
                if 620 <= point[0] <= 930 and 430 <= point[1] <= 560:
                    return point
            return None
        while time.monotonic() < deadline:
            observed = observe_screen_stable()
            screen_matches = observed == screen or (screen == "bonus" and observed == "item_reward")
            # ボス詳細の閉じるボタンは固定ROIで検証済み。まず軽量な
            # テンプレート確認を行い、毎回のOCR初期往復を避ける。
            if screen in {"boss_detail", "withdraw_confirm"} and screen_matches and probe.target_visible(probe_label):
                break
            if dynamic_point is None:
                dynamic_point = dynamic_close_point()
            if dynamic_point is None:
                dynamic_point = dynamic_withdraw_ok_point()
            # ボス詳細・確認ダイアログは最小ROIのOCR位置を一次根拠にする。
            # 全テンプレート照合を先に行うと、閉じる操作が不要に遅れる。
            if screen_matches and dynamic_point is not None:
                break
            if screen_matches and probe.target_visible(probe_label):
                break
            if dynamic_point is not None:
                break
            if screen == "guild_select" and label not in probe.targets:
                dynamic_point = dynamic_guild_point()
                if dynamic_point is not None:
                    break
            time.sleep(0.08)
        else:
            return False
        point = dynamic_point or (screen_coordinate(screen, label) if screen in {"quest_menu", "labyrinth_top"} else ADB_BUTTON_COORDINATES.get(label))
        if point is None:
            return False
        try:
            started = time.perf_counter()
            run_adb_coordinate_sequence([point], serial=args.serial, healthcheck=True,
                                        timing_policy=AdaptiveWaitPolicy(minimum_seconds=0.05, poll_seconds=0.03, timeout_seconds=1.5), screen_probe=probe.observe_screen,
                                        debug_capture_dir=live_dir, debug_capture_prefix=f"task_boss_gacha_{label}",
                                        timing_trace=trace, previous_screen_token=screen)
            operation_log.record(task="task_boss_gacha", purpose=label, screen_before=screen,
                                 action="ADB tap", coordinate=point, adb_serial=args.serial, outcome="sent",
                                 duration_ms=(time.perf_counter() - started) * 1000)
            return True
        except Exception:
            return False

    def read_name(side: str) -> str | None:
        started = time.perf_counter()
        frame_index["value"] += 1
        path = live_dir / f"task_boss_gacha_{side}_{frame_index['value']}.png"
        capture.capture(path)
        # 実機のボス名ROIは高さが約72pxしかないため、そのままでは
        # PP-OCRv4の検出器が文字列を落とすことがある。ROIだけを2倍に
        # 拡大してOCRし、画面全体のノイズは読み込ませない。
        import cv2
        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError("ボス名画像を読み込めません")
        cropped = roi.crop_array(image)
        enlarged = cv2.resize(cropped, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        ocr_path = live_dir / f"task_boss_gacha_{side}_{frame_index['value']}_name_ocr.png"
        if not cv2.imwrite(str(ocr_path), enlarged):
            raise RuntimeError("ボス名OCR画像を保存できません")
        lines = ocr.recognize(str(ocr_path))
        trace.record("ocr_boss_name", (time.perf_counter() - started) * 1000, side=side)
        text = re.sub(r"\s+", "", "".join(line.text for line in lines))
        for canonical, variants in names.items():
            normalized_variants = {re.sub(r"\s+", "", variant) for variant in variants}
            if any(variant in text or text in variant for variant in normalized_variants):
                return canonical
        return None

    def verify_guild(expected: str) -> bool:
        """出発ボーナスのギルド表記を確認してから次画面へ進む。"""
        path = live_dir / "task_boss_gacha_guild_verify.png"
        try:
            capture.capture(path)
            lines = ocr.recognize(str(path))
        except Exception:
            return False
        expected_text = re.sub(r"\s+", "", expected)
        observed = re.sub(r"\s+", "", "".join(line.text for line in lines if line.confidence >= 0.55))
        return expected_text in observed

    # 開始・再開とも現在画面を自動判定する。画面が曖昧な場合は入力せず停止する。
    start_screen = screen_id
    if start_screen == "item_reward":
        start_screen = "bonus"
    if start_screen not in {"quest_menu", "labyrinth_top", "guild_select", "guild_confirm", "bonus", "initial_char", "boss_map", "boss_detail", "withdraw_confirm"}:
        print(json.dumps({"status": "safety_stop", "reason": f"unsupported_start_screen:{start_screen}"}, ensure_ascii=False))
        return 2
    actions = GuardedLiveActions(observe_screen=probe.observe_screen, target_visible=probe.target_visible,
                                 tap=lambda label: tap(observe_screen_stable() or "", label))
    coordinator = BossGachaPhaseCoordinator(actions)
    workflow = LiveBossGachaWorkflow(tap=tap, wait_screen=wait_screen, read_boss_name=read_name,
                                     guild_label=guild_label, verify_guild=verify_guild)
    first = {"screen": start_screen}
    remaining = {"count": args.passports}
    def begin_once() -> None:
        begin_screen = first.pop("screen", "labyrinth_top")
        workflow.begin_attempt(begin_screen)
        # 初回が初期キャラ/マップ/ボーナスからの復帰なら既に消費済み。
        # 次回以降の通常出発では各回1枚だけ減算する。
        if begin_screen in {"quest_menu", "labyrinth_top", "guild_select", "guild_confirm"}:
            remaining["count"] = max(0, remaining["count"] - 1)
        elif begin_screen in {"initial_char", "boss_map", "bonus", "withdraw_confirm"}:
            return
        else:
            remaining["count"] = max(0, remaining["count"] - 1)
    def _gacha_progress(payload: dict) -> None:
        print(json.dumps({"gacha_progress": True, **payload}, ensure_ascii=False), flush=True)

    runner = workflow.runner(BossGachaController(policy),
                         passport_count=lambda: remaining["count"],
                         safety_check=lambda: observe_screen_stable() in {"labyrinth_top", "guild_select", "guild_confirm", "bonus", "item_reward", "initial_char", "boss_map", "boss_detail", "withdraw_confirm"},
                         timing_trace=trace,
                         phase_guard=coordinator.guard_phase if start_screen == "labyrinth_top" else None,
                         on_progress=_gacha_progress)
    runner.begin_attempt = begin_once
    # begin_attempt完了後は必ず初期キャラ画面。既にマップ上で開始した場合だけ
    # 初回のマップ操作を省略する。
    read_start = {"screen": "boss_detail" if start_screen == "boss_detail" else ("boss_map" if start_screen == "boss_map" else "initial_char")}
    target_left = str(policy.target_bosses.get("3", ""))
    runner.read_boss_names = lambda: workflow.read_boss_names(
        read_start.pop("screen", "initial_char"), target_left=target_left
    )
    result = runner.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "matched" else 2


if __name__ == "__main__":
    raise SystemExit(main())
