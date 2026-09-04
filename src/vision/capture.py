from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Callable


@dataclass(frozen=True)
class CapturedFrame:
    image_path: str
    monitor_index: int
    captured_at: datetime


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    width: int
    height: int


class ScreenCapture:
    """Read-only desktop capture boundary; it has no input or game controls."""

    def __init__(self, monitor_index: int = 1, capture_png: Callable[[int], bytes] | None = None):
        if monitor_index < 1:
            raise ValueError("monitor_index must be at least 1")
        self.monitor_index = monitor_index
        self._capture_png = capture_png or self._capture_with_mss

    def capture(self, output_path: str | Path) -> CapturedFrame:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        png = self._capture_png(self.monitor_index)
        if not isinstance(png, bytes) or not png:
            raise ValueError("capture backend must return non-empty PNG bytes")
        path.write_bytes(png)
        return CapturedFrame(str(path), self.monitor_index, datetime.now(timezone.utc))

    @staticmethod
    def _capture_with_mss(monitor_index: int) -> bytes:
        try:
            import mss
            import mss.tools
        except ImportError as exc:
            raise RuntimeError("画面Captureにはmssが必要です") from exc
        with mss.MSS() as source:
            if monitor_index >= len(source.monitors):
                raise ValueError(f"monitor_index is unavailable: {monitor_index}")
            monitor = source.monitors[monitor_index]
            image = source.grab(monitor)
            return mss.tools.to_png(image.rgb, image.size)


class AdbScreenCapture:
    """ADB経由でAndroid端末の画面を取得する。Windows前面状態に依存しない。"""

    def __init__(self, serial: str = "127.0.0.1:5555", adb_command: str = "adb", timeout_seconds: float = 5.0, timing_trace=None):
        if not serial.strip():
            raise ValueError("serial must not be empty")
        self.serial = serial
        self.adb_command = adb_command
        self.timeout_seconds = timeout_seconds
        self.timing_trace = timing_trace

    def capture(self, output_path: str | Path) -> CapturedFrame:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        started = __import__("time").perf_counter()
        result = subprocess.run(
            [self.adb_command, "-s", self.serial, "exec-out", "screencap", "-p"],
            check=True, capture_output=True, timeout=self.timeout_seconds,
        )
        if self.timing_trace is not None:
            self.timing_trace.record("adb_screencap", (__import__("time").perf_counter() - started) * 1000,
                                     serial=self.serial, bytes=len(result.stdout))
        if not result.stdout:
            raise RuntimeError("ADB screencap returned an empty image")
        path.write_bytes(result.stdout)
        return CapturedFrame(str(path), 0, datetime.now(timezone.utc))


class WindowsGraphicsCapture:
    """Windows Graphics Capture APIによるBlueStacksの背面対応キャプチャ。"""

    def __init__(self, window_name: str = "BlueStacks App Player"):
        self.window_name = window_name

    def capture(self, output_path: str | Path) -> CapturedFrame:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from windows_capture import InternalCaptureControl, WindowsCapture
        except ImportError as exc:
            raise RuntimeError("Windows Graphics Captureにはwindows-captureが必要です") from exc
        captured = {"done": False}
        capture = WindowsCapture(
            cursor_capture=None,
            draw_border=None,
            monitor_index=None,
            window_name=self.window_name,
            minimum_update_interval=1,
        )

        @capture.event
        def on_frame_arrived(frame, control: InternalCaptureControl):
            if not captured["done"]:
                frame.save_as_image(str(path))
                captured["done"] = True
            control.stop()

        @capture.event
        def on_closed():
            return None

        capture.start()
        if not captured["done"] or not path.exists():
            raise RuntimeError(f"Windows Graphics Captureで対象ウィンドウを取得できません: {self.window_name}")
        return CapturedFrame(str(path), 0, datetime.now(timezone.utc))


class BlueStacksWindowCapture:
    """Read only the named BlueStacks window; never fall back to a whole monitor."""

    def __init__(
        self,
        title_contains: str = "BlueStacks",
        *,
        find_window: Callable[[str], WindowRect] | None = None,
        capture_png: Callable[[WindowRect], bytes] | None = None,
    ) -> None:
        if not title_contains.strip():
            raise ValueError("title_contains must not be empty")
        self.title_contains = title_contains
        self._find_window = find_window or self._find_windows_window
        self._capture_png = capture_png or self._capture_window_with_mss

    def capture(self, output_path: str | Path) -> CapturedFrame:
        path = Path(output_path)
        rect = self._find_window(self.title_contains)
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError("BlueStacks window has an invalid size")
        png = self._capture_png(rect)
        if not isinstance(png, bytes) or not png:
            raise ValueError("capture backend must return non-empty PNG bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return CapturedFrame(str(path), 0, datetime.now(timezone.utc))

    @staticmethod
    def _capture_window_with_mss(rect: WindowRect) -> bytes:
        try:
            import mss
            import mss.tools
        except ImportError as exc:
            raise RuntimeError("画面Captureにはmssが必要です") from exc
        with mss.MSS() as source:
            image = source.grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
            return mss.tools.to_png(image.rgb, image.size)

    @staticmethod
    def _find_windows_window(title_contains: str) -> WindowRect:
        """Find one visible matching Windows window without third-party APIs."""
        if __import__("sys").platform != "win32":
            raise RuntimeError("BlueStacks window capture is supported on Windows only")
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        matches: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def collect(hwnd: int, _lparam: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, len(title))
                if title_contains.casefold() in title.value.casefold():
                    matches.append(hwnd)
            return True

        user32.EnumWindows(callback_type(collect), 0)
        if not matches:
            raise RuntimeError(f"BlueStacks window was not found: {title_contains}")
        rect = wintypes.RECT()
        if not user32.GetClientRect(matches[0], ctypes.byref(rect)):
            raise OSError(ctypes.get_last_error(), "GetClientRect failed")
        origin = wintypes.POINT(rect.left, rect.top)
        corner = wintypes.POINT(rect.right, rect.bottom)
        if not user32.ClientToScreen(matches[0], ctypes.byref(origin)):
            raise OSError(ctypes.get_last_error(), "ClientToScreen failed")
        if not user32.ClientToScreen(matches[0], ctypes.byref(corner)):
            raise OSError(ctypes.get_last_error(), "ClientToScreen failed")
        return WindowRect(origin.x, origin.y, corner.x - origin.x, corner.y - origin.y)


