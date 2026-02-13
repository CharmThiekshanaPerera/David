from __future__ import annotations

from agent.memory import LongTermMemory
from agent.qa import MemoryTeacherQA


class FakeLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if not self._responses:
            raise AssertionError("Unexpected LLM call")
        return self._responses.pop(0)


def test_teach_then_ask_father_name(tmp_path):
    memory = LongTermMemory(tmp_path / "long_term.json")
    llm = FakeLLM(
        responses=[
            '{"facts": [], "notes": "captured relation"}',
            '{"answer": "My father is Charm Thiekshana.", "used_facts": [{"subject": "David", "predicate": "father_name", "object": "Charm Thiekshana"}]}',
        ]
    )
    qa = MemoryTeacherQA(llm=llm, memory=memory)

    teach_result = qa.teach("Hi David I am your dad. My Name is Charm Thiekshana.")

    assert any(
        fact.subject == "David" and fact.predicate == "father_name" and fact.object == "Charm Thiekshana"
        for fact in teach_result.stored_facts
    )

    father = memory.get_fact("David", "father_name")
    assert father is not None
    assert father.object == "Charm Thiekshana"

    answer = qa.ask("Who is your father?")
    assert answer == "My father is Charm Thiekshana."


def test_ask_unknown_fact_without_model_call(tmp_path):
    memory = LongTermMemory(tmp_path / "long_term.json")
    llm = FakeLLM(responses=[])
    qa = MemoryTeacherQA(llm=llm, memory=memory)

    answer = qa.ask("What is your favorite color?")

    assert answer.startswith("I do not know yet.")
    assert llm.calls == []
