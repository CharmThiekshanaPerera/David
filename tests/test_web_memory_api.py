from __future__ import annotations

import json
from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from agent.config import AgentConfig
from web.app import create_app
from web.control_center import DavidControlCenter


def _make_config(tmp_path: Path) -> AgentConfig:
    project_root = tmp_path / "project"
    workspace = tmp_path / "workspace"
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_file = memory_dir / "long_term.json"
    project_root.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    memory_file.write_text('{"facts": [], "lessons": [], "preferences": []}\n', encoding="utf-8")

    return AgentConfig(
        project_root=project_root,
        workspace_dir=workspace,
        memory_file=memory_file,
        logs_dir=logs_dir,
        model="qwen2.5-coder:1.5b",
        planner_model="qwen2.5-coder:1.5b",
        coder_model="qwen2.5-coder:1.5b",
        critic_model="qwen2.5-coder:1.5b",
        ollama_url="http://127.0.0.1:11434/api/chat",
        tdd_mode=False,
        max_iterations=4,
        command_timeout_sec=10,
        max_file_write_bytes=100_000,
        max_total_write_bytes=400_000,
        max_command_output_chars=8_000,
        temperature=0.2,
        allowed_commands=("python", "pytest"),
    )


@pytest.fixture
def memory_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    class FakeOllama:
        def __init__(self, _config):
            pass

        def chat(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
            if "Teach Extractor" in system_prompt:
                return '{"facts": [], "notes": "extracted"}'
            return '{"answer": "from memory", "used_facts": []}'

    monkeypatch.setattr("web.control_center.OllamaClient", FakeOllama)
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    app = create_app(control_center=center)
    app.config.update(TESTING=True)
    return app.test_client(), config


def test_api_teach_then_ask_persists(memory_client) -> None:
    client, config = memory_client

    teach = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Charm Thiekshana."})
    assert teach.status_code == 200
    teach_payload = teach.get_json()["data"]
    assert teach_payload["status"] == "stored"
    assert teach_payload["stored_count"] >= 1

    memory_raw = json.loads(config.memory_file.read_text(encoding="utf-8"))
    facts = memory_raw.get("facts", [])
    assert any(
        str(item.get("subject", "")).lower() == "david"
        and str(item.get("predicate", "")).lower() == "father_name"
        and str(item.get("object", "")) == "Charm Thiekshana"
        for item in facts
    )

    ask = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask.status_code == 200
    ask_payload = ask.get_json()["data"]
    assert ask_payload["mode"] == "ask"
    assert ask_payload["question"] == "Who is your father?"
    assert "Charm Thiekshana" in ask_payload["answer"]


def test_api_teach_conflict_requires_confirmation(memory_client) -> None:
    client, _config = memory_client

    first = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Charm Thiekshana."})
    assert first.status_code == 200
    assert first.get_json()["data"]["status"] == "stored"

    conflict = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Bob."})
    assert conflict.status_code == 200
    conflict_payload = conflict.get_json()["data"]
    assert conflict_payload["status"] == "conflict"
    assert conflict_payload["requires_confirmation"] is True
    assert conflict_payload["stored_count"] == 0

    ask_before = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask_before.status_code == 200
    assert "Charm Thiekshana" in ask_before.get_json()["data"]["answer"]

    confirm = client.post(
        "/api/teach",
        json={"message": "Hi David I am your dad. My Name is Bob.", "confirm_conflict": True},
    )
    assert confirm.status_code == 200
    confirm_payload = confirm.get_json()["data"]
    assert confirm_payload["status"] == "stored"
    assert confirm_payload["confirmed_conflict"] is True

    ask_after = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask_after.status_code == 200
    assert "Bob" in ask_after.get_json()["data"]["answer"]


def test_api_chat_teach_requires_confirm_save(memory_client) -> None:
    client, config = memory_client
    chat = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": False},
    )
    assert chat.status_code == 200
    payload = chat.get_json()["data"]
    assert payload["response"]["status"] == "confirmation_required"

    memory_raw = json.loads(config.memory_file.read_text(encoding="utf-8"))
    facts = memory_raw.get("facts", [])
    assert not any(str(item.get("predicate", "")).lower() == "father_name" for item in facts)


def test_api_chat_teach_deduplicates_facts(memory_client) -> None:
    client, config = memory_client

    first = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["response"]["status"] == "stored"

    second = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert second.status_code == 200
    second_payload = second.get_json()["data"]["response"]
    assert second_payload["status"] == "stored"
    assert int(second_payload.get("stored_count", 0)) == 0

    memory_raw = json.loads(config.memory_file.read_text(encoding="utf-8"))
    father_facts = [
        item
        for item in memory_raw.get("facts", [])
        if str(item.get("subject", "")).lower() == "david" and str(item.get("predicate", "")).lower() == "father_name"
    ]
    assert len(father_facts) == 1


def test_api_chat_sessions_and_conversations(memory_client) -> None:
    client, _config = memory_client
    session_id = "session_memory_test"

    chat = client.post(
        "/api/chat",
        json={"message": "Who is your father?", "intent": "ask", "session_id": session_id},
    )
    assert chat.status_code == 200

    conversations = client.get(f"/api/memory/conversations?session_id={session_id}")
    assert conversations.status_code == 200
    rows = conversations.get_json()["data"]["conversations"]
    assert len(rows) >= 2
    assert all(str(item.get("session_id", "")) == session_id for item in rows)

    sessions = client.get("/api/chat/sessions")
    assert sessions.status_code == 200
    session_rows = sessions.get_json()["data"]
    assert any(str(item.get("session_id", "")) == session_id for item in session_rows)


def test_api_chat_ask_memory_first_with_citations(memory_client) -> None:
    client, _config = memory_client
    teach = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert teach.status_code == 200

    ask = client.post("/api/chat", json={"message": "Who is your father?", "intent": "ask"})
    assert ask.status_code == 200
    response = ask.get_json()["data"]["response"]
    assert "Charm Thiekshana" in str(response.get("answer", ""))
    citations = response.get("citations", [])
    assert isinstance(citations, list)
    assert any(str(item.get("type", "")) == "fact" for item in citations)


def test_api_chat_intent_classification(memory_client) -> None:
    client, _config = memory_client

    ask_like = client.post("/api/chat", json={"message": "Who is your father?"})
    assert ask_like.status_code == 200
    ask_payload = ask_like.get_json()["data"]
    assert ask_payload["detected_intent"] == "ask"
    assert ask_payload["selected_intent"] == "ask"

    teach_like = client.post("/api/chat", json={"message": "Remember this: my name is Charm Thiekshana"})
    assert teach_like.status_code == 200
    teach_payload = teach_like.get_json()["data"]
    assert teach_payload["detected_intent"] == "teach"
