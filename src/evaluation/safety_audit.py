from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_MODULES = frozenset({
    "pyautogui", "pydirectinput", "keyboard", "mouse", "win32api", "win32con",
    "openai", "anthropic", "requests", "httpx", "boto3",
})
FORBIDDEN_CALLS = frozenset({"click", "press", "key_down", "key_up", "move_to", "mouseDown", "mouseUp"})


def audit_no_game_io(paths: list[Path]) -> list[dict[str, str | int]]:
    """Find game-input imports/calls in safety-sensitive Python sources."""
    findings: list[dict[str, str | int]] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
                for name in names:
                    if name in FORBIDDEN_MODULES:
                        findings.append({"path": str(path), "line": node.lineno, "kind": "forbidden_import", "value": name})
            elif isinstance(node, ast.ImportFrom):
                name = (node.module or "").split(".")[0]
                if name in FORBIDDEN_MODULES:
                    findings.append({"path": str(path), "line": node.lineno, "kind": "forbidden_import", "value": name})
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                findings.append({"path": str(path), "line": node.lineno, "kind": "forbidden_call", "value": node.func.id})
    return findings
