"""黎明界ラビリンスの定型移動ランナー。

マス種別ごとの定型操作をスクリプトで即時実行する。
判断が必要な箇所はユーザー確認へ戻す。
"""

from __future__ import annotations

import random
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from decision.timing import AdaptiveWaitPolicy, wait_until_hidden, wait_until_visible

# 画面プローブを持たない互換アダプター向けの最小間隔。
# 実機ADBは画面変化検知が優先されるため、ここで2秒を固定しない。
SCRIPT_BUTTON_INTERVAL_SECONDS = 0.30
# BlueStacksのADB画面はウィンドウ枠を含まない1280x720座標を使用する。
ADB_SERIAL = "127.0.0.1:5555"
ADB_HEALTHCHECK_TIMEOUT_SECONDS = 3
MAP_SWIPE_START = (1120, 360)
MAP_SWIPE_END = (160, 360)
MAP_SWIPE_DURATION_MS = 300
BASE_SCREEN_SIZE = (1280, 720)


class AdbCoordinateScaler:
    """Convert design coordinates to the actual Android client resolution."""

    def __init__(self, serial: str = ADB_SERIAL, adb_command: str = "adb") -> None:
        self.serial = serial
        self.adb_command = adb_command
        self._size: tuple[int, int] | None = None

    def screen_size(self) -> tuple[int, int]:
        if self._size is not None:
            return self._size
        result = subprocess.run(
            [self.adb_command, "-s", self.serial, "shell", "wm", "size"],
            check=True, capture_output=True, text=True, timeout=ADB_HEALTHCHECK_TIMEOUT_SECONDS,
        )
        matches = re.findall(r"(\d+)x(\d+)", result.stdout)
        if not matches:
            raise RuntimeError(f"ADB画面サイズを取得できません: {self.serial}")
        width, height = (int(value) for value in matches[-1])
        if width <= 0 or height <= 0:
            raise RuntimeError(f"ADB画面サイズが不正です: {width}x{height}")
        base_width, base_height = BASE_SCREEN_SIZE
        if width * base_height != height * base_width:
            raise RuntimeError(
                f"画面比率が基準と異なるため安全停止: {width}x{height} != {base_width}x{base_height}"
            )
        self._size = (width, height)
        return self._size

    def point(self, point: tuple[int, int]) -> tuple[int, int]:
        width, height = self.screen_size()
        base_width, base_height = BASE_SCREEN_SIZE
        return (
            round(point[0] * width / base_width),
            round(point[1] * height / base_height),
        )


def debug_jitter_coordinate(
    point: tuple[int, int], *, max_offset: int = 2, rng: random.Random | None = None
) -> tuple[int, int]:
    """当たり判定検証用の微小ずらし。本番用途では呼び出さない。"""
    if len(point) != 2 or max_offset < 0:
        raise ValueError("point/max_offsetが不正です")
    source = rng or random.Random()
    return (
        point[0] + source.randint(-max_offset, max_offset),
        point[1] + source.randint(-max_offset, max_offset),
    )
ADB_BUTTON_COORDINATES: Mapping[str, tuple[int, int]] = {
    "EX装備": (817, 610),
    "おまかせ装備": (790, 640),
    # 「物理防御貫通」ボタン後に開く優先ステータス画面のラジオ位置。
    "物理防御貫通": (778, 243),
    "物理防御貫通ラジオ": (387, 336),
    "OK": (786, 638),
    "移動先確認OK": (785, 495),
    "装備確定": (1085, 640),
    "キャンセル": (195, 640),
    "バトル開始": (1135, 605),
    "次へ": (1105, 650),
    "閉じる": (640, 640),
    # エリアマップからの撤退と確認ダイアログ。
    "撤退する": (910, 650),
    "撤退確認OK": (785, 495),
    # キャラ／遺物の3候補ボタン（左・中央・右）。
    "候補1": (300, 590),
    "候補2": (640, 590),
    "候補3": (980, 590),
    "ショップ購入1": (330, 350),
    "ショップ購入2": (720, 350),
    "ショップ購入3": (1110, 350),
    "購入確認OK": (785, 575),
    "購入完了OK": (640, 495),
    "ショップ更新": (450, 648),
    "ショップ閉じる": (1090, 635),
    "ショップ終了OK": (785, 495),
    "ボスマス": (640, 350),
    # 初期キャラ選択画面の左下「マップ」ボタン。
    "マップ": (90, 640),
    "フォレスティエ": (1090, 560),
    "ギルド_フォレスティエ": (1090, 560),
    "ギルド選択確認": (940, 635),
    # エリアマップ上部のBOSSタイムライン。現在の1280x720レイアウトでは
    # 旧マップノード座標ではなく、上部の詳細ボタン中心を押す。
    "左BOSS": (675, 50),
    "右BOSS": (825, 50),
    "ボス移動OK": (785, 495),
    "パーティ1": (130, 120),
    "パーティ2": (300, 120),
    "パーティ3": (450, 120),
}

