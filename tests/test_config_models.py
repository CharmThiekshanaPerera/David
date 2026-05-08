from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.config import load_config


def _set_common_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DAVID_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("DAVID_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("DAVID_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DAVID_MEMORY_FILE", "long_term.json")
    monkeypatch.setenv("DAVID_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")


def _unset(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    if key in os.environ:
        monkeypatch.delenv(key)


def test_role_models_fallback_to_single_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_common_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DAVID_MODEL", "qwen2.5-coder:1.5b")
    _unset(monkeypatch, "PLANNER_MODEL")
    _unset(monkeypatch, "CODER_MODEL")
    _unset(monkeypatch, "CRITIC_MODEL")

    config = load_config()

    assert config.model == "qwen2.5-coder:1.5b"
    assert config.planner_model == "qwen2.5-coder:1.5b"
    assert config.coder_model == "qwen2.5-coder:1.5b"
    assert config.critic_model == "qwen2.5-coder:1.5b"


def test_role_model_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_common_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DAVID_MODEL", "qwen2.5-coder:1.5b")
    monkeypatch.setenv("PLANNER_MODEL", "llama3.2:3b")
    monkeypatch.setenv("CODER_MODEL", "qwen2.5-coder:1.5b")
    monkeypatch.setenv("CRITIC_MODEL", "deepseek-r1:7b")
    monkeypatch.setenv("TDD_MODE", "true")

    config = load_config()

    assert config.planner_model == "llama3.2:3b"
    assert config.coder_model == "qwen2.5-coder:1.5b"
    assert config.critic_model == "deepseek-r1:7b"
    assert config.tdd_mode is True


def test_invalid_role_model_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_common_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DAVID_MODEL", "qwen2.5-coder:1.5b")
    monkeypatch.setenv("PLANNER_MODEL", "bad model; rm -rf /")

    with pytest.raises(ValueError):
        load_config()
