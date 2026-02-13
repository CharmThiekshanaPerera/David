from __future__ import annotations

import json

from agent.contracts import CriticOutput, ExecutionResult, LessonProposal
from agent.contracts import ContractError
from agent.json_utils import JsonParseError, parse_json_object
from agent.llm import OllamaClient
from agent.prompts import CRITIC_SYSTEM_PROMPT


class Critic:
    """Analyzes command output and guides the next iteration."""

    def __init__(self, llm: OllamaClient) -> None:
        self._llm = llm

    def review(
        self,
        goal: str,
        plan_json: dict,
        coder_json: dict,
        execution_results: list[ExecutionResult],
    ) -> CriticOutput:
        rendered_results = json.dumps([result.to_dict() for result in execution_results], indent=2)

        user_prompt = f"""
Goal:
{goal}

Plan (JSON):
{json.dumps(plan_json, indent=2)}

Coder output (JSON):
{json.dumps(coder_json, indent=2)}

Execution results:
{rendered_results}
""".strip()

        try:
            raw = self._llm.chat(CRITIC_SYSTEM_PROMPT, user_prompt)
            data = parse_json_object(raw)
            return CriticOutput.from_dict(data)
        except (JsonParseError, ContractError):
            return self._fallback_review(execution_results)

    @staticmethod
    def _fallback_review(execution_results: list[ExecutionResult]) -> CriticOutput:
        if execution_results and all(result.returncode == 0 and not result.timed_out for result in execution_results):
            return CriticOutput(
                status="success",
                analysis="All allowed validation commands passed.",
                next_actions=["Finalize this goal and record the lesson."],
                lessons=[
                    LessonProposal(
                        lesson="Passing tests are the minimum acceptance gate before claiming success.",
                        tags=["testing", "quality"],
                    )
                ],
            )

        return CriticOutput(
            status="retry",
            analysis="One or more commands failed or timed out. Iterate with a smaller scoped fix.",
            next_actions=[
                "Inspect the first failing command output.",
                "Apply a focused code change.",
                "Re-run only required validation commands.",
            ],
            lessons=[
                LessonProposal(
                    lesson="Tight iteration loops reduce debugging complexity.",
                    tags=["debugging", "iteration"],
                )
            ],
        )
