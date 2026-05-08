from __future__ import annotations

from web.control_center import ControlSettings


def test_control_settings_voice_defaults_include_vad_min_speech() -> None:
    settings = ControlSettings.from_dict({})
    assert settings.voice_input_mode == "manual"
    assert settings.voice_continuous_mode is False
    assert int(settings.voice_post_reply_delay_ms) == 450
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


def test_control_settings_voice_continual_delay_bounded() -> None:
    settings = ControlSettings.from_dict(
        {
            "voice_continuous_mode": True,
            "voice_post_reply_delay_ms": 9999,
        }
    )
    assert settings.voice_continuous_mode is True
    assert int(settings.voice_post_reply_delay_ms) == 800


def test_control_settings_voice_stop_phrases_normalized_from_string() -> None:
    settings = ControlSettings.from_dict(
        {
            "voice_stop_phrases": " stop listening , END CHAT, bye david, , bye david ",
        }
    )
    assert settings.voice_stop_phrases == ["stop listening", "end chat", "bye david"]


def test_control_settings_voice_stop_phrases_normalized_from_list_and_limited() -> None:
    payload = [f" phrase_{idx:02d} " for idx in range(20)] + ["", "phrase_00"]
    settings = ControlSettings.from_dict({"voice_stop_phrases": payload})
    assert len(settings.voice_stop_phrases) == 12
    assert settings.voice_stop_phrases[0] == "phrase_00"
    assert settings.voice_stop_phrases[-1] == "phrase_11"


def test_control_settings_voice_stop_phrases_defaults_when_missing_or_empty() -> None:
    missing = ControlSettings.from_dict({})
    empty = ControlSettings.from_dict({"voice_stop_phrases": " , ,, "})
    assert missing.voice_stop_phrases == ["stop listening", "end chat", "bye david"]
    assert empty.voice_stop_phrases == ["stop listening", "end chat", "bye david"]


def test_control_settings_plan_quality_threshold_bounds() -> None:
    default_settings = ControlSettings.from_dict({})
    high = ControlSettings.from_dict({"plan_quality_threshold": 140})
    low = ControlSettings.from_dict({"plan_quality_threshold": -10})

    assert int(default_settings.plan_quality_threshold) == 0
    assert int(high.plan_quality_threshold) == 100
    assert int(low.plan_quality_threshold) == 0