# 同一座標に別の意味のボタンが存在する画面遷移用座標。
# 必ず screen_id と組み合わせて参照し、座標だけを使い回さない。
ADB_SCREEN_COORDINATES: Mapping[str, Mapping[str, tuple[int, int]]] = {
    "quest_menu": {"ラビリンス": (1150, 540)},
    "labyrinth_top": {"出発": (780, 390)},
    "character_join": {"閉じる": (640, 580)},
    "item_reward": {"アイテム報酬閉じる": (640, 640)},
}


def screen_coordinate(screen_id: str, label: str) -> tuple[int, int]:
    """画面IDが一致した場合だけ、画面固有のADB座標を返す。"""
    try:
        return ADB_SCREEN_COORDINATES[screen_id][label]
    except KeyError as exc:
        raise RuntimeError(f"画面固有座標が未登録です: {screen_id}/{label}") from exc


def navigate_to_screen(
    target_screen: str,
    *,
    serial: str = ADB_SERIAL,
    screen_probe: Callable[[], str | None],
    max_steps: int = 8,
    debug_capture_dir: str | Path | None = None,
    debug_capture_prefix: str = "navigate",
) -> dict[str, object]:
    """Move through explicitly verified live transitions only.

    The live task scripts need a shared entry point, but a missing route must
    never be filled with a guessed coordinate.  At present the only generic
    transition owned by this module is the initial-character screen's map
    button; the reverse path is handled by its dedicated live task.
    """
    if not target_screen or max_steps < 0:
        raise ValueError("target_screen/max_stepsが不正です")
    current = screen_probe()
    trace: list[str | None] = [current]
    if current == target_screen:
        return {"status": "ready", "screen_id": current, "trace": trace, "steps": 0}
    transitions: Mapping[tuple[str | None, str], tuple[str, str]] = {
        ("initial_char", "boss_map"): ("マップ", "boss_map"),
    }
    for _ in range(max_steps):
        transition = transitions.get((current, target_screen))
        if transition is None:
            return {
                "status": "safety_stop",
                "reason": "unconfirmed_transition",
                "screen_id": current,
                "target_screen": target_screen,
                "trace": trace,
            }
        label, expected = transition
        coordinates = {label: ADB_BUTTON_COORDINATES[label]}
        adapter = AdbScreenAdapter(
            coordinates=coordinates,
            serial=serial,
            task_name=debug_capture_prefix,
            screen_guard=lambda _label, expected_screen=current: screen_probe() == expected_screen,
            screen_probe=screen_probe,
            adb_healthcheck=True,
            debug_capture_dir=debug_capture_dir,
            require_screen_change=True,
        )
        adapter.click(label)
        current = screen_probe()
        trace.append(current)
        if current == expected == target_screen:
            return {"status": "ready", "screen_id": current, "trace": trace, "steps": len(trace) - 1}
        return {
            "status": "safety_stop",
            "reason": "unexpected_transition",
            "screen_id": current,
            "target_screen": target_screen,
            "trace": trace,
        }
    return {"status": "safety_stop", "reason": "max_steps_exceeded", "screen_id": current, "target_screen": target_screen, "trace": trace}


