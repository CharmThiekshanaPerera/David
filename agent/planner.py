from __future__ import annotations

from agent.contracts import ContractError, PlanOutput, PlanStep
from agent.json_utils import JsonParseError, parse_json_object
from agent.llm import OllamaClient
from agent.prompts import PLANNER_SYSTEM_PROMPT


class Planner:
    """Builds a structured implementation plan for the active goal."""

    def __init__(self, llm: OllamaClient, model_name: str | None = None) -> None:
        self._llm = llm
        self._model_name = model_name

    def create_plan(
        self,
        goal: str,
        workspace_snapshot: str,
        memory_context: str,
        tdd_mode: bool = False,
    ) -> PlanOutput:
        tdd_line = (
            "TDD mode is enabled. Write tests first, then implementation. "
            "Plan step 1 must create tests under tests/ in the active project."
            if tdd_mode
            else "TDD mode is disabled."
        )
        user_prompt = f"""
User goal:
{goal}

Current workspace snapshot:
{workspace_snapshot}

Relevant lessons from memory:
{memory_context}

Execution mode:
{tdd_line}
""".strip()

        try:
            raw = self._llm.chat(PLANNER_SYSTEM_PROMPT, user_prompt, model=self._model_name)
            data = parse_json_object(raw)
            return PlanOutput.from_dict(data)
        except (JsonParseError, ContractError):
            return self._fallback_plan(goal, tdd_mode=tdd_mode)

    @staticmethod
    def _fallback_plan(goal: str, tdd_mode: bool = False) -> PlanOutput:
        """Guaranteed-safe fallback when the model emits invalid JSON."""

        steps: list[PlanStep] = []
        if tdd_mode:
            steps.append(
                PlanStep(
                    id="S1",
                    title="Write failing tests first",
                    details="Create tests under tests/ in the active project that describe the required behavior.",
                    success_check="Pytest executes and at least one test fails before implementation.",
                )
            )
            steps.append(
                PlanStep(
                    id="S2",
                    title="Implement minimum code",
                    details="Write focused implementation to satisfy the failing tests.",
                    success_check="Implementation files are updated without violating safety rules.",
                )
            )
            steps.append(
                PlanStep(
                    id="S3",
                    title="Run tests to green",
                    details="Run pytest and iterate until tests pass or limits are reached.",
                    success_check="All selected pytest commands exit with code 0.",
                )
            )
            steps.append(
                PlanStep(
                    id="S4",
                    title="Reflect and finalize",
                    details="Capture lessons and confirm success criteria are met.",
                    success_check="Lessons are written and final output is coherent.",
                )
            )
            criteria = [
                "Tests are created under tests/ in the active project before implementation changes.",
                "Validation commands run without errors.",
                "At least one lesson is persisted to long-term memory.",
            ]
            return PlanOutput(goal=goal, steps=steps, success_criteria=criteria)

        return PlanOutput(
            goal=goal,
            steps=[
                PlanStep(
                    id="S1",
                    title="Understand the task",
                    details="Identify files to create/update in the active project and constraints.",
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
                "Requested behavior is implemented in active project files.",
                "Validation commands run without errors.",
                "At least one lesson is persisted to long-term memory.",
            ],
        )
