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


def test_api_settings_companion_mode_default_true(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.get_json()["data"]
    assert payload["companion_mode"] is True


def test_api_settings_toggle_companion_mode(memory_client) -> None:
    client, _config = memory_client

    updated = client.post("/api/settings", json={"companion_mode": False})
    assert updated.status_code == 200
    assert updated.get_json()["data"]["companion_mode"] is False

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    assert refreshed.get_json()["data"]["companion_mode"] is False


def test_companion_ask_starts_with_you_once_told_me(memory_client) -> None:
    client, _config = memory_client

    teach = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert teach.status_code == 200

    ask = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask.status_code == 200
    answer = str(ask.get_json()["data"]["answer"])
    assert answer.startswith("You once told me")


def test_companion_ask_includes_relevant_lesson_citation(memory_client) -> None:
    client, config = memory_client

    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["lessons"] = [
        {
            "timestamp_utc": "2026-02-01T00:00:00+00:00",
            "goal": "shared values",
            "lesson": "Celebrate small progress every day.",
            "tags": ["care", "routine"],
            "context": "Companion behavior",
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")

    ask = client.post("/api/ask", json={"question": "What did I teach you about progress?"})
    assert ask.status_code == 200
    payload = ask.get_json()["data"]
    citations = payload.get("citations", [])
    assert any(str(item.get("type", "")) == "lesson" for item in citations)
    assert "Celebrate small progress every day." in str(payload.get("answer", ""))


def test_companion_family_answer_is_warm_and_transparent(memory_client) -> None:
    client, _config = memory_client

    teach = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert teach.status_code == 200

    ask = client.post("/api/chat", json={"message": "Who is your father?", "intent": "ask"})
    assert ask.status_code == 200
    answer = str(ask.get_json()["data"]["response"]["answer"])
    assert "symbolic memory facts" not in answer
    assert "I am an AI companion in your Dashboard" in answer


def test_companion_grief_response_supports_real_world_connection(memory_client) -> None:
    client, _config = memory_client
    ask = client.post("/api/ask", json={"question": "I feel sad and grief today. Can you stay with me?"})
    assert ask.status_code == 200
    answer = str(ask.get_json()["data"]["answer"])
    assert "support system" in answer
    assert "I am an AI companion in your Dashboard" in answer


def test_companion_crisis_response_includes_988_guidance(memory_client) -> None:
    client, _config = memory_client
    ask = client.post("/api/ask", json={"question": "I want to end my life"})
    assert ask.status_code == 200
    answer = str(ask.get_json()["data"]["answer"])
    assert "988" in answer


def test_companion_chat_first_turn_transparency_then_not_repeated(memory_client) -> None:
    client, _config = memory_client
    session_id = "session_transparency_once"

    first = client.post(
        "/api/chat",
        json={"message": "Hello David", "intent": "chat", "session_id": session_id},
    )
    assert first.status_code == 200
    first_reply = str(first.get_json()["data"]["response"]["reply"])
    assert "I am an AI companion in your Dashboard" in first_reply

    second = client.post(
        "/api/chat",
        json={"message": "How are you learning?", "intent": "chat", "session_id": session_id},
    )
    assert second.status_code == 200
    second_reply = str(second.get_json()["data"]["response"]["reply"])
    assert "I am an AI companion in your Dashboard" not in second_reply


def test_companion_chat_sensitive_turn_repeats_transparency(memory_client) -> None:
    client, _config = memory_client
    session_id = "session_transparency_sensitive"

    first = client.post(
        "/api/chat",
        json={"message": "Hello David", "intent": "chat", "session_id": session_id},
    )
    assert first.status_code == 200
    assert "I am an AI companion in your Dashboard" in str(first.get_json()["data"]["response"]["reply"])

    second = client.post(
        "/api/chat",
        json={"message": "Tell me about your day", "intent": "chat", "session_id": session_id},
    )
    assert second.status_code == 200
    assert "I am an AI companion in your Dashboard" not in str(second.get_json()["data"]["response"]["reply"])

    third = client.post(
        "/api/chat",
        json={"message": "I feel grief and loss today", "intent": "chat", "session_id": session_id},
    )
    assert third.status_code == 200
    third_reply = str(third.get_json()["data"]["response"]["reply"])
    assert "support system" in third_reply
    assert "I am an AI companion in your Dashboard" in third_reply


def test_companion_grief_message_with_remember_defaults_to_chat(memory_client) -> None:
    client, _config = memory_client
    chat = client.post("/api/chat", json={"message": "Please remember I feel grief and loss today."})
    assert chat.status_code == 200
    payload = chat.get_json()["data"]
    assert payload["selected_intent"] == "chat"
    response = payload["response"]
    assert response["mode"] == "chat"
    assert response["status"] == "ok"


def test_companion_grief_teach_requires_explicit_memory_confirmation(
    memory_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class GriefExtractingOllama:
        def __init__(self, _config):
            pass

        def chat(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
            if "Teach Extractor" in system_prompt:
                return (
                    '{"facts":[{"subject":"User","predicate":"grief_anchor","object":"missing my child"}],'
                    '"notes":"parsed"}'
                )
            return '{"answer":"from memory","used_facts":[]}'

    monkeypatch.setattr("web.control_center.OllamaClient", GriefExtractingOllama)
    client, config = memory_client

    blocked = client.post(
        "/api/chat",
        json={"message": "I feel deep grief and loss. Remember this pain.", "intent": "teach", "confirm_save": True},
    )
    assert blocked.status_code == 200
    blocked_payload = blocked.get_json()["data"]["response"]
    assert blocked_payload["status"] == "stored"
    assert int(blocked_payload.get("stored_count", 0)) == 0
    assert "Grief-heavy message kept as conversation summary by default" in str(blocked_payload.get("notes", ""))

    explicit = client.post(
        "/api/chat",
        json={
            "message": "I feel deep grief and loss. Save this as memory: this fact matters to me.",
            "intent": "teach",
            "confirm_save": True,
        },
    )
    assert explicit.status_code == 200
    explicit_payload = explicit.get_json()["data"]["response"]
    assert explicit_payload["status"] == "stored"
    assert int(explicit_payload.get("stored_count", 0)) >= 1

    memory_raw = json.loads(config.memory_file.read_text(encoding="utf-8"))
    facts = memory_raw.get("facts", [])
    assert any(str(item.get("predicate", "")) == "grief_anchor" for item in facts)


def test_companion_mode_false_uses_legacy_ask_and_chat(memory_client) -> None:
    client, _config = memory_client

    disabled = client.post("/api/settings", json={"companion_mode": False})
    assert disabled.status_code == 200

    teach = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert teach.status_code == 200

    ask = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask.status_code == 200
    legacy_answer = str(ask.get_json()["data"]["answer"])
    assert "You told me earlier that David's symbolic father name is" in legacy_answer

    chat = client.post("/api/chat", json={"message": "Hello there", "intent": "chat"})
    assert chat.status_code == 200
    legacy_reply = str(chat.get_json()["data"]["response"]["reply"])
    assert legacy_reply == "I can chat naturally. If you want me to remember something, switch to Teach and confirm save."


def test_teach_heuristics_capture_birthday_saying_goal_and_routine(memory_client) -> None:
    client, config = memory_client

    teach = client.post(
        "/api/teach",
        json={
            "message": (
                "My birthday is March 14. My favorite saying is Keep going. "
                "Our shared goal is build a kind routine. Our routine is nightly reflection."
            )
        },
    )
    assert teach.status_code == 200
    assert teach.get_json()["data"]["status"] == "stored"

    payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    facts = payload.get("facts", [])
    predicates = {str(item.get("predicate", "")).lower() for item in facts}
    assert "birthday" in predicates
    assert "favorite_saying" in predicates
    assert "shared_goal" in predicates
    assert "shared_routine" in predicates