def restart_adb_connection(
    *, serial: str = ADB_SERIAL, adb_command: str = "adb", timeout_seconds: float = ADB_HEALTHCHECK_TIMEOUT_SECONDS
) -> None:
    """ADBサーバーを再起動し、対象BlueStacksへ再接続する共通復旧処理。"""
    subprocess.run([adb_command, "kill-server"], check=False, capture_output=True, text=True, timeout=timeout_seconds)
    subprocess.run([adb_command, "start-server"], check=True, capture_output=True, text=True, timeout=timeout_seconds)
    subprocess.run([adb_command, "connect", serial], check=False, capture_output=True, text=True, timeout=timeout_seconds)


def ensure_adb_connection(
    *, serial: str = ADB_SERIAL, adb_command: str = "adb", timeout_seconds: float = ADB_HEALTHCHECK_TIMEOUT_SECONDS
) -> None:
    """タップ前のADB疎通確認。失敗時は1回だけ再起動・再接続して再確認する。"""
    command = [adb_command, "-s", serial, "get-state"]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout_seconds)
        return
    except (OSError, subprocess.SubprocessError):
        try:
            restart_adb_connection(serial=serial, adb_command=adb_command, timeout_seconds=timeout_seconds)
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout_seconds)
        except (OSError, subprocess.SubprocessError) as second_error:
            raise RuntimeError(f"ADB接続を復旧できません: {serial}") from second_error


def run_adb_coordinate_sequence(
    coordinates: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    *,
    serial: str = ADB_SERIAL,
    adb_command: str = "adb",
    interval_seconds: float | None = None,
    timing_policy: AdaptiveWaitPolicy | None = None,
    screen_probe: Callable[[], str | None] | None = None,
    healthcheck: bool = False,
    debug_jitter: int = 0,
    jitter_rng: random.Random | None = None,
    debug_capture_dir: str | Path | None = None,
    debug_capture_prefix: str = "tap_before",
    require_screen_change: bool = False,
    timing_trace=None,
    previous_screen_token: str | None = None,
    coordinate_scaler: AdbCoordinateScaler | None = None,
) -> None:
    """座標リストをADBで順番にタップする共通処理。"""
    if interval_seconds is None:
        interval_seconds = SCRIPT_BUTTON_INTERVAL_SECONDS
    if interval_seconds < 0:
        raise ValueError("タップ間隔は0以上で指定してください")
    if debug_jitter < 0 or debug_jitter > 2:
        raise ValueError("debug_jitterは0〜2pxに制限されます")
    if require_screen_change and (timing_policy is None or screen_probe is None):
        raise ValueError("画面変化必須時はtiming_policyとscreen_probeが必要です")
    scaler = coordinate_scaler or AdbCoordinateScaler(serial, adb_command)
    for index, point in enumerate(coordinates):
        if len(point) != 2:
            raise ValueError("座標は(x, y)の2要素で指定してください")
        source_point = debug_jitter_coordinate(point, max_offset=debug_jitter, rng=jitter_rng) if debug_jitter else point
        x, y = scaler.point(source_point)
        if debug_capture_dir is not None:
            _capture_tap_debug(
                x, y, output_dir=debug_capture_dir, prefix=debug_capture_prefix, serial=serial,
            )
        if healthcheck:
            health_started = time.monotonic()
            ensure_adb_connection(serial=serial, adb_command=adb_command)
            if timing_trace is not None:
                timing_trace.record("adb_healthcheck", (time.monotonic() - health_started) * 1000, serial=serial)
        if timing_policy is not None and screen_probe is not None:
            # Callers that just validated the target can pass that token to
            # avoid an identical ADB capture immediately before the tap.
            previous_token = previous_screen_token if index == 0 and previous_screen_token is not None else screen_probe()
        else:
            previous_token = None
        if timing_trace is not None and screen_probe is not None:
            timing_trace.record("screen_probe_before", 0.0, token=previous_token)
        started = time.monotonic()
        subprocess.run(
            [adb_command, "-s", serial, "shell", "input", "tap", str(x), str(y)],
            check=True,
            capture_output=True,
            text=True,
        )
        if timing_policy is not None and screen_probe is not None:
            wait_started = time.monotonic()
            _, _, changed = timing_policy.wait_for_change_checked(previous_token, screen_probe)
            if timing_trace is not None:
                timing_trace.record("screen_change_wait", (time.monotonic() - wait_started) * 1000,
                                     changed=changed)
            if require_screen_change and not changed:
                raise RuntimeError(f"タップ後に画面変化がないため停止: ({x},{y})")
        else:
            time.sleep(max(0.0, interval_seconds - (time.monotonic() - started)))
        if timing_trace is not None:
            timing_trace.record("adb_tap_total", (time.monotonic() - started) * 1000,
                                 coordinate=[x, y])


