from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._:/+-]{1,160}$")


@dataclass(frozen=True)
class AgentConfig:
    """Runtime configuration for David."""

    project_root: Path
    workspace_dir: Path
    memory_file: Path
    logs_dir: Path
    model: str
    planner_model: str
    coder_model: str
    critic_model: str
    ollama_url: str
    tdd_mode: bool
    max_iterations: int
    command_timeout_sec: int
    max_file_write_bytes: int
    max_total_write_bytes: int
    max_command_output_chars: int
    temperature: float
    allowed_commands: tuple[str, ...]
    plan_quality_threshold: int = 0
    git_auto_commit: bool = False


def sanitize_model_name(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")
    if not MODEL_NAME_PATTERN.match(cleaned):
        raise ValueError(
            f"{field_name} contains invalid characters. "
            "Allowed: letters, numbers, ., _, :, /, +, -"
        )
    return cleaned


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


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value. Got: {raw!r}")


def load_config() -> AgentConfig:
    """Load configuration from .env and environment variables."""

    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    model = sanitize_model_name(os.getenv("DAVID_MODEL", "qwen2.5-coder:1.5b"), "DAVID_MODEL")
    planner_model = sanitize_model_name(os.getenv("PLANNER_MODEL", model), "PLANNER_MODEL")
    coder_model = sanitize_model_name(os.getenv("CODER_MODEL", model), "CODER_MODEL")
    critic_model = sanitize_model_name(os.getenv("CRITIC_MODEL", model), "CRITIC_MODEL")

    ollama_url = _validate_ollama_url(os.getenv("DAVID_OLLAMA_URL", DEFAULT_OLLAMA_URL).strip())

    workspace_dir = (project_root / os.getenv("DAVID_WORKSPACE_DIR", "workspace")).resolve()
    memory_dir = (project_root / os.getenv("DAVID_MEMORY_DIR", "memory")).resolve()
    logs_dir = (project_root / os.getenv("DAVID_LOGS_DIR", "logs")).resolve()
    memory_file = (memory_dir / os.getenv("DAVID_MEMORY_FILE", "long_term.json")).resolve()

    workspace_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    if not memory_file.exists():
        memory_file.write_text('{"facts": [], "lessons": [], "preferences": []}\n', encoding="utf-8")

    return AgentConfig(
        project_root=project_root,
        workspace_dir=workspace_dir,
        memory_file=memory_file,
        logs_dir=logs_dir,
        model=model,
        planner_model=planner_model,
        coder_model=coder_model,
        critic_model=critic_model,
        ollama_url=ollama_url,
        tdd_mode=_parse_bool("TDD_MODE", default=False),
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
        plan_quality_threshold=_parse_int("DAVID_PLAN_QUALITY_THRESHOLD", default=0, minimum=0, maximum=100),
        git_auto_commit=_parse_bool("DAVID_GIT_AUTO_COMMIT", default=False),
    )
