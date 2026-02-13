from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent.json_utils import JsonParseError, parse_json_object
from agent.llm import OllamaClient
from agent.memory import LongTermMemory, MemoryFact
from agent.prompts import FACT_QA_PROMPT, TEACH_EXTRACTOR_PROMPT


UNKNOWN_ANSWER = 'I do not know yet. Please teach me using --teach "...".'


@dataclass(frozen=True)
class TeachResult:
    stored_facts: list[MemoryFact]
    skipped_items: list[str]
    notes: str


class MemoryTeacherQA:
    """Explicit teach/ask flow for user-provided personal facts."""

    def __init__(self, llm: OllamaClient, memory: LongTermMemory) -> None:
        self._llm = llm
        self._memory = memory

    def teach(self, message: str) -> TeachResult:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("Teach message cannot be empty.")

        extracted = self._extract_facts(clean_message)
        heuristic = self._heuristic_facts(clean_message)
        fact_rows = self._merge_fact_rows(extracted.get("facts", []), heuristic)

        stored: list[MemoryFact] = []
        skipped: list[str] = []
        for row in fact_rows:
            subject = str(row.get("subject", "")).strip()
            predicate = str(row.get("predicate", "")).strip()
            object_value = str(row.get("object", "")).strip()
            if not subject or not predicate or not object_value:
                skipped.append("Skipped malformed fact row with missing subject/predicate/object.")
                continue
            try:
                stored.append(
                    self._memory.add_fact(
                        subject=subject,
                        predicate=predicate,
                        object=object_value,
                        source="user_teach",
                        confidence=1.0,
                    )
                )
            except ValueError as exc:
                skipped.append(f"Skipped fact `{subject}.{predicate}`: {exc}")

        notes = str(extracted.get("notes", "")).strip()
        return TeachResult(stored_facts=stored, skipped_items=skipped, notes=notes)

    def ask(self, question: str) -> str:
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("Question cannot be empty.")

        facts = self._memory.search_facts(clean_question, limit=8)
        if not facts:
            return UNKNOWN_ANSWER

        direct = self._direct_fact_answer(clean_question, facts)
        if direct:
            return direct

        user_prompt = json.dumps(
            {
                "question": clean_question,
                "facts": [
                    {"subject": fact.subject, "predicate": fact.predicate, "object": fact.object}
                    for fact in facts
                ],
            },
            indent=2,
        )

        try:
            raw = self._llm.chat(FACT_QA_PROMPT, user_prompt)
            parsed = parse_json_object(raw)
            answer = parsed.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
        except JsonParseError:
            pass

        return self._fallback_answer(clean_question, facts)

    @staticmethod
    def _direct_fact_answer(question: str, facts: list[MemoryFact]) -> str | None:
        lowered = question.lower()
        if "father" in lowered or "dad" in lowered:
            for fact in facts:
                if fact.subject.casefold() == "david" and fact.predicate.casefold() == "father_name":
                    return f"My father is {fact.object}."
        return None

    def _extract_facts(self, message: str) -> dict:
        raw = self._llm.chat(TEACH_EXTRACTOR_PROMPT, message)
        try:
            parsed = parse_json_object(raw)
        except JsonParseError:
            parsed = {"facts": [], "notes": "Model returned invalid JSON for teach extraction."}

        if not isinstance(parsed.get("facts"), list):
            parsed["facts"] = []
        if not isinstance(parsed.get("notes"), str):
            parsed["notes"] = ""
        return parsed

    @staticmethod
    def _heuristic_facts(message: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        lowered = message.lower()

        name_match = re.search(r"\bmy name is\s+([a-z][a-z .'-]{1,80})", message, flags=re.IGNORECASE)
        name_value = ""
        if name_match:
            name_value = name_match.group(1).strip(" .")

        if "i am your dad" in lowered or "i'm your dad" in lowered or "i am your father" in lowered:
            rows.append({"subject": "David", "predicate": "father_relation", "object": "dad"})
            if name_value:
                rows.append({"subject": "David", "predicate": "father_name", "object": name_value})

        return rows

    @staticmethod
    def _merge_fact_rows(primary: list, extra: list[dict[str, str]]) -> list[dict]:
        rows: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        for item in primary + extra:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject", "")).strip()
            predicate = str(item.get("predicate", "")).strip()
            object_value = str(item.get("object", "")).strip()
            key = (subject.casefold(), predicate.casefold(), object_value.casefold())
            if not subject or not predicate or not object_value or key in seen:
                continue
            seen.add(key)
            rows.append({"subject": subject, "predicate": predicate, "object": object_value})
        return rows

    @staticmethod
    def _fallback_answer(question: str, facts: list[MemoryFact]) -> str:
        lowered = question.lower()
        if "father" in lowered:
            for fact in facts:
                if fact.subject.casefold() == "david" and fact.predicate.casefold() == "father_name":
                    return f"My father is {fact.object}."

        first = facts[0]
        return (
            f"From memory: {first.subject} {first.predicate.replace('_', ' ')} is {first.object}."
        )
