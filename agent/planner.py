from __future__ import annotations

from agent.contracts import ContractError, PlanOutput, PlanStep
from agent.json_utils import JsonParseError, parse_json_object
from agent.llm import OllamaClient
from agent.prompts import PLANNER_SYSTEM_PROMPT


class Planner:
    """Builds a structured implementation plan for the active goal."""

    def __init__(self, llm: OllamaClient) -> None:
        self._llm = llm

    def create_plan(self, goal: str, workspace_snapshot: str, memory_context: str) -> PlanOutput:
        user_prompt = f"""
User goal:
{goal}

Current workspace snapshot:
{workspace_snapshot}

Relevant lessons from memory:
{memory_context}
""".strip()

        try:
            raw = self._llm.chat(PLANNER_SYSTEM_PROMPT, user_prompt)
            data = parse_json_object(raw)
            return PlanOutput.from_dict(data)
        except (JsonParseError, ContractError):
            return self._fallback_plan(goal)

    @staticmethod
    def _fallback_plan(goal: str) -> PlanOutput:
        """Guaranteed-safe fallback when the model emits invalid JSON."""

        return PlanOutput(
            goal=goal,
            steps=[
                PlanStep(
                    id="S1",
                    title="Understand the task",
                    details="Identify files to create/update in workspace and constraints.",
                    success_check="A concrete file/change list exists.",
                ),
                PlanStep(
                    id="S2",
                    title="Implement focused changes",
                    details="Write or adjust the minimum code needed for the goal.",
                    success_check="Files are updated without violating safety rules.",
                ),
                PlanStep(
                    id="S3",
                    title="Run verification",
                    details="Execute allowed tests/commands to validate behavior.",
                    success_check="All selected commands exit with code 0.",
                ),
                PlanStep(
                    id="S4",
                    title="Reflect and finalize",
                    details="Capture lessons and confirm success criteria are met.",
                    success_check="Lessons are written and final output is coherent.",
                ),
            ],
            success_criteria=[
                "Requested behavior is implemented in workspace files.",
                "Validation commands run without errors.",
                "At least one lesson is persisted to long-term memory.",
            ],
        )
