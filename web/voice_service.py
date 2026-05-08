from __future__ import annotations

import base64
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MIME_EXTENSION_MAP = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
}
SAFE_COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9_./:-]+$")
STT_ENGINES = {"none", "whisper_cli", "whisper_cpp"}
TTS_ENGINES = {"browser", "piper", "none"}
VOICE_STYLES = {"warm", "balanced", "clear"}
NON_SPEECH_MARKER_PATTERN = re.compile(
    r"^\s*[\[(<]?\s*(music|applause|laughter|silence|noise|inaudible|background noise)\s*[\])>]?\s*$",
    flags=re.IGNORECASE,
)
NOISE_TOKEN_PATTERN = re.compile(
    r"\s*[\[(<]\s*(music|applause|laughter|silence|noise|inaudible|background noise)\s*[\])>]\s*",
    flags=re.IGNORECASE,
)
WHISPER_SPECIAL_TOKEN_PATTERN = re.compile(r"<\|[^|>]+\|>")
MAX_TRANSCRIPT_CHARS = 4000


@dataclass(frozen=True)
class VoiceRuntimeConfig:
    stt_engine: str
    stt_command: str
    stt_model: str
    stt_language: str
    whisper_cpp_command: str
    whisper_cpp_model_path: str
    tts_engine: str
    tts_command: str
    tts_model_path: str
    voice_style: str
    voice_rate: int
    chunk_chars: int


def voice_config_from_settings(settings: dict[str, Any]) -> VoiceRuntimeConfig:
    payload = settings if isinstance(settings, dict) else {}
    stt_engine = str(payload.get("voice_stt_engine", "none")).strip().lower()
    if stt_engine not in STT_ENGINES:
        stt_engine = "none"

    tts_engine = str(payload.get("voice_tts_engine", "browser")).strip().lower()
    if tts_engine not in TTS_ENGINES:
        tts_engine = "browser"

    voice_style = str(payload.get("voice_style", "warm")).strip().lower()
    if voice_style not in VOICE_STYLES:
        voice_style = "warm"

    return VoiceRuntimeConfig(
        stt_engine=stt_engine,
        stt_command=_safe_command_name(payload.get("voice_stt_command", "whisper"), default="whisper"),
        stt_model=str(payload.get("voice_stt_model", "base")).strip() or "base",
        stt_language=_sanitize_language(payload.get("voice_stt_language", "en")),
        whisper_cpp_command=_safe_command_name(
            payload.get("voice_whisper_cpp_command", "whisper-cli"),
            default="whisper-cli",
        ),
        whisper_cpp_model_path=str(payload.get("voice_whisper_cpp_model_path", "")).strip(),
        tts_engine=tts_engine,
        tts_command=_safe_command_name(payload.get("voice_tts_command", "piper"), default="piper"),
        tts_model_path=str(payload.get("voice_tts_model_path", "")).strip(),
        voice_style=voice_style,
        voice_rate=_clamp_int(payload.get("voice_rate", 100), low=60, high=180, default=100),
        chunk_chars=_clamp_int(payload.get("voice_chunk_chars", 180), low=80, high=400, default=180),
    )


def split_response_text(text: str, *, max_chars: int = 180) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    limit = max(80, min(int(max_chars or 180), 400))
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: list[str] = []
    current = ""
    for part in parts:
        piece = str(part).strip()
        if not piece:
            continue
        if len(piece) > limit:
            words = piece.split()
            segment = ""
            for word in words:
                candidate = f"{segment} {word}".strip()
                if segment and len(candidate) > limit:
                    chunks.append(segment)
                    segment = word
                else:
                    segment = candidate
            if segment:
                if current and len(f"{current} {segment}".strip()) <= limit:
                    current = f"{current} {segment}".strip()
                else:
                    if current:
                        chunks.append(current)
                    current = segment
            continue
        candidate = f"{current} {piece}".strip() if current else piece
        if current and len(candidate) > limit:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [cleaned]