def run_adb_swipe(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    duration_ms: int = MAP_SWIPE_DURATION_MS,
    serial: str = ADB_SERIAL,
    adb_command: str = "adb",
    healthcheck: bool = False,
    screen_guard: Callable[[], bool] | None = None,
    operation_logger: object | None = None,
    task_name: str = "map_scan",
    timing_trace=None,
    coordinate_scaler: AdbCoordinateScaler | None = None,
) -> None:
    """Send one guarded Android swipe for map panning.

    The caller supplies the screen guard; a rejected/unknown screen never
    reaches ``input swipe``.  Coordinates are Android client coordinates.
    """
    if len(start) != 2 or len(end) != 2 or duration_ms < 0:
        raise ValueError("スワイプ座標または時間が不正です")
    if screen_guard is None:
        raise RuntimeError("画面ガード未指定のためスワイプを停止")
    if not bool(screen_guard()):
        raise RuntimeError("想定外画面のためスワイプを停止")
    if healthcheck:
        ensure_adb_connection(serial=serial, adb_command=adb_command)
    scaler = coordinate_scaler or AdbCoordinateScaler(serial, adb_command)
    actual_start = scaler.point(start)
    actual_end = scaler.point(end)
    started = time.monotonic()
    command = [
        adb_command, "-s", serial, "shell", "input", "swipe",
        str(actual_start[0]), str(actual_start[1]), str(actual_end[0]),
        str(actual_end[1]), str(duration_ms),
    ]
    for attempt in range(3):
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(0.1 * (attempt + 1))
    if timing_trace is not None:
        timing_trace.record("adb_swipe_total", (time.monotonic() - started) * 1000,
                            start=list(actual_start), end=list(actual_end),
                            requested_duration_ms=duration_ms)
    if operation_logger is not None:
        record = getattr(operation_logger, "record", None)
        if callable(record):
            record(
                task=task_name,
                purpose="エリアマス確認のマップ走査",
                screen_before="操作前画面をガード済み",
                action="ADB swipe",
                coordinate={"start": list(start), "end": list(end)},
                adb_serial=serial,
                outcome="ADB送信完了",
                duration_ms=round((time.monotonic() - started) * 1000, 1),
                screen_after="観測コールバックで確認",
            )


def scan_map_layout(
    adapter: ScreenAdapter,
    *,
    observe_layout: Callable[[], object | None],
    at_right_edge: Callable[[object | None], bool],
    at_left_edge: Callable[[object | None], bool],
    max_swipes: int = 12,
) -> dict[str, object] | str:
    """Scan map panels rightward, then deterministically return to the left.

    ``observe_layout`` is responsible for the smallest map ROI.  No swipe is
    sent until the current panel is observed; missing observations and edge
    timeouts are safety-stop results.
    """
    if max_swipes < 1:
        raise ValueError("max_swipes must be positive")
    swipe = getattr(adapter, "swipe", None)
    if not callable(swipe):
        return "安全停止: マップスワイプが未対応です"
    layouts: list[object] = []
    for _ in range(max_swipes + 1):
        layout = observe_layout()
        if layout is None:
            return "安全停止: マップ配置を確認できません"
        layouts.append(layout)
        if at_right_edge(layout):
            break
        swipe(MAP_SWIPE_START, MAP_SWIPE_END)
    else:
        return "安全停止: マップ右端へ到達できません"
    for _ in range(max_swipes + 1):
        layout = observe_layout()
        if layout is None:
            return "安全停止: マップ左戻りを確認できません"
        if at_left_edge(layout):
            return {"area_map": layouts, "returned_left": True, "swipe_count": len(layouts) - 1}
        swipe(MAP_SWIPE_END, MAP_SWIPE_START)
    return "安全停止: マップ左端へ復帰できません"


