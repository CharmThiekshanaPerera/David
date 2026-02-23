from __future__ import annotations

import re
from pathlib import Path


def test_voice_ui_includes_vad_and_barge_in_hooks() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "startVoiceVad" in app_js
    assert "stopVoiceVad" in app_js
    assert "handleVoiceBargeIn" in app_js
    assert "cancelVoiceTurn" in app_js
    assert "abortVoiceTranscription" in app_js
    assert "activeTurnId" in app_js
    assert "vadSilenceMs" in app_js
    assert "vadMinSpeechMs" in app_js
    assert "nextVoiceTurnState" in app_js
    assert "evaluateVadFrame" in app_js
    assert "Voice barge-in" in app_js


def test_voice_ui_state_machine_states_and_transitions_present() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert '"idle", "listening_armed", "recording", "stopping", "transcribing", "responding"' in app_js
    assert "transitionVoiceTurn(\"start_recording\")" in app_js
    assert "transitionVoiceTurn(\"stop_request\")" in app_js
    assert "transitionVoiceTurn(\"transcribe_start\")" in app_js
    assert "transitionVoiceTurn(\"respond_start\")" in app_js
    assert "VOICE_VAD_START_DEBOUNCE_MS" in app_js
    assert "shouldStartRecording" in app_js
    assert "shouldStopRecording" in app_js
    assert "shouldAccept" in app_js


def test_voice_ui_cancel_path_aborts_stream_and_transcription() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    cancel_block = re.search(r"async function cancelVoiceTurn\([^)]*\)\s*\{(?P<body>.*?)\n\}", app_js, re.DOTALL)
    assert cancel_block, "cancelVoiceTurn function not found"
    body = cancel_block.group("body")
    assert "abortVoiceStream();" in body
    assert "abortVoiceTranscription();" in body
    assert "stopVoiceListening({" in body
    assert "stopVoiceVad({ submit: false })" in body
