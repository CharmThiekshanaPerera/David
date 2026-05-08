from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.contracts import LessonProposal


@dataclass(frozen=True)
class MemoryFact:
    subject: str
    predicate: str
    object: str
    source: str
    confidence: float
    timestamp: str


@dataclass(frozen=True)
class MemoryLesson:
    timestamp_utc: str
    goal: str
    lesson: str
    tags: list[str]
    context: str


class LongTermMemory:
    """Appends and retrieves reusable lessons and explicit taught facts."""

    _SENSITIVE_PATTERNS = (
        "password",
        "passphrase",
        "api key",
        "api_key",
        "token",
        "secret",
        "private key",
        "ssh key",
        "ssn",
        "social security",
        "credit card",
        "cvv",
        "bank account",
        "otp",
    )

    def __init__(self, memory_file: Path, max_entries: int = 2_000) -> None:
        self._memory_file = memory_file
        self._max_entries = max_entries
        self._ensure_file()

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object: str,
        source: str = "user_teach",
        confidence: float = 1.0,
        timestamp: str | None = None,
    ) -> MemoryFact:
        normalized_subject = self._clean_text(subject, "subject")
        normalized_predicate = self._normalize_predicate(predicate)
        normalized_object = self._clean_text(object, "object")
        normalized_source = self._clean_text(source, "source")

        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")

        self._reject_sensitive_content(normalized_subject, normalized_predicate, normalized_object)

        payload = self._read_payload()
        raw_facts = payload.setdefault("facts", [])

        existing = self.get_fact(normalized_subject, normalized_predicate)
        if existing and existing.object.casefold() == normalized_object.casefold():
            return existing

        resolved_timestamp = timestamp or datetime.now(tz=timezone.utc).isoformat()
        fact = MemoryFact(
            subject=normalized_subject,
            predicate=normalized_predicate,
            object=normalized_object,
            source=normalized_source,
            confidence=round(confidence, 3),
            timestamp=resolved_timestamp,
        )

        raw_facts.append(asdict(fact))
        if len(raw_facts) > self._max_entries:
            payload["facts"] = raw_facts[-self._max_entries :]
        self._write_payload(payload)
        return fact

    def get_fact(self, subject: str, predicate: str) -> MemoryFact | None:
        normalized_subject = self._clean_text(subject, "subject")
        normalized_predicate = self._normalize_predicate(predicate)

        matches: list[MemoryFact] = []
        for item in self._read_facts():
            fact = self._fact_from_dict(item)
            if (
                fact.subject.casefold() == normalized_subject.casefold()
                and fact.predicate.casefold() == normalized_predicate.casefold()
            ):
                matches.append(fact)

        if not matches:
            return None
        matches.sort(key=lambda fact: fact.timestamp, reverse=True)
        return matches[0]

    def search_facts(self, query: str, limit: int = 8) -> list[MemoryFact]:
        facts = [self._fact_from_dict(item) for item in self._read_facts()]
        if not facts:
            return []

        tokens = set(self._tokenize(query))
        if not tokens:
            return facts[:limit]

        scored: list[tuple[int, MemoryFact]] = []
        for fact in facts:
            text = f"{fact.subject} {fact.predicate} {fact.object}"
            fact_tokens = set(self._tokenize(text))
            score = len(tokens & fact_tokens)
            if score > 0:
                scored.append((score, fact))

        if not scored:
            return []

        scored.sort(key=lambda item: (item[0], item[1].timestamp), reverse=True)
        return [fact for _, fact in scored[:limit]]

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

        self._write_payload(payload)

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
            self._write_payload({"facts": [], "lessons": [], "preferences": [], "values": [], "projects": []})
            return
        payload = self._read_payload()
        self._write_payload(payload)

    def _read_payload(self) -> dict:
        try:
            data = json.loads(self._memory_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        if not isinstance(data, dict):
            data = {}

        if not isinstance(data.get("facts"), list):
            data["facts"] = []
        if not isinstance(data.get("lessons"), list):
            data["lessons"] = []
        if not isinstance(data.get("preferences"), list):
            data["preferences"] = []
        if not isinstance(data.get("values"), list):
            data["values"] = []
        if not isinstance(data.get("projects"), list):
            data["projects"] = []

        return data

    def _write_payload(self, payload: dict) -> None:
        self._memory_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _read_lessons(self) -> list[dict]:
        payload = self._read_payload()
        return payload.get("lessons", [])

    def _read_facts(self) -> list[dict]:
        payload = self._read_payload()
        return payload.get("facts", [])

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
    def _fact_from_dict(data: dict) -> MemoryFact:
        try:
            confidence = float(data.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        return MemoryFact(
            subject=str(data.get("subject", "")).strip(),
            predicate=str(data.get("predicate", "")).strip(),
            object=str(data.get("object", "")).strip(),
            source=str(data.get("source", "unknown")).strip() or "unknown",
            confidence=confidence,
            timestamp=str(data.get("timestamp", "")).strip() or "unknown-time",
        )

    @staticmethod
    def _clean_text(value: str, field: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field} cannot be empty.")
        return text

    @staticmethod
    def _normalize_predicate(predicate: str) -> str:
        clean = LongTermMemory._clean_text(predicate, "predicate")
        clean = re.sub(r"\s+", "_", clean.strip().lower())
        clean = re.sub(r"[^a-z0-9_]", "", clean)
        if not clean:
            raise ValueError("predicate cannot be empty after normalization.")
        return clean

    @classmethod
    def _reject_sensitive_content(cls, subject: str, predicate: str, object_value: str) -> None:
        combined = f"{subject} {predicate} {object_value}".lower()
        for marker in cls._SENSITIVE_PATTERNS:
            if marker in combined:
                raise ValueError("Refusing to store sensitive data in long-term memory.")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        normalized = text.lower().replace("_", " ")
        return [part for part in re.findall(r"[a-zA-Z0-9]+", normalized) if len(part) > 2]
