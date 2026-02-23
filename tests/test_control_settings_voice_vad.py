from __future__ import annotations

from web.control_center import ControlSettings


def test_control_settings_voice_defaults_include_vad_min_speech() -> None:
    settings = ControlSettings.from_dict({})
    assert settings.voice_input_mode == "manual"
    assert float(settings.voice_vad_threshold) == 0.035
    assert int(settings.voice_vad_silence_ms) == 900
    assert int(settings.voice_vad_min_speech_ms) == 300


def test_control_settings_accepts_vad_alias_fields_and_ptt_back_compat() -> None:
    settings = ControlSettings.from_dict(
        {
            "voice_input_mode": "ptt",
            "vad_threshold": 0.051,
            "vad_silence_ms": 1330,
            "vad_min_speech_ms": 640,
        }
    )
    assert settings.voice_input_mode == "manual"
    assert float(settings.voice_vad_threshold) == 0.051
    assert int(settings.voice_vad_silence_ms) == 1330
    assert int(settings.voice_vad_min_speech_ms) == 640
