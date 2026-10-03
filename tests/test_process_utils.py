from scripts import process_utils


def test_run_without_console_adds_windows_no_console_flag(monkeypatch):
    sentinel = object()
    captured = {}
    monkeypatch.setattr(process_utils.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    result = process_utils.run_without_console(["adb", "devices"], capture_output=True)

    assert result is sentinel
    assert captured["args"] == (["adb", "devices"],)
    assert captured["kwargs"]["creationflags"] == 0x08000000


def test_run_without_console_preserves_explicit_creation_flags(monkeypatch):
    captured = {}
    monkeypatch.setattr(process_utils.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(process_utils.subprocess, "run", lambda *args, **kwargs: captured.update(kwargs))

    process_utils.run_without_console(["adb"], creationflags=7)

    assert captured["creationflags"] == 7
