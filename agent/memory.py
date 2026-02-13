from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.contracts import LessonProposal


@dataclass(frozen=True)
class MemoryLesson:
    timestamp_utc: str
    goal: str
    lesson: str
    tags: list[str]
    context: str


class LongTermMemory:
    """Appends and retrieves reusable lessons from previous iterations."""

    def __init__(self, memory_file: Path, max_entries: int = 2_000) -> None:
        self._memory_file = memory_file
        self._max_entries = max_entries
        self._ensure_file()

    def relevant_lessons(self, goal: str, limit: int = 8) -> list[MemoryLesson]:
        items = self._read_lessons()
        if not items:
            return []

        goal_terms = set(self._tokenize(goal))
        scored: list[tuple[int, MemoryLesson]] = []

        for item in items:
            lesson = self._lesson_from_dict(item)
            text_terms = set(self._tokenize(f"{lesson.lesson} {' '.join(lesson.tags)} {lesson.context}"))
            score = len(goal_terms & text_terms)
            if score > 0:
                scored.append((score, lesson))

        if not scored:
            recent = [self._lesson_from_dict(item) for item in items[-limit:]]
            return list(reversed(recent))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [lesson for _, lesson in scored[:limit]]

    def append_lessons(self, goal: str, lessons: list[LessonProposal], context: str) -> None:
        if not lessons:
            return

        payload = self._read_payload()
        raw_lessons = payload.setdefault("lessons", [])
        now = datetime.now(tz=timezone.utc).isoformat()

        for lesson in lessons:
            raw_lessons.append(
                asdict(
                    MemoryLesson(
                        timestamp_utc=now,
                        goal=goal,
                        lesson=lesson.lesson,
                        tags=lesson.tags,
                        context=context,
                    )
                )
            )

        if len(raw_lessons) > self._max_entries:
            payload["lessons"] = raw_lessons[-self._max_entries :]

        self._memory_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def render_context(self, goal: str, limit: int = 8) -> str:
        lessons = self.relevant_lessons(goal, limit=limit)
        if not lessons:
            return "No prior lessons available."

        lines: list[str] = []
        for item in lessons:
            tags = ", ".join(item.tags) if item.tags else "untagged"
            lines.append(f"- [{item.timestamp_utc}] ({tags}) {item.lesson}")
        return "\n".join(lines)

    def _ensure_file(self) -> None:
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._memory_file.exists():
            self._memory_file.write_text('{"lessons": []}\n', encoding="utf-8")

    def _read_payload(self) -> dict:
        try:
            data = json.loads(self._memory_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"lessons": []}
        if not isinstance(data, dict):
            data = {"lessons": []}
        if not isinstance(data.get("lessons"), list):
            data["lessons"] = []
        return data

    def _read_lessons(self) -> list[dict]:
        payload = self._read_payload()
        return payload.get("lessons", [])

    @staticmethod
    def _lesson_from_dict(data: dict) -> MemoryLesson:
        timestamp = str(data.get("timestamp_utc", "")).strip() or "unknown-time"
        goal = str(data.get("goal", "")).strip()
        lesson = str(data.get("lesson", "")).strip()
        context = str(data.get("context", "")).strip()

        raw_tags = data.get("tags", [])
        tags: list[str] = []
        if isinstance(raw_tags, list):
            for item in raw_tags:
                if isinstance(item, str) and item.strip():
                    tags.append(item.strip())

        return MemoryLesson(
            timestamp_utc=timestamp,
            goal=goal,
            lesson=lesson,
            tags=tags,
            context=context,
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [part for part in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(part) > 2]