def transcribe_audio_bytes(
    audio_bytes: bytes,
    *,
    mime_type: str,
    config: VoiceRuntimeConfig,
) -> dict[str, Any]:
    raw = bytes(audio_bytes or b"")
    if not raw:
        raise ValueError("Audio payload is empty.")
    if len(raw) > MAX_AUDIO_BYTES:
        raise ValueError(f"Audio payload exceeds max size ({MAX_AUDIO_BYTES} bytes).")

    if config.stt_engine == "none":
        raise ValueError(
            "Voice STT is disabled. In Settings, choose a local STT engine (whisper_cli or whisper_cpp)."
        )

    normalized_mime = str(mime_type or "audio/webm").split(";", 1)[0].strip().lower() or "audio/webm"
    suffix = MIME_EXTENSION_MAP.get(normalized_mime, ".webm")

    with tempfile.TemporaryDirectory(prefix="david_stt_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        input_path = tmp_root / f"voice_input{suffix}"
        input_path.write_bytes(raw)

        if config.stt_engine == "whisper_cpp":
            transcript = _run_whisper_cpp(input_path, tmp_root=tmp_root, config=config)
        else:
            transcript = _run_whisper_cli(input_path, tmp_root=tmp_root, config=config)
    transcript = normalize_transcript_text(transcript)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS].strip()
    if not transcript or not re.search(r"[A-Za-z0-9]", transcript):
        raise ValueError("Speech recognition did not detect clear spoken words.")

    return {
        "text": transcript,
        "engine": config.stt_engine,
        "model": config.stt_model,
        "mime_type": normalized_mime,
        "bytes": len(raw),
    }


def synthesize_text_chunk(
    text: str,
    *,
    config: VoiceRuntimeConfig,
    voice_style: str,
    speech_rate: int,
) -> dict[str, Any]:
    chunk = str(text or "").strip()
    if not chunk:
        return {
            "engine": config.tts_engine,
            "mime_type": "",
            "audio_base64": "",
            "style": voice_style,
            "rate": speech_rate,
        }

    if config.tts_engine != "piper":
        return {
            "engine": config.tts_engine,
            "mime_type": "",
            "audio_base64": "",
            "style": voice_style,
            "rate": speech_rate,
        }

    audio_bytes = _run_piper(chunk, config=config, speech_rate=speech_rate)
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    return {
        "engine": "piper",
        "mime_type": "audio/wav",
        "audio_base64": encoded,
        "style": voice_style,
        "rate": speech_rate,
    }


def _run_whisper_cli(input_path: Path, *, tmp_root: Path, config: VoiceRuntimeConfig) -> str:
    cmd = [
        config.stt_command,
        str(input_path),
        "--model",
        config.stt_model,
        "--output_format",
        "txt",
        "--output_dir",
        str(tmp_root),
        "--fp16",
        "False",
        "--verbose",
        "False",
    ]
    if config.stt_language:
        cmd.extend(["--language", config.stt_language])

    result = _run_local_command(cmd, timeout_sec=240)
    if result.returncode != 0:
        raise ValueError(
            "Local Whisper CLI transcription failed. "
            f"stderr: {str(result.stderr or '').strip() or 'n/a'}"
        )

    transcript_file = tmp_root / f"{input_path.stem}.txt"
    if transcript_file.exists():
        transcript = transcript_file.read_text(encoding="utf-8", errors="ignore").strip()
    else:
        transcript = str(result.stdout or "").strip()
    if not transcript:
        raise ValueError("Whisper CLI returned no transcript text.")
    return transcript


def _run_whisper_cpp(input_path: Path, *, tmp_root: Path, config: VoiceRuntimeConfig) -> str:
    model_path = Path(config.whisper_cpp_model_path).expanduser().resolve()
    if not config.whisper_cpp_model_path:
        raise ValueError(
            "whisper_cpp model path is missing. Set `voice_whisper_cpp_model_path` in Settings."
        )
    if not model_path.exists() or not model_path.is_file():
        raise ValueError(f"whisper_cpp model not found: {model_path}")

    source_path = input_path
    if input_path.suffix.lower() != ".wav":
        source_path = _convert_audio_to_wav(input_path, tmp_root=tmp_root)

    output_prefix = tmp_root / "whisper_cpp_output"
    cmd = [
        config.whisper_cpp_command,
        "-m",
        str(model_path),
        "-f",
        str(source_path),
        "-otxt",
        "-of",
        str(output_prefix),
    ]
    if config.stt_language:
        cmd.extend(["-l", config.stt_language])

    result = _run_local_command(cmd, timeout_sec=240)
    if result.returncode != 0:
        raise ValueError(
            "whisper.cpp transcription failed. "
            f"stderr: {str(result.stderr or '').strip() or 'n/a'}"
        )

    transcript_file = Path(f"{output_prefix}.txt")
    if not transcript_file.exists():
        raise ValueError("whisper.cpp did not produce transcript output.")
    transcript = transcript_file.read_text(encoding="utf-8", errors="ignore").strip()
    if not transcript:
        raise ValueError("whisper.cpp returned no transcript text.")
    return transcript


