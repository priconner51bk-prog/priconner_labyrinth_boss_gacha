"""Helpers for starting non-interactive child processes without console flashes."""

from __future__ import annotations

import subprocess
from typing import Any


def run_without_console(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """Run a child process without creating a Windows console window.

    On non-Windows systems ``creationflags=0`` is accepted by subprocess and
    keeps this helper portable. GUI processes such as BlueStacks and the Tk
    control window must continue to use their explicit ``Popen`` launchers.
    """
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    check = kwargs.pop("check", False)
    return subprocess.run(*popenargs, check=check, **kwargs)