MAX_DEBUG_CAPTURE_PAIRS = 100


def _capture_tap_debug(x: int, y: int, *, output_dir: str | Path, prefix: str, serial: str = ADB_SERIAL) -> Path:
    """タップ直前画面に予定座標を描画して保存する検証用処理。"""
    from PIL import Image, ImageDraw

    from vision.capture import AdbScreenCapture

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    index = len(list(destination.glob(f"{prefix}_*_source.png"))) + 1
    if index > MAX_DEBUG_CAPTURE_PAIRS:
        raise RuntimeError(f"デバッグ証跡上限到達: {prefix}")
    source = destination / f"{prefix}_{index:04d}_source.png"
    overlay = destination / f"{prefix}_{index:04d}.png"
    AdbScreenCapture(serial=serial).capture(source)
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline=(255, 0, 0), width=3)
    draw.line((x - 20, y, x + 20, y), fill=(255, 0, 0), width=2)
    draw.line((x, y - 20, x, y + 20), fill=(255, 0, 0), width=2)
    draw.text((x + 12, y + 12), f"TAP ({x},{y})", fill=(255, 0, 0))
    image.save(overlay, format="PNG")
    return overlay


class ScreenAdapter(Protocol):
    def is_visible(self, label: str) -> bool: ...
    def click(self, label: str) -> None: ...

    def wait_until_visible(self, label: str, timeout_seconds: int = 60) -> bool: ...

    def is_selected(self, label: str) -> bool: ...

    def finish_if_present(self, *labels: str) -> bool: ...

    def wait_until_hidden(self, label: str, timeout_seconds: float = 1.5) -> bool: ...


