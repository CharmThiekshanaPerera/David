from __future__ import annotations

import json

from agent.contracts import CodeEdit, CoderOutput, ContractError
from agent.json_utils import JsonParseError, parse_json_object
from agent.llm import OllamaClient
from agent.prompts import CODER_SYSTEM_PROMPT


class Coder:
    """Proposes concrete file edits and verification commands."""

    def __init__(self, llm: OllamaClient) -> None:
        self._llm = llm

    def propose(
        self,
        goal: str,
        plan_json: dict,
        workspace_snapshot: str,
        memory_context: str,
        critic_feedback: str,
        iteration: int,
    ) -> CoderOutput:
        user_prompt = f"""
Iteration: {iteration}
Goal:
{goal}

Plan (JSON):
{json.dumps(plan_json, indent=2)}

Workspace snapshot:
{workspace_snapshot}

Memory context:
{memory_context}

Critic feedback from previous iteration:
{critic_feedback}
""".strip()

        try:
            raw = self._llm.chat(CODER_SYSTEM_PROMPT, user_prompt)
            data = parse_json_object(raw)
            return CoderOutput.from_dict(data)
        except (JsonParseError, ContractError):
            return CoderOutput(
                summary="Model response was invalid JSON; no file edits proposed.",
                edits=[],
                commands=["pytest -q"],
                done=False,
                done_reason="",
            )

    @staticmethod
    def render_edit_preview(edits: list[CodeEdit]) -> str:
        if not edits:
            return "No edits proposed."
        lines: list[str] = []
        for edit in edits:
            lines.append(f"- {edit.path}: {edit.reason}")
        return "\n".join(lines)
