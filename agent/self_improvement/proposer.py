"""LLM-based improvement proposer for David's self-improvement system.

Given a WeaknessSignal, reads the target module and asks the local LLM
to propose a minimal, targeted improvement. Returns a full replacement
file as an ImprovementProposal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent.llm import OllamaClient
from agent.self_improvement.analyzer import WeaknessSignal


# Paths that can never be proposed for improvement — immutable safety boundary
BLOCKED_PATHS: frozenset[str] = frozenset({
    "agent/safety.py",
    "web/safety.py",
    "agent/executor.py",
    "agent/config.py",
    "agent/self_improvement/analyzer.py",
    "agent/self_improvement/proposer.py",
    "agent/self_improvement/stager.py",
    "agent/self_improvement/version_manager.py",
})

_MAX_SOURCE_CHARS = 12_000  # truncate very large source files before sending to LLM

_PROPOSER_SYSTEM_PROMPT = """
You are David's Self-Improvement Proposer.
You receive a weakness signal derived from David's run telemetry and the current source of a specific Python module.
Your job is to propose a minimal, targeted improvement to that module.

Return ONLY a valid JSON object with exactly this schema:
{
  "reasoning": "one short paragraph explaining what you changed and why it addresses the weakness",
  "content": "the COMPLETE improved Python file content, ready to write to disk"
}

Rules:
- The returned content must be the COMPLETE file — include all original imports, functions, and classes.
- Make only minimal targeted changes relevant to the weakness signal. Do not rewrite unrelated parts.
- Do not change any public function or method signatures that other modules depend on.
- Do not remove or weaken any existing safety checks, path validations, or allow-list enforcement.
- Do not add new external library imports (only use the standard library and imports already present).
- The content must be valid Python that passes ast.parse().
- No markdown. No code fences. No explanations outside the JSON object.
""".strip()


@dataclass(frozen=True)
class ImprovementProposal:
    """A validated, LLM-generated improvement ready for staging."""

    target_path: str        # relative path from project root, e.g. "agent/planner.py"
    original_content: str
    proposed_content: str
    reasoning: str
    signal: WeaknessSignal


class ImprovementProposer:
    """Uses the local LLM (critic model) to propose an improved module version."""

    def __init__(self, llm: OllamaClient, project_root: Path) -> None:
        self._llm = llm
        self._project_root = project_root

    def propose(self, signal: WeaknessSignal) -> ImprovementProposal | None:
        """
        Generate an improvement proposal for the given weakness signal.
        Returns None if the path is blocked, the file does not exist,
        the LLM call fails, or the output is identical to the original.
        """
        normalized = signal.module_path.replace("\\", "/").strip()

        if normalized in BLOCKED_PATHS:
            return None

        target_file = (self._project_root / normalized).resolve()
        if not target_file.exists() or not target_file.is_file():
            return None

        try:
            original = target_file.read_text(encoding="utf-8")
        except OSError:
            return None

        source_snippet = original if len(original) <= _MAX_SOURCE_CHARS else (
            original[:_MAX_SOURCE_CHARS] + "\n# ... [truncated for length] ..."
        )

        user_prompt = (
            f"Weakness signal detected in David's telemetry:\n"
            f"  Module:     {normalized}\n"
            f"  Signal:     {signal.signal_code}\n"
            f"  Severity:   {signal.severity}/100\n"
            f"  Evidence:   {signal.evidence}\n\n"
            f"Current content of {normalized}:\n"
            f"{source_snippet}"
        )

        try:
            raw = self._llm.chat(
                system_prompt=_PROPOSER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self._llm.config.critic_model,
            )
        except Exception:
            return None

        parsed = self._parse_response(raw)
        if parsed is None:
            return None

        reasoning, proposed_content = parsed

        if not proposed_content.strip():
            return None
        if proposed_content.strip() == original.strip():
            return None  # LLM returned identical content — no improvement

        return ImprovementProposal(
            target_path=normalized,
            original_content=original,
            proposed_content=proposed_content,
            reasoning=reasoning,
            signal=signal,
        )

    @staticmethod
    def _parse_response(raw: str) -> tuple[str, str] | None:
        """Extract (reasoning, content) from the LLM JSON response."""
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end])
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        reasoning = str(data.get("reasoning", "")).strip()
        content = str(data.get("content", "")).strip()
        if not content:
            return None
        return reasoning, content