class AdbScreenAdapter:
    """固定座標のラビリンス操作をBlueStacksへADBで送るアダプター。

    座標はADBの端末画面座標で指定する（BlueStacksの外枠座標ではない）。
    画面認識が必要な操作は、呼び出し側の認識アダプターへ委譲する。
    """

    def __init__(
        self,
        coordinates: Mapping[str, tuple[int, int]] | None = None,
        serial: str = ADB_SERIAL,
        adb_command: str = "adb",
        operation_logger: object | None = None,
        task_name: str = "adb_script",
        screen_guard: Callable[[str], bool] | None = None,
        timing_policy: AdaptiveWaitPolicy | None = None,
        screen_probe: Callable[[], str | None] | None = None,
        visibility_probe: Callable[[str], bool] | None = None,
        adb_healthcheck: bool = False,
        debug_capture_dir: str | Path | None = None,
        require_screen_change: bool = False,
        timing_trace=None,
    ) -> None:
        self.coordinates = dict(coordinates or ADB_BUTTON_COORDINATES)
        self.serial = serial
        self.adb_command = adb_command
        self.operation_logger = operation_logger
        self.task_name = task_name
        self.screen_guard = screen_guard
        # プローブが渡された場合は、固定2秒ではなく共通の軽量待機を自動利用する。
        self.timing_policy = timing_policy or (AdaptiveWaitPolicy() if screen_probe is not None else None)
        self.screen_probe = screen_probe
        self.visibility_probe = visibility_probe
        self.adb_healthcheck = adb_healthcheck
        self.debug_capture_dir = debug_capture_dir
        self.require_screen_change = require_screen_change
        self.timing_trace = timing_trace
        # is_visible() 直後に click() が同じROIを再認識する二重ADB取得を
        # 防ぐ。短いTTLに限定し、タップ後は必ず無効化する。
        self._visibility_cache: dict[str, tuple[float, bool]] = {}
        self._visibility_cache_ttl = 0.20

    def is_visible(self, label: str) -> bool:
        if label in FORBIDDEN:
            return False
        if label not in self.coordinates:
            return False
        # A coordinate entry is not evidence that the control is on screen.
        # When a live target probe is available, use it for every caller
        # (including the fixed departure script) so stale coordinates cannot
        # trigger an input on a different Android screen.
        if self.visibility_probe is not None:
            cached = self._visibility_cache.get(label)
            if cached is not None and time.monotonic() - cached[0] <= self._visibility_cache_ttl:
                return cached[1]
            try:
                visible = bool(self.visibility_probe(label))
                self._visibility_cache[label] = (time.monotonic(), visible)
                return visible
            except Exception:
                return False
        return True

    def click(self, label: str) -> None:
        if label in FORBIDDEN:
            raise RuntimeError(f"禁止操作のためADB送信を停止: {label}")
        operation_started = time.monotonic()
        if self.screen_guard is not None:
            try:
                safe = bool(self.screen_guard(label))
            except Exception as exc:
                raise RuntimeError(f"画面ガードの判定に失敗したため停止: {label}") from exc
            if not safe:
                raise RuntimeError(f"想定外画面のためADB操作を停止: {label}")
        # 座標が登録されているだけではタップしない。現在画面の対象表示を
        # 軽量プローブで確認できる場合に限り、表示中の対象へ送信する。
        if self.visibility_probe is not None:
            try:
                cached = self._visibility_cache.get(label)
                if cached is not None and time.monotonic() - cached[0] <= self._visibility_cache_ttl:
                    visible = cached[1]
                else:
                    visible = bool(self.visibility_probe(label))
            except Exception as exc:
                raise RuntimeError(f"タップ対象の表示確認に失敗したため停止: {label}") from exc
            if not visible:
                raise RuntimeError(f"タップ対象が表示されていないため停止: {label}")
        try:
            x, y = self.coordinates[label]
        except KeyError as exc:
            raise KeyError(f"ADB座標が未登録です: {label}") from exc
        run_adb_coordinate_sequence(
            [(x, y)], serial=self.serial, adb_command=self.adb_command,
            timing_policy=self.timing_policy, screen_probe=self.screen_probe,
            healthcheck=self.adb_healthcheck,
            debug_capture_dir=self.debug_capture_dir,
            debug_capture_prefix=self.task_name,
            require_screen_change=self.require_screen_change,
            timing_trace=self.timing_trace,
        )
        self._visibility_cache.clear()
        if self.operation_logger is not None:
            record = getattr(self.operation_logger, "record", None)
            if callable(record):
                record(
                    task=self.task_name,
                    purpose=f"定型操作: {label}",
                    screen_before="未取得（操作前画面を呼び出し側で記録）",
                    action=f"ADB tap: {label}",
                    coordinate=(x, y),
                    adb_serial=self.serial,
                    outcome="ADB送信完了",
                    duration_ms=round((time.monotonic() - operation_started) * 1000, 1),
                    screen_after="未取得（操作後画面を呼び出し側で記録）",
                )

    def swipe(self, start: tuple[int, int] = MAP_SWIPE_START,
              end: tuple[int, int] = MAP_SWIPE_END,
              *, duration_ms: int = MAP_SWIPE_DURATION_MS) -> None:
        """Pan the open map while applying the same screen guard as taps."""
        run_adb_swipe(
            start, end, duration_ms=duration_ms, serial=self.serial,
            adb_command=self.adb_command, healthcheck=self.adb_healthcheck,
            screen_guard=(lambda: bool(self.screen_guard("マップ"))) if self.screen_guard else None,
            operation_logger=self.operation_logger, task_name=self.task_name,
            timing_trace=self.timing_trace,
        )

    def wait_until_visible(self, label: str, timeout_seconds: int = 60) -> bool:
        if self.visibility_probe is None:
            return self.is_visible(label)
        return wait_until_visible(
            lambda: bool(self.visibility_probe(label)),
            timeout_seconds=float(timeout_seconds),
        )

    def wait_until_hidden(self, label: str, timeout_seconds: float = 1.5) -> bool:
        if self.visibility_probe is None:
            return False
        return wait_until_hidden(
            lambda: bool(self.visibility_probe(label)),
            timeout_seconds=timeout_seconds,
        )

    def is_selected(self, label: str) -> bool:
        return False

    def finish_if_present(self, *labels: str) -> bool:
        for label in labels:
            if self.is_visible(label):
                self.click(label)
                return True
        return False


