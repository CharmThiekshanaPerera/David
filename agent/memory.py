from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    outcome: str = "unknown"          # "success" | "failure" | "unknown"
    reinforcement_count: int = 0      # incremented each time this lesson preceded a success


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
        scored: list[tuple[float, MemoryLesson]] = []

        for item in items:
            lesson = self._lesson_from_dict(item)

            # Tags score 2x — they are curated signals
            tag_terms = set(self._tokenize(" ".join(lesson.tags)))
            body_terms = set(self._tokenize(f"{lesson.lesson} {lesson.context}"))
            tag_score = len(goal_terms & tag_terms) * 2.0
            body_score = len(goal_terms & body_terms) * 1.0
            base = tag_score + body_score

            if base == 0:
                continue

            # Recency boost: lessons < 7 days old get +1.0
            age_days = self._lesson_age_days(lesson.timestamp_utc)
            recency_bonus = 1.0 if age_days <= 7 else 0.0

            # Outcome weight: successful lessons rank higher, failures lower
            outcome_weight = {"success": 1.2, "failure": 0.8}.get(lesson.outcome, 1.0)

            # Reinforcement bonus capped at +0.5 (each success adds 0.1)
            reinf_bonus = min(0.5, lesson.reinforcement_count * 0.1)

            composite = (base + recency_bonus + reinf_bonus) * outcome_weight
            scored.append((composite, lesson))

        if not scored:
            recent = [self._lesson_from_dict(item) for item in items[-limit:]]
            return list(reversed(recent))

        scored.sort(key=lambda pair: (pair[0], pair[1].timestamp_utc), reverse=True)
        return [lesson for _, lesson in scored[:limit]]

    def append_lessons(
        self,
        goal: str,
        lessons: list[LessonProposal],
        context: str,
        outcome: str = "unknown",
    ) -> None:
        if not lessons:
            return

        payload = self._read_payload()
        raw_lessons = payload.setdefault("lessons", [])
        now = datetime.now(tz=timezone.utc).isoformat()
        safe_outcome = outcome if outcome in ("success", "failure", "unknown") else "unknown"

        for lesson in lessons:
            raw_lessons.append(
                asdict(
                    MemoryLesson(
                        timestamp_utc=now,
                        goal=goal,
                        lesson=lesson.lesson,
                        tags=lesson.tags,
                        context=context,
                        outcome=safe_outcome,
                        reinforcement_count=0,
                    )
                )
            )

        if len(raw_lessons) > self._max_entries:
            payload["lessons"] = raw_lessons[-self._max_entries :]

        self._write_payload(payload)

    def reinforce_lessons(self, goal: str, outcome: str, since_iso: str = "") -> int:
        """Update outcome and reinforcement_count for lessons from this run.

        Matches lessons by goal string and optional since_iso lower-bound timestamp.
        Returns the number of lessons updated.
        """
        safe_outcome = outcome if outcome in ("success", "failure") else "unknown"
        payload = self._read_payload()
        raw_lessons = payload.get("lessons", [])
        updated = 0

        for item in raw_lessons:
            if not isinstance(item, dict):
                continue
            if str(item.get("goal", "")) != goal:
                continue
            ts = str(item.get("timestamp_utc", ""))
            if since_iso and ts < since_iso:
                continue
            # Set outcome if still unknown
            if item.get("outcome", "unknown") == "unknown":
                item["outcome"] = safe_outcome
            # Increment reinforcement on success
            if safe_outcome == "success":
                item["reinforcement_count"] = int(item.get("reinforcement_count", 0)) + 1
            updated += 1

        if updated:
            payload["lessons"] = raw_lessons
            self._write_payload(payload)
        return updated

    def render_context(self, goal: str, limit: int = 8) -> str:
        text, _ = self.render_context_and_meta(goal, limit=limit)
        return text

    def render_context_and_meta(
        self, goal: str, limit: int = 8
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return (formatted context string, list of lesson metadata dicts).

        The metadata list enables memory-influence telemetry in the agent loop.
        """
        lessons = self.relevant_lessons(goal, limit=limit)
        lines: list[str] = []
        meta: list[dict[str, Any]] = []

        if lessons:
            for item in lessons:
                tags = ", ".join(item.tags) if item.tags else "untagged"
                outcome_tag = f" [{item.outcome}]" if item.outcome != "unknown" else ""
                reinf = f" (reinforced×{item.reinforcement_count})" if item.reinforcement_count > 0 else ""
                lines.append(f"- [{item.timestamp_utc}] ({tags}){outcome_tag}{reinf} {item.lesson}")
                meta.append(
                    {
                        "timestamp_utc": item.timestamp_utc,
                        "tags": list(item.tags),
                        "outcome": item.outcome,
                        "reinforcement_count": item.reinforcement_count,
                        "lesson_preview": item.lesson[:80],
                    }
                )
        else:
            lines.append("No prior lessons available.")

        # Append session hints from the current run (short-lived, not persisted long-term)
        hints = self.get_session_hints(goal)
        if hints:
            lines.append("\nSession hints from current run:")
            for h in hints:
                lines.append(f"  • {h}")

        return "\n".join(lines), meta

    # ------------------------------------------------------------------
    # Session hints — cleared at the start of each run, not persisted
    # long-term. Used to propagate within-run tactical knowledge between
    # iterations (safety rejections, TDD violations, etc.).
    # ------------------------------------------------------------------

    def append_session_hint(
        self, goal: str, hint: str, tags: list[str] | None = None
    ) -> None:
        hint = str(hint or "").strip()
        if not hint:
            return
        payload = self._read_payload()
        hints = payload.setdefault("session_hints", [])
        hints.append(
            {
                "goal": goal,
                "hint": hint,
                "tags": tags or [],
                "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        self._write_payload(payload)

    def clear_session_hints(self) -> None:
        payload = self._read_payload()
        payload["session_hints"] = []
        self._write_payload(payload)

    def get_session_hints(self, goal: str) -> list[str]:
        payload = self._read_payload()
        raw = payload.get("session_hints", [])
        result: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            item_goal = str(item.get("goal", ""))
            if item_goal in (goal, ""):
                h = str(item.get("hint", "")).strip()
                if h:
                    result.append(h)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def add_web_research(
        self,
        url: str,
        summary: str,
        goal: str,
        timestamp: str | None = None,
    ) -> None:
        """Store a summarized web research entry linked to a goal."""
        url = str(url).strip()
        summary = str(summary).strip()
        goal = str(goal).strip()
        if not url or not summary:
            return
        payload = self._read_payload()
        entries = payload.setdefault("web_research", [])
        entries.append(
            {
                "url": url,
                "summary": summary,
                "goal": goal,
                "timestamp": timestamp or datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        if len(entries) > self._max_entries:
            payload["web_research"] = entries[-self._max_entries :]
        self._write_payload(payload)

    def recent_web_research(self, goal: str, limit: int = 5) -> list[dict]:
        """Return recent web research entries relevant to the given goal."""
        payload = self._read_payload()
        entries = payload.get("web_research", [])
        if not entries:
            return []

        goal_tokens = set(self._tokenize(goal))
        scored: list[tuple[int, dict]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_goal = str(entry.get("goal", ""))
            summary = str(entry.get("summary", ""))
            text = f"{entry_goal} {summary}"
            entry_tokens = set(self._tokenize(text))
            score = len(goal_tokens & entry_tokens) if goal_tokens else 0
            if score > 0 or entry_goal == goal:
                scored.append((score, entry))

        if not scored:
            return [e for e in entries[-limit:] if isinstance(e, dict)]

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def _ensure_file(self) -> None:
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._memory_file.exists():
            self._write_payload(
                {
                    "facts": [],
                    "lessons": [],
                    "preferences": [],
                    "values": [],
                    "projects": [],
                    "session_hints": [],
                    "web_research": [],
                }
            )
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
        if not isinstance(data.get("session_hints"), list):
            data["session_hints"] = []
        if not isinstance(data.get("web_research"), list):
            data["web_research"] = []

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

        outcome = str(data.get("outcome", "unknown")).strip()
        if outcome not in ("success", "failure", "unknown"):
            outcome = "unknown"

        try:
            reinforcement_count = int(data.get("reinforcement_count", 0))
        except (TypeError, ValueError):
            reinforcement_count = 0

        return MemoryLesson(
            timestamp_utc=timestamp,
            goal=goal,
            lesson=lesson,
            tags=tags,
            context=context,
            outcome=outcome,
            reinforcement_count=reinforcement_count,
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
    def _lesson_age_days(timestamp_utc: str) -> float:
        """Return age of a lesson in days. Returns large value if unparseable."""
        try:
            ts = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
            delta = datetime.now(tz=timezone.utc) - ts
            return delta.total_seconds() / 86400.0
        except (ValueError, TypeError, OverflowError):
            return 9999.0

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
