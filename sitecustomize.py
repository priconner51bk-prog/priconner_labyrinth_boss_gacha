"""Keep the bundled Python Tcl/Tk runtime discoverable on Windows.

Some pyenv-win installations leave Tcl/Tk discovery to an incomplete
registry/PATH setup.  Python's ``site`` module imports this file at startup,
so GUI tests and ``python main.py`` use the same interpreter-local runtime.
Existing valid environment overrides are preserved.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _set_runtime_path(variable: str, directory: Path, marker: str) -> None:
    current = os.environ.get(variable)
    if current and (Path(current) / marker).is_file():
        return
    if (directory / marker).is_file():
        os.environ[variable] = str(directory)


_tcl_root = Path(sys.prefix) / "tcl"
_set_runtime_path("TCL_LIBRARY", _tcl_root / "tcl8.6", "init.tcl")
_set_runtime_path("TK_LIBRARY", _tcl_root / "tk8.6", "tk.tcl")