def click_and_wait(adapter: ScreenAdapter, label: str, *, wait_hidden: bool = False) -> None:
    """クリック後、必要なら対象要素が消えるまでピンポイント確認する。"""
    adapter.click(label)
    if wait_hidden and not adapter.wait_until_hidden(label):
        raise RuntimeError(f"操作対象が消えないため停止: {label}")
    if not wait_hidden and not isinstance(adapter, AdbScreenAdapter):
        time.sleep(SCRIPT_BUTTON_INTERVAL_SECONDS)


CANDIDATE_BUTTONS = ("候補1", "候補2", "候補3")


def select_candidate_and_close(adapter: ScreenAdapter, choice: int) -> str:
    """候補を選択し、同じ処理として続けて閉じる。"""
    if choice not in (1, 2, 3):
        raise ValueError("候補は1、2、3のいずれかを指定してください")
    candidate = CANDIDATE_BUTTONS[choice - 1]
    if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(candidate):
        return f"画面確認待ち: {candidate}"
    click_and_wait(adapter, candidate)
    if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible("閉じる"):
        return "画面確認待ち: 閉じる"
    click_and_wait(adapter, "閉じる")
    return f"{candidate}を選択して閉じました"


def select_boss_and_confirm(adapter: ScreenAdapter) -> str:
    """ボスマス選択後の移動確認OKまでを1セットで実行する。"""
    for label in ("ボスマス", "ボス移動OK"):
        if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(label):
            return f"画面確認待ち: {label}"
        click_and_wait(adapter, label)
    return "ボスマスを選択して移動を確定しました"


def confirm_boss_names(
    adapter: ScreenAdapter,
    read_boss_name: Callable[[str], str | None],
    *,
    wait_for_map_return: Callable[[], bool] | None = None,
) -> dict[str, str] | str:
    """左右のボス名を、必ず表示確認を挟んで順番に取得する。

    左側の詳細を閉じる前に右側へ進むことはない。名前が空、又は
    ``None`` の場合は安全停止し、閉じる・次のボス・挑戦操作を行わない。
    ``read_boss_name`` は画面認識側（OCR）から現在表示中の名前を返す。
    """
    names: dict[str, str] = {}
    if isinstance(adapter, AdbScreenAdapter) and adapter.screen_guard is None:
        return "安全停止: ADBボス確認には画面ガードが必要です"
    for side, open_label, close_label in (
        ("left", "左BOSS", "閉じる"),
        ("right", "右BOSS", "閉じる"),
    ):
        if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(open_label):
            return f"安全停止: {open_label}が表示されていません"
        if (
            isinstance(adapter, AdbScreenAdapter)
            and adapter.visibility_probe is not None
            and not adapter.wait_until_visible(open_label, timeout_seconds=2)
        ):
            return f"安全停止: {open_label}の表示復帰を確認できません"
        click_and_wait(adapter, open_label)
        name = read_boss_name(side)
        if not isinstance(name, str) or not name.strip():
            return f"安全停止: {side}ボス名を確認できません"
        names[side] = name.strip()
        if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(close_label):
            return f"安全停止: {close_label}が表示されていません（{side}ボス確認後）"
        click_and_wait(adapter, close_label)
        # 左詳細を閉じた直後は復帰アニメーション中のことがある。
        # マップ画面への復帰を確認できるまで、右ボスへのタップを許可しない。
        if side == "left" and wait_for_map_return is not None and not wait_for_map_return():
            return "安全停止: 左ボス詳細を閉じた後、マップ復帰を確認できません"
    return names


