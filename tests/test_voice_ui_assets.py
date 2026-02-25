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


def test_voice_ui_continual_mode_rearm_and_echo_guard_hooks_present() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "function scheduleContinualRearm(" in app_js
    assert "function voiceEchoGuardActive()" in app_js
    assert "scheduleContinualRearm(\"reply_complete\")" in app_js
    assert "voiceEchoGuardActive()" in app_js
    assert "voice_post_reply_delay_ms" in app_js


def test_voice_ui_continual_pause_resume_end_controls_present() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "pauseContinualVoiceChat" in app_js
    assert "resumeContinualVoiceChat" in app_js
    assert "stopContinualVoiceChat" in app_js
    assert "voicePauseBtn" in app_js
    assert "voiceResumeBtn" in app_js
    assert "voiceEndConversationBtn" in app_js


def test_voice_ui_continual_barge_in_and_confirmation_gates_present() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "handleVoiceBargeIn(\"speech detected while assistant audio was active\")" in app_js
    assert "abortVoiceStream();" in app_js
    assert "clearVoiceAudioQueue(true);" in app_js
    assert "window.confirm(`Run this goal from voice transcript?" in app_js
    assert "overwrite_confirmation_required" in app_js


def test_voice_ui_continual_controls_visible_in_html() -> None:
    index_html = Path("web/static/index.html").read_text(encoding="utf-8")
    assert "settingVoiceContinuousMode" in index_html
    assert "settingVoicePostReplyDelayMs" in index_html
    assert "settingVoiceStopPhrases" in index_html
    assert "settingVoiceStopPhrasesResetBtn" in index_html
    assert "voiceContinuousMode" in index_html
    assert "voicePauseBtn" in index_html
    assert "voiceResumeBtn" in index_html
    assert "voiceEndConversationBtn" in index_html
    assert "voiceContinualIndicator" in index_html


def test_voice_ui_stop_phrases_bound_to_backend_not_local_storage() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "voice_stop_phrases" in app_js
    assert "dcc_voice_stop_phrases" not in app_js
    assert "settingVoiceStopPhrasesResetBtn" in app_js


def test_voice_ui_stop_phrase_matching_exits_continual_mode_deterministically() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "matchesVoiceStopPhrase(transcript)" in app_js
    assert "stopContinualVoiceChat(\"Continual voice chat stopped by phrase.\")" in app_js
