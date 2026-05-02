from pathlib import Path

import desktop_launcher


def test_build_url_normalizes_path() -> None:
    assert desktop_launcher.build_url("127.0.0.1", 8788, "overlay") == "http://127.0.0.1:8788/overlay"


def test_browser_command_has_safe_fallback(monkeypatch) -> None:
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert desktop_launcher.browser_command("http://127.0.0.1:8788/overlay") == ["open", "http://127.0.0.1:8788/overlay"]
