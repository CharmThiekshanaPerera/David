from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


@dataclass(frozen=True)
class AgentConfig:
    """Runtime configuration for David."""

    project_root: Path
    workspace_dir: Path
    memory_file: Path
    logs_dir: Path
    model: str
    ollama_url: str
    max_iterations: int
    command_timeout_sec: int
    max_file_write_bytes: int
    max_total_write_bytes: int
    max_command_output_chars: int
    temperature: float
    allowed_commands: tuple[str, ...]


def _parse_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer. Got: {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}. Got: {value}")
    return value


def _parse_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float. Got: {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}. Got: {value}")
    return value


def _validate_ollama_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise ValueError("DAVID_OLLAMA_URL must use http:// for local Ollama access.")
    if parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("DAVID_OLLAMA_URL must point to localhost/127.0.0.1/::1 only.")
    if parsed.path.rstrip("/") != "/api/chat":
        raise ValueError("DAVID_OLLAMA_URL must end with /api/chat.")
    return url


def _parse_allowed_commands() -> tuple[str, ...]:
    raw = os.getenv("DAVID_ALLOWED_COMMANDS", "python,pytest")
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    valid_set = {"python", "pytest"}
    if not values:
        raise ValueError("DAVID_ALLOWED_COMMANDS cannot be empty.")
    invalid = [item for item in values if item not in valid_set]
    if invalid:
        raise ValueError(
            "DAVID_ALLOWED_COMMANDS may only include python and pytest. "
            f"Invalid: {', '.join(invalid)}"
        )
    return values


def load_config() -> AgentConfig:
    """Load configuration from .env and environment variables."""

    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    model = os.getenv("DAVID_MODEL", "qwen2.5-coder:1.5b").strip()
    if not model:
        raise ValueError("DAVID_MODEL cannot be empty.")

    ollama_url = _validate_ollama_url(os.getenv("DAVID_OLLAMA_URL", DEFAULT_OLLAMA_URL).strip())

    workspace_dir = (project_root / os.getenv("DAVID_WORKSPACE_DIR", "workspace")).resolve()
    memory_dir = (project_root / os.getenv("DAVID_MEMORY_DIR", "memory")).resolve()
    logs_dir = (project_root / os.getenv("DAVID_LOGS_DIR", "logs")).resolve()
    memory_file = (memory_dir / os.getenv("DAVID_MEMORY_FILE", "long_term.json")).resolve()

    workspace_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    if not memory_file.exists():
        memory_file.write_text('{"lessons": []}\n', encoding="utf-8")

    return AgentConfig(
        project_root=project_root,
        workspace_dir=workspace_dir,
        memory_file=memory_file,
        logs_dir=logs_dir,
        model=model,
        ollama_url=ollama_url,
        max_iterations=_parse_int("DAVID_MAX_ITERATIONS", default=8, minimum=1, maximum=50),
        command_timeout_sec=_parse_int("DAVID_COMMAND_TIMEOUT_SEC", default=45, minimum=1, maximum=600),
        max_file_write_bytes=_parse_int("DAVID_MAX_FILE_WRITE_BYTES", default=250_000, minimum=1_000, maximum=5_000_000),
        max_total_write_bytes=_parse_int(
            "DAVID_MAX_TOTAL_WRITE_BYTES",
            default=1_000_000,
            minimum=10_000,
            maximum=10_000_000,
        ),
        max_command_output_chars=_parse_int(
            "DAVID_MAX_COMMAND_OUTPUT_CHARS",
            default=8_000,
            minimum=500,
            maximum=200_000,
        ),
        temperature=_parse_float("DAVID_TEMPERATURE", default=0.2, minimum=0.0, maximum=1.0),
        allowed_commands=_parse_allowed_commands(),
    )