def open_map_and_confirm_boss_names(
    adapter: ScreenAdapter,
    read_boss_name: Callable[[str], str | None],
    *,
    wait_for_map_return: Callable[[], bool] | None = None,
) -> dict[str, str] | str:
    """初期キャラ画面から、マップ表示完了後にボス名を確認する。"""
    if isinstance(adapter, AdbScreenAdapter) and adapter.screen_guard is None:
        return "安全停止: ADBマップ操作には画面ガードが必要です"
    if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible("マップ"):
        return "安全停止: マップボタンが表示されていません"
    click_and_wait(
        adapter,
        "マップ",
        wait_hidden=(not isinstance(adapter, AdbScreenAdapter))
        or getattr(adapter, "visibility_probe", None) is not None,
    )
    return confirm_boss_names(
        adapter,
        read_boss_name,
        wait_for_map_return=wait_for_map_return,
    )


# 「撤退する」は対象外ボス時の再抽選、および戦闘で勝利困難な場合の
# 中断・やり直しに必要な正規フローとして許可。
# 一方、ラビリンスを完全終了する帰還・終了操作は誤タップ防止のため常時禁止。
FORBIDDEN = frozenset({
    "帰還する", "帰還する（報酬あり）", "終了する", "選択終了",
})

def close_departure_bonus(adapter: ScreenAdapter) -> str:
    """出発直後のボーナス窓を閉じる共通処理。

    閉じるボタンが存在しない画面では操作せず、呼び出し側の画面判定へ戻す。
    """
    if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible("閉じる"):
        return "画面確認待ち: 出発ボーナス"
    # ADBアダプターでは可視性プローブが任意のため、送信後の画面判定は
    # 次の共通タイトル確認に委譲する。
    click_and_wait(adapter, "閉じる", wait_hidden=not isinstance(adapter, AdbScreenAdapter))
    return "出発ボーナスを閉じました"


def close_dialog(adapter: ScreenAdapter, *, label: str = "閉じる") -> str:
    """汎用の閉じるタスク。対象ボタンが確認できない場合は操作しない。"""
    if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(label):
        return f"画面確認待ち: {label}"
    click_and_wait(adapter, label, wait_hidden=not isinstance(adapter, AdbScreenAdapter))
    return f"{label}を押しました"


def select_guild(adapter: ScreenAdapter, guild: str = "フォレスティエ") -> str:
    """承認済みギルドを選択し、確認画面まで進める共通タスク。"""
    labels = {"フォレスティエ": ("ギルド_フォレスティエ", "ギルド選択確認")}
    if guild not in labels:
        raise ValueError(f"未承認のギルドです: {guild}")
    for label in labels[guild]:
        if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(label):
            return f"画面確認待ち: {label}"
        click_and_wait(adapter, label)
    return f"{guild}を選択して出発確認へ進みました"


def tap_next(adapter: ScreenAdapter, *, label: str = "次へ") -> str:
    """汎用の次へタスク。報酬・説明など複数画面で再利用する。"""
    if not isinstance(adapter, AdbScreenAdapter) and not adapter.is_visible(label):
        return f"画面確認待ち: {label}"
    click_and_wait(adapter, label)
    return f"{label}を押しました"


def inspect_game_window_title(
    read_title: Callable[[], str | None],
    *,
    allowed_titles: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    """ゲーム内ウィンドウタイトルを共通取得し、未知タイトルを安全停止扱いにする。"""
    title = read_title()
    normalized = title.strip() if isinstance(title, str) else ""
    if not normalized:
        return {"screen_status": "unknown", "reason": "game_window_title_missing"}
    result = {"window_title": normalized}
    if allowed_titles is not None and normalized not in allowed_titles:
        result.update({"screen_status": "unexpected", "reason": "game_window_title_unexpected"})
    else:
        result["screen_status"] = "known"
    return result


if __name__ == "__main__":
    print("Computer Use の画面アダプターを接続して実行してください。")
