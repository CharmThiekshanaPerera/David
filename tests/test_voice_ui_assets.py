from __future__ import annotations

from pathlib import Path


def test_voice_ui_includes_vad_and_barge_in_hooks() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "startVoiceVad" in app_js
    assert "stopVoiceVad" in app_js
    assert "handleVoiceBargeIn" in app_js
    assert "activeTurnId" in app_js
    assert "vadSilenceMs" in app_js
    assert "Voice barge-in" in app_js
