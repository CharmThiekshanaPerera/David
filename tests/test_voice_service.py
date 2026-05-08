from __future__ import annotations

import pytest

from web import voice_service


def _voice_config() -> voice_service.VoiceRuntimeConfig:
    return voice_service.VoiceRuntimeConfig(
        stt_engine="whisper_cli",
        stt_command="whisper",
        stt_model="base",
        stt_language="en",
        whisper_cpp_command="whisper-cli",
        whisper_cpp_model_path="",
        tts_engine="browser",
        tts_command="piper",
        tts_model_path="",
        voice_style="warm",
        voice_rate=100,
        chunk_chars=180,
    )


def test_normalize_transcript_text_filters_common_noise_tokens() -> None:
    normalized = voice_service.normalize_transcript_text("[Music]\n<|en|>\nHello there [Applause]")
    assert normalized == "Hello there"


def test_transcribe_audio_bytes_rejects_noise_only_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        voice_service,
        "_run_whisper_cli",
        lambda _input_path, *, tmp_root, config: "[Music]\n[noise]",
    )
    with pytest.raises(ValueError, match="did not detect clear spoken words"):
        voice_service.transcribe_audio_bytes(
            b"RIFF\x00\x00\x00\x00WAVEfmt ",
            mime_type="audio/wav",
            config=_voice_config(),
        )


def test_transcribe_audio_bytes_returns_cleaned_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        voice_service,
        "_run_whisper_cli",
        lambda _input_path, *, tmp_root, config: "[Music]\nDavid here [laughter]",
    )
    result = voice_service.transcribe_audio_bytes(
        b"RIFF\x00\x00\x00\x00WAVEfmt ",
        mime_type="audio/wav",
        config=_voice_config(),
    )
    assert result["text"] == "David here"
