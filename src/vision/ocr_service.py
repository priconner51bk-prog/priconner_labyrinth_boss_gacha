"""常駐PaddleOCRへの軽量なJSON Linesクライアント。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

from .ocr import OCRLine, normalize_ocr_result

HOST = "127.0.0.1"
PORT = 18765
ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "scripts" / "tool_ocr_server.py"


def _exchange(request: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        data = bytearray()
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("ocr_server_closed")
            data.extend(chunk)
    result = json.loads(data.decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("ocr_server_invalid_response")
    return result


def ensure_server(*, startup_timeout: float = 30.0) -> None:
    """サーバーがなければ1回だけバックグラウンド起動する。"""
    if not SERVER.is_file():
        raise RuntimeError("ocr_service_server_unavailable")
    try:
        _exchange({"op": "ping"}, timeout=0.5)
        return
    except Exception:
        pass
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([sys.executable, str(SERVER)], cwd=str(ROOT),
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, creationflags=creationflags,
                      close_fds=os.name != "nt")
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        try:
            _exchange({"op": "ping"}, timeout=0.5)
            return
        except Exception:
            time.sleep(0.1)
    raise TimeoutError("ocr_server_start_timeout")


class OCRServiceAdapter:
    """PaddleOCRAdapter互換の常駐サービス利用ラッパー。"""

    def __init__(self, *, language: str = "jpn") -> None:
        self.language = language
        ensure_server()

    def recognize(self, image_path: str | Path, *, roi: Any = None) -> list[OCRLine]:
        request: dict[str, Any] = {"op": "recognize", "path": str(Path(image_path).resolve()), "language": self.language}
        if roi is not None:
            request["roi"] = roi.model_dump() if hasattr(roi, "model_dump") else roi
        result = _exchange(request)
        if result.get("status") != "ok":
            raise RuntimeError(str(result.get("reason", "ocr_failed")))
        return normalize_ocr_result(result.get("lines", []))
