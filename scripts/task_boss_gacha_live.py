"""実機ボスガチャ実行コマンド（task_）。"""

from __future__ import annotations

import argparse
import hashlib
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
from boss_gacha.guild_selection import guild_button_point, scan_directions
from decision.operation_log import OperationLogger
from decision.timing import AdaptiveWaitPolicy
from decision.timing_trace import TimingTrace
from vision.capture import AdbScreenCapture
from vision.template_screen_probe import load_template_probe_config
from scripts.labyrinth_route import (ADB_BUTTON_COORDINATES,
                                     run_adb_coordinate_sequence,
                                     run_adb_swipe,
                                     screen_coordinate)
from scripts.live_cli_utils import screen_error_message


def main() -> int:
    parser = argparse.ArgumentParser(description="画面ガード付きボスガチャ（最大1000回）")
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
    parser.add_argument("--default-models", action="store_true", help="互換引数（現在は無視。テンプレート判定を使用）")
    args = parser.parse_args()
    if args.passports < 0:
        parser.error("--passports must be non-negative")

    live_dir = ROOT / "data" / "observations" / "live"
    trace = TimingTrace(live_dir / "boss_gacha_timing.jsonl", task="task_boss_gacha")
    capture = AdbScreenCapture(serial=args.serial, timing_trace=trace)
    screenshot_index = {"value": 0}
    last_observed_screen = {"value": None}
    screenshot_hashes: set[str] = set()
    for existing in live_dir.glob("task_boss_gacha_screen_*.png"):
        try:
            screenshot_hashes.add(hashlib.sha256(existing.read_bytes()).hexdigest())
        except OSError:
            pass

    def save_gacha_screenshot(label: str) -> Path | None:
        """ガチャ実行中の画面を証跡として保存する。"""
        screenshot_index["value"] += 1
        safe_label = re.sub(r"[^0-9A-Za-z一-龯ぁ-んァ-ヶ_-]+", "_", label).strip("_") or "screen"
        path = live_dir / f"task_boss_gacha_screen_{screenshot_index['value']:04d}_{safe_label}.png"
        pending = live_dir / f".task_boss_gacha_pending_{screenshot_index['value']:04d}.png"
        try:
            capture.capture(pending)
            digest = hashlib.sha256(pending.read_bytes()).hexdigest()
            if digest in screenshot_hashes:
                pending.unlink(missing_ok=True)
                return None
            screenshot_hashes.add(digest)
            pending.replace(path)
            return path
        except Exception:
            pending.unlink(missing_ok=True)
            return None
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
        # BlueStacksの再起動直後はADB接続済みでも、描画バッファと
        # スクリーンショット取得が安定するまで数秒かかることがある。
        # 初回判定を0.8秒で打ち切ると、画面参照前に停止してしまうため、
        # 短い間隔で最大7.5秒だけ再試行する。
        for attempt in range(30):
            try:
                observed = probe.observe_screen()
            except Exception:
                observed = None
            if observed:
                if last_observed_screen["value"] != observed:
                    save_gacha_screenshot(f"observed_{observed}")
                    last_observed_screen["value"] = observed
                return observed
            if attempt < 29:
                time.sleep(0.25)
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

    # Resolve resume/new-departure state before loading templates. Resume
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

    operation_log = OperationLogger(live_dir / "boss_gacha_operations.jsonl", live_dir / "boss_gacha_operations.md")
    policy = BossGachaPolicy.from_json(ROOT / "configs" / "labyrinth_target_policy.json")
    policy = BossGachaPolicy(
        target_bosses={"3": args.area3_boss[0], "5": args.area5_boss[0]},
        allowed_bosses={"3": tuple(args.area3_boss), "5": tuple(args.area5_boss)},
        max_attempts=policy.max_attempts,
    )
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
            """Find a configured guild card using templates only."""
            if screen != "guild_select":
                return None
            # 収集済みカードをテンプレート照合する。テンプレートは
            # スクロール後にも毎ページ再評価する必要があるため、走査の
            # 外側ではなく、この関数の各呼び出しで現在画面を取得する。
            # source画像は同一レイアウトの4カードを含むため、対象ごとに
            # カード矩形を切り出して比較する。
            def template_point(frame):
                import cv2
                template_specs = {
                    "美食殿": ("guild_mishoku_card.png", None),
                    "トゥインクルウィッシュ": ("guild_twinkle_card.png", "guild_confirm_mishoku.png"),
                    "サレンディア救護院": ("guild_salendia_card.png", "guild_confirm_mishoku.png"),
                }
                filename, source_name = template_specs.get(label, (None, None))
                template_path = ROOT / "data" / "template_migration" / "templates" / (filename or "")
                template = cv2.imread(str(template_path), cv2.IMREAD_COLOR) if filename and template_path.exists() else None
                if template is None and source_name:
                    source = cv2.imread(str(ROOT / "data" / "template_migration" / "source" / source_name), cv2.IMREAD_COLOR)
                    if source is not None:
                        crops = {"トゥインクルウィッシュ": (390, 175, 710, 635), "サレンディア救護院": (750, 175, 1070, 635)}
                        x1, y1, x2, y2 = crops[label]
                        template = source[y1:y2, x1:x2]
                if template is None or frame is None or frame.shape[0] < template.shape[0] or frame.shape[1] < template.shape[1]:
                    return None
                result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, location = cv2.minMaxLoc(result)
                if score >= 0.82:
                    x, y = location
                    return (x + template.shape[1] // 2, y + template.shape[0] - 70)
                return None

            try:
                import cv2
                frame_path = live_dir / "task_boss_gacha_guild_select_template.png"
                capture.capture(frame_path)
                frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
                point = template_point(frame)
                if point is not None:
                    return point
            except Exception:
                pass
            path = live_dir / "task_boss_gacha_guild_select_template.png"
            # ギルドカードは横スクロール式。現在表示分を確認し、見つから
            # なければ画面ガード付きで最大4ページだけ送る。
            # 前回の試行位置を問わず、左右両方向を走査する。ページャは
            # 端で止まるため、反対向きも含めて最大9回で全ギルドを覆う。
            guild_order = list(guild_data.get("guilds", {}).keys())
            settings_path = ROOT / ".local_gui_settings.json"
            try:
                current_guild = json.loads(settings_path.read_text(encoding="utf-8")).get("guild")
            except (OSError, ValueError, TypeError):
                current_guild = None
            current_index = guild_order.index(current_guild) if current_guild in guild_order else 0
            target_index = guild_order.index(label) if label in guild_order else None
            # 保存設定と実機のカード位置がずれていても、カード列の順序は
            # 固定なので、まず下部スクロールバーを目的位置へ合わせる。
            # 既に対象カードが見えている場合は上のテンプレート判定で戻るため、
            # 不要なスクロールは発生しない。
            if target_index is not None and guild_order:
                try:
                    # 画面には約3枚ずつ表示されるため、スクロールバーの
                    # 位置はカード番号ではなく表示ページ番号に対応させる。
                    page_index = target_index // 3
                    max_page_index = max(1, (len(guild_order) - 1) // 3)
                    target_scroll_x = 25 + round(1230 * page_index / max_page_index)
                    run_adb_swipe(
                        (1100, 658), (target_scroll_x, 658), serial=args.serial,
                        healthcheck=True,
                        screen_guard=lambda: observe_screen_stable() == "guild_select",
                        task_name="guild_select_scrollbar_position",
                        timing_trace=trace,
                    )
                    time.sleep(0.45)
                    import cv2
                    capture.capture(path)
                    point = template_point(cv2.imread(str(path), cv2.IMREAD_COLOR))
                    if point is not None:
                        return point
                except Exception:
                    pass
            directions = scan_directions(
                len(guild_order), current_index=current_index, target_index=target_index
            )
            # 保存位置と実機位置がずれている場合に限り、全体走査へフォールバックする。
            # 通常は上の最短経路だけで済み、無限走査は行わない。
            fallback = scan_directions(len(guild_order))
            directions.extend(fallback)
            for page in range(len(directions) + 1):
                try:
                    capture.capture(path)
                    import cv2
                    point = template_point(cv2.imread(str(path), cv2.IMREAD_COLOR))
                    if point is not None:
                        return point
                except Exception:
                    return None
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
                # スワイプ後の新しいページもテンプレートだけで判定する。
                try:
                    import cv2
                    # 画面IDが戻ってもカード描画だけ遅れる場合があるため、
                    # 直後の一枚を判定せず短時間だけ描画を待つ。
                    time.sleep(0.45)
                    capture.capture(path)
                    point = template_point(cv2.imread(str(path), cv2.IMREAD_COLOR))
                    if point is not None:
                        return point
                except Exception:
                    pass
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
            return None
        def dynamic_withdraw_ok_point() -> tuple[int, int] | None:
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
            # ボス詳細・確認ダイアログは固定テンプレートを一次根拠にする。
            # 未一致時は入力せず安全停止する。
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
            save_gacha_screenshot(f"after_{label}")
            if screen == "guild_select":
                settings_path = ROOT / ".local_gui_settings.json"
                try:
                    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
                    settings["guild"] = label
                    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except (OSError, ValueError, TypeError):
                    pass
            return True
        except Exception:
            return False

    def read_name(side: str) -> str | None:
        started = time.perf_counter()
        frame_index["value"] += 1
        path = live_dir / f"task_boss_gacha_{side}_{frame_index['value']}.png"
        capture.capture(path)
        import cv2
        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError("ボス名画像を読み込めません")
        # ボス名はOCRを使わず、収集済み肖像テンプレートだけで判定する。
        portrait_dir = ROOT / "data" / "template_migration" / "templates" / "boss_portraits"
        best_name, best_score = None, 0.0
        search = image[145:285, 350:510]
        for template_path in portrait_dir.glob("*.png"):
            # OpenCVのWindows版は日本語ファイル名を直接開けないため、
            # ASCII名へコピー済みのテンプレートだけを対象にする。
            if not template_path.name.isascii():
                continue
            template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
            if template is None or search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
                continue
            result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, _ = cv2.minMaxLoc(result)
            if score > best_score:
                best_name, best_score = template_path.stem, float(score)
        aliases = {
            "venom_salamandra": "ベノムサラマンドラ",
            "madam_electra": "マダムエレクトラ",
            "goblin_lord": "ゴブリンロード",
            "ultima_guardian": "アルティマガーディアン",
            "ultima_guardian_jp": "アルティマガーディアン",
            "chimera": "キマイラ",
        }
        if best_name in aliases and best_score >= 0.82:
            trace.record("template_boss_name", (time.perf_counter() - started) * 1000,
                         side=side, score=best_score, name=best_name)
            return aliases[best_name]
        raise RuntimeError(
            f"boss_name_template_unrecognized:{side}:best={best_name!r}:score={best_score:.3f}:image={path}"
        )

    def verify_guild(expected: str) -> bool:
        """テンプレートだけでギルド確認画面を検証する。"""
        return probe.target_visible("ギルド選択確認")

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
