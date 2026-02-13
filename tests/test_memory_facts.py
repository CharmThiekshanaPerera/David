from __future__ import annotations

import json

import pytest

from agent.memory import LongTermMemory


def test_add_fact_and_lookup(tmp_path):
    memory_file = tmp_path / "long_term.json"
    memory = LongTermMemory(memory_file)

    fact = memory.add_fact(
        subject="David",
        predicate="father_name",
        object="Charm Thiekshana",
        source="user_teach",
    )

    assert fact.subject == "David"
    assert fact.predicate == "father_name"
    assert fact.object == "Charm Thiekshana"

    payload = json.loads(memory_file.read_text(encoding="utf-8"))
    assert "facts" in payload
    assert "lessons" in payload
    assert "preferences" in payload

    fetched = memory.get_fact("David", "father_name")
    assert fetched is not None
    assert fetched.object == "Charm Thiekshana"

    matches = memory.search_facts("Who is your father?")
    assert any(match.predicate == "father_name" for match in matches)


def test_reject_sensitive_fact(tmp_path):
    memory = LongTermMemory(tmp_path / "long_term.json")

    with pytest.raises(ValueError):
        memory.add_fact("David", "api_key", "123456")
