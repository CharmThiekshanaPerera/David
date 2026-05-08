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


def _coerce_float(value: Any, field: str, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field} must be numeric.") from exc


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


@dataclass(frozen=True)
class VisionDetection:
    label: str
    confidence: float
    bbox: dict[str, int]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "VisionDetection":
        src = _require_dict(data, "vision_detection")
        label = _require_str(src.get("label"), "vision_detection.label")
        confidence = max(0.0, min(1.0, _coerce_float(src.get("confidence", 0.0), "vision_detection.confidence", 0.0)))
        bbox_src = src.get("bbox", {})
        bbox_dict = _require_dict(bbox_src, "vision_detection.bbox")
        bbox: dict[str, int] = {}
        for key in ("x1", "y1", "x2", "y2"):
            try:
                bbox[key] = int(bbox_dict.get(key, 0))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"vision_detection.bbox.{key} must be an integer.") from exc
        return VisionDetection(
            label=label,
            confidence=round(confidence, 4),
            bbox=bbox,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisionMotion:
    detected: bool
    sustained: bool
    ratio: float
    regions: list[dict[str, Any]]
    method: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "VisionMotion":
        src = _require_dict(data, "vision_motion")
        detected = bool(src.get("detected", False))
        sustained = bool(src.get("sustained", False))
        ratio = max(0.0, _coerce_float(src.get("ratio", 0.0), "vision_motion.ratio", 0.0))
        method = str(src.get("method", "")).strip() or "unknown"
        regions_raw = src.get("regions", [])
        if not isinstance(regions_raw, list):
            raise ContractError("vision_motion.regions must be a list.")
        regions = [dict(item) for item in regions_raw if isinstance(item, dict)]
        return VisionMotion(
            detected=detected,
            sustained=sustained,
            ratio=round(ratio, 5),
            regions=regions,
            method=method,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisionContextEvent:
    timestamp_utc: str
    frame_id: str
    detections: list[VisionDetection]
    motion: VisionMotion
    detector_source: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "VisionContextEvent":
        src = _require_dict(data, "vision_event")
        timestamp_utc = _require_str(src.get("timestamp_utc"), "vision_event.timestamp_utc")
        frame_id = _require_str(src.get("frame_id"), "vision_event.frame_id")
        detections_raw = src.get("detections", [])
        if not isinstance(detections_raw, list):
            raise ContractError("vision_event.detections must be a list.")
        detections = [VisionDetection.from_dict(item) for item in detections_raw]
        motion = VisionMotion.from_dict(src.get("motion", {}))
        detector_source = str(src.get("detector_source", "")).strip() or "none"
        return VisionContextEvent(
            timestamp_utc=timestamp_utc,
            frame_id=frame_id,
            detections=detections,
            motion=motion,
            detector_source=detector_source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "frame_id": self.frame_id,
            "detections": [item.to_dict() for item in self.detections],
            "motion": self.motion.to_dict(),
            "detector_source": self.detector_source,
        }


@dataclass(frozen=True)
class VisionContext:
    session_id: str
    active: bool
    planner_context: str
    summary: dict[str, Any]
    events: list[VisionContextEvent]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "VisionContext":
        src = _require_dict(data, "vision_context")
        session_id = str(src.get("session_id", "")).strip()
        active = bool(src.get("active", False))
        planner_context = str(src.get("planner_context", "")).strip()
        summary_raw = src.get("summary", {})
        summary = _require_dict(summary_raw, "vision_context.summary")
        events_raw = src.get("events", [])
        if not isinstance(events_raw, list):
            raise ContractError("vision_context.events must be a list.")
        events = [VisionContextEvent.from_dict(item) for item in events_raw]
        return VisionContext(
            session_id=session_id,
            active=active,
            planner_context=planner_context,
            summary=summary,
            events=events,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active": self.active,
            "planner_context": self.planner_context,
            "summary": dict(self.summary),
            "events": [item.to_dict() for item in self.events],
        }
