from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class ContractError(ValueError):
    """Raised when model output does not match required JSON contract."""


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be an object.")
    return value


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string.")
    return value.strip()


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field} must be a boolean.")
    return value


def _require_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{field} must be a list.")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{field}[{index}] must be a non-empty string.")
        result.append(item.strip())
    return result


@dataclass(frozen=True)
class PlanStep:
    id: str
    title: str
    details: str
    success_check: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PlanStep":
        src = _require_dict(data, "plan_step")
        return PlanStep(
            id=_require_str(src.get("id"), "plan_step.id"),
            title=_require_str(src.get("title"), "plan_step.title"),
            details=_require_str(src.get("details"), "plan_step.details"),
            success_check=_require_str(src.get("success_check"), "plan_step.success_check"),
        )


@dataclass(frozen=True)
class PlanOutput:
    goal: str
    steps: list[PlanStep]
    success_criteria: list[str]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PlanOutput":
        src = _require_dict(data, "plan")
        goal = _require_str(src.get("goal"), "plan.goal")

        raw_steps = src.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ContractError("plan.steps must be a non-empty list.")
        steps = [PlanStep.from_dict(item) for item in raw_steps]

        success_criteria = _require_str_list(src.get("success_criteria"), "plan.success_criteria")
        if not success_criteria:
            raise ContractError("plan.success_criteria must contain at least one item.")

        return PlanOutput(goal=goal, steps=steps, success_criteria=success_criteria)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [asdict(step) for step in self.steps],
            "success_criteria": list(self.success_criteria),
        }


@dataclass(frozen=True)
class CodeEdit:
    path: str
    content: str
    reason: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CodeEdit":
        src = _require_dict(data, "code_edit")
        path = _require_str(src.get("path"), "code_edit.path")
        content = src.get("content")
        if not isinstance(content, str):
            raise ContractError("code_edit.content must be a string.")
        reason = _require_str(src.get("reason"), "code_edit.reason")
        return CodeEdit(path=path, content=content, reason=reason)


@dataclass(frozen=True)
class CoderOutput:
    summary: str
    edits: list[CodeEdit]
    commands: list[str]
    done: bool
    done_reason: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CoderOutput":
        src = _require_dict(data, "coder")
        summary = _require_str(src.get("summary"), "coder.summary")

        raw_edits = src.get("edits")
        if not isinstance(raw_edits, list):
            raise ContractError("coder.edits must be a list.")
        edits = [CodeEdit.from_dict(item) for item in raw_edits]

        commands = _require_str_list(src.get("commands"), "coder.commands")
        done = _require_bool(src.get("done"), "coder.done")

        done_reason = src.get("done_reason", "")
        if not isinstance(done_reason, str):
            raise ContractError("coder.done_reason must be a string.")

        return CoderOutput(
            summary=summary,
            edits=edits,
            commands=commands,
            done=done,
            done_reason=done_reason.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "edits": [asdict(edit) for edit in self.edits],
            "commands": list(self.commands),
            "done": self.done,
            "done_reason": self.done_reason,
        }


@dataclass(frozen=True)
class ExecutionResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_sec: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LessonProposal:
    lesson: str
    tags: list[str]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LessonProposal":
        src = _require_dict(data, "critic.lesson")
        lesson = _require_str(src.get("lesson"), "critic.lesson.lesson")
        tags = _require_str_list(src.get("tags", []), "critic.lesson.tags")
        return LessonProposal(lesson=lesson, tags=tags)


@dataclass(frozen=True)
class CriticOutput:
    status: str
    analysis: str
    next_actions: list[str]
    lessons: list[LessonProposal]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CriticOutput":
        src = _require_dict(data, "critic")
        status = _require_str(src.get("status"), "critic.status").lower()
        if status not in {"success", "retry", "abort"}:
            raise ContractError("critic.status must be one of: success, retry, abort.")

        analysis = _require_str(src.get("analysis"), "critic.analysis")
        next_actions = _require_str_list(src.get("next_actions"), "critic.next_actions")

        raw_lessons = src.get("lessons", [])
        if not isinstance(raw_lessons, list):
            raise ContractError("critic.lessons must be a list.")
        lessons = [LessonProposal.from_dict(item) for item in raw_lessons]

        return CriticOutput(
            status=status,
            analysis=analysis,
            next_actions=next_actions,
            lessons=lessons,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "analysis": self.analysis,
            "next_actions": list(self.next_actions),
            "lessons": [asdict(lesson) for lesson in self.lessons],
        }
