from unittest.mock import patch

import pytest

from scripts.labyrinth_route import AdbCoordinateScaler


def test_scaler_reads_android_client_size_and_scales_coordinates():
    completed = type("Completed", (), {"stdout": "Physical size: 1920x1080\n"})()
    with patch("scripts.labyrinth_route.subprocess.run", return_value=completed):
        scaler = AdbCoordinateScaler("127.0.0.1:5555")
        assert scaler.point((640, 360)) == (960, 540)
        assert scaler.point((1280, 720)) == (1920, 1080)


def test_scaler_rejects_different_aspect_ratio():
    completed = type("Completed", (), {"stdout": "Physical size: 1280x752\n"})()
    with patch("scripts.labyrinth_route.subprocess.run", return_value=completed), pytest.raises(RuntimeError, match="画面比率"):
            AdbCoordinateScaler().screen_size()
