from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from agent.config import AgentConfig, sanitize_model_name


class LLMError(RuntimeError):
    """Raised when the local model cannot be reached or returns an invalid response."""


@dataclass
class OllamaClient:
    """Thin wrapper for local-only Ollama chat calls."""

    config: AgentConfig

    def chat(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        model_name = sanitize_model_name(model or self.config.model, "model")
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": self.config.temperature},
        }

        try:
            response = requests.post(
                self.config.ollama_url,
                json=payload,
                timeout=(10, 120),
            )
        except requests.RequestException as exc:
            raise LLMError(
                "Failed to connect to local Ollama. Ensure `ollama serve` is running and "
                f"model `{model_name}` exists. Details: {exc}"
            ) from exc

        if response.status_code != 200:
            raise LLMError(
                "Ollama returned non-200 status "
                f"{response.status_code}: {response.text[:300]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Ollama response was not valid JSON.") from exc

        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMError("Ollama response missing `message` object.")

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Ollama response missing string `message.content`.")
        return content