def _run_piper(text: str, *, config: VoiceRuntimeConfig, speech_rate: int) -> bytes:
    model_path = Path(config.tts_model_path).expanduser().resolve()
    if not config.tts_model_path:
        raise ValueError("Piper model path is missing. Set `voice_tts_model_path` in Settings.")
    if not model_path.exists() or not model_path.is_file():
        raise ValueError(f"Piper model not found: {model_path}")

    rate = _clamp_int(speech_rate, low=60, high=180, default=config.voice_rate)
    length_scale = max(0.5, min(2.0, round(100.0 / float(rate), 3)))

    with tempfile.TemporaryDirectory(prefix="david_tts_") as tmp_dir:
        output_path = Path(tmp_dir) / "tts.wav"
        cmd = [
            config.tts_command,
            "--model",
            str(model_path),
            "--output_file",
            str(output_path),
            "--length_scale",
            f"{length_scale:.3f}",
        ]
        result = _run_local_command(cmd, timeout_sec=180, input_bytes=(text.strip() + "\n").encode("utf-8"))
        if result.returncode != 0:
            raise ValueError(
                "Local Piper synthesis failed. "
                f"stderr: {str(result.stderr or '').strip() or 'n/a'}"
            )
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise ValueError("Piper did not generate an audio file.")
        return output_path.read_bytes()


def _convert_audio_to_wav(input_path: Path, *, tmp_root: Path) -> Path:
    output_path = tmp_root / "voice_input.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]
    result = _run_local_command(cmd, timeout_sec=120)
    if result.returncode != 0 or not output_path.exists():
        raise ValueError(
            "ffmpeg conversion to wav failed. Install ffmpeg or provide wav input for whisper_cpp."
        )
    return output_path


def _run_local_command(
    cmd: list[str],
    *,
    timeout_sec: int,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[Any]:
    if not cmd:
        raise ValueError("No command provided.")
    command_name = _safe_command_name(cmd[0], default="")
    if not command_name:
        raise ValueError("Command name is invalid.")
    safe_cmd = [command_name, *[str(part) for part in cmd[1:]]]

    try:
        return subprocess.run(
            safe_cmd,
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=max(1, int(timeout_sec)),
        )
    except FileNotFoundError as exc:
        raise ValueError(f"Local command not found: {command_name}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Local command timed out: {command_name}") from exc


def _safe_command_name(value: Any, *, default: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        clean = str(default or "").strip()
    if not clean:
        return ""
    if SAFE_COMMAND_PATTERN.match(clean):
        return clean
    fallback = str(default or "").strip()
    if fallback and SAFE_COMMAND_PATTERN.match(fallback):
        return fallback
    return ""


def _sanitize_language(value: Any) -> str:
    clean = re.sub(r"[^a-zA-Z-]", "", str(value or "").strip())
    if not clean:
        return ""
    return clean[:12].lower()


def _clamp_int(value: Any, *, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def normalize_transcript_text(raw_text: Any) -> str:
    text = str(raw_text or "")
    if not text:
        return ""

    lines = []
    for line in text.splitlines():
        clean_line = str(line).strip()
        if not clean_line:
            continue
        if NON_SPEECH_MARKER_PATTERN.match(clean_line):
            continue
        lines.append(clean_line)

    merged = " ".join(lines).strip()
    if not merged:
        return ""

    merged = WHISPER_SPECIAL_TOKEN_PATTERN.sub(" ", merged)
    merged = NOISE_TOKEN_PATTERN.sub(" ", merged)
    merged = re.sub(r"\s+", " ", merged).strip()
    return merged
