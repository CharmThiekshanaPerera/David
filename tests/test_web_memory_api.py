from __future__ import annotations

import io
import json
import zipfile
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


def _build_test_xlsx_bytes() -> bytes:
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sales" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
    sheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>region</t></is></c>
      <c r="B1" t="inlineStr"><is><t>amount</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>East</t></is></c>
      <c r="B2"><v>120</v></c>
    </row>
    <row r="3">
      <c r="A3" t="inlineStr"><is><t>West</t></is></c>
      <c r="B3"><v>95</v></c>
    </row>
  </sheetData>
</worksheet>
"""
    types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buff.getvalue()


def _build_test_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Page >>\nendobj\n"
        b"2 0 obj\n<< /Length 31 >>\nstream\n(Budget East region grows) Tj\nendstream\nendobj\n"
        b"%%EOF\n"
    )


def _build_test_png_bytes() -> bytes:
    # Minimal PNG with IHDR width=2, height=3
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x02\x00\x00\x00\x03\x08\x02\x00\x00\x00"
        b"\x00\x00\x00\x00"
    )


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


def test_api_clear_conversations_by_session_and_all(memory_client) -> None:
    client, _config = memory_client
    session_a = "session_clear_a"
    session_b = "session_clear_b"

    first = client.post("/api/chat", json={"message": "Who is your father?", "intent": "ask", "session_id": session_a})
    assert first.status_code == 200
    second = client.post("/api/chat", json={"message": "What is your name?", "intent": "ask", "session_id": session_b})
    assert second.status_code == 200

    clear_a = client.post("/api/memory/conversations/clear", json={"session_id": session_a})
    assert clear_a.status_code == 200
    clear_a_data = clear_a.get_json()["data"]
    assert clear_a_data["scope"] == "session"
    assert clear_a_data["session_id"] == session_a
    assert int(clear_a_data["removed_count"]) >= 2

    conv_a = client.get(f"/api/memory/conversations?session_id={session_a}")
    conv_b = client.get(f"/api/memory/conversations?session_id={session_b}")
    assert conv_a.status_code == 200
    assert conv_b.status_code == 200
    assert int(conv_a.get_json()["data"]["total"]) == 0
    assert int(conv_b.get_json()["data"]["total"]) >= 2

    clear_all = client.post("/api/memory/conversations/clear", json={})
    assert clear_all.status_code == 200
    clear_all_data = clear_all.get_json()["data"]
    assert clear_all_data["scope"] == "all"

    all_rows = client.get("/api/memory/conversations")
    assert all_rows.status_code == 200
    assert int(all_rows.get_json()["data"]["total"]) == 0


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


def test_parent_teaching_mode_requires_clarification_then_stores_value(memory_client) -> None:
    client, _config = memory_client
    session_id = "session_parent_teach_1"

    first = client.post(
        "/api/chat",
        json={
            "message": "Always value patience.",
            "intent": "teach",
            "confirm_save": True,
            "parent_teaching_mode": True,
            "session_id": session_id,
        },
    )
    assert first.status_code == 200
    first_response = first.get_json()["data"]["response"]
    assert first_response["status"] == "parent_teaching_clarify_required"
    assert first_response["requires_clarification"] is True
    assert "How should I apply" in str(first_response.get("question", ""))

    second = client.post(
        "/api/chat",
        json={
            "message": "Apply patience by investigating failures step by step before editing code.",
            "intent": "teach",
            "confirm_save": True,
            "parent_teaching_mode": True,
            "session_id": session_id,
        },
    )
    assert second.status_code == 200
    second_response = second.get_json()["data"]["response"]
    assert second_response["status"] == "stored"
    assert second_response["parent_teaching_stage"] == "completed"
    assert int(second_response.get("stored_value_count", 0)) == 1

    snapshot = client.get("/api/memory")
    assert snapshot.status_code == 200
    data = snapshot.get_json()["data"]
    assert int(data.get("values_count", 0)) >= 1
    assert any("patience" in str(item.get("principle", "")).lower() for item in data.get("values", []))


def test_meaningful_chat_writes_reflection(memory_client) -> None:
    client, _config = memory_client

    chat = client.post(
        "/api/chat",
        json={"message": "Please explain this step-by-step so I can follow clearly.", "intent": "chat"},
    )
    assert chat.status_code == 200

    snapshot = client.get("/api/memory")
    assert snapshot.status_code == 200
    payload = snapshot.get_json()["data"]
    reflections = payload.get("reflections", [])
    assert any("step-by-step" in str(item.get("lesson", "")).lower() for item in reflections)
    assert int(payload.get("reflection_count", 0)) >= 1
    assert all(str(item.get("kind", "")).lower() != "reflection" for item in payload.get("lessons", []))


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


def test_api_settings_memory_insight_mode_default_true(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.get_json()["data"]
    assert payload["memory_insight_mode"] is True


def test_api_settings_toggle_memory_insight_mode(memory_client) -> None:
    client, _config = memory_client
    updated = client.post("/api/settings", json={"memory_insight_mode": False})
    assert updated.status_code == 200
    assert updated.get_json()["data"]["memory_insight_mode"] is False

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    assert refreshed.get_json()["data"]["memory_insight_mode"] is False


def test_api_settings_toggle_parent_teaching_mode(memory_client) -> None:
    client, _config = memory_client

    updated = client.post("/api/settings", json={"parent_teaching_mode": True})
    assert updated.status_code == 200
    assert updated.get_json()["data"]["parent_teaching_mode"] is True

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    assert refreshed.get_json()["data"]["parent_teaching_mode"] is True


def test_api_settings_autonomous_self_improvement_mode_defaults_true(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.get_json()["data"]
    assert payload["autonomous_self_improvement_mode"] is True


def test_api_settings_toggle_autonomous_self_improvement_mode(memory_client) -> None:
    client, _config = memory_client
    updated = client.post("/api/settings", json={"autonomous_self_improvement_mode": False})
    assert updated.status_code == 200
    assert updated.get_json()["data"]["autonomous_self_improvement_mode"] is False

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    assert refreshed.get_json()["data"]["autonomous_self_improvement_mode"] is False


def test_api_settings_upload_vision_defaults(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.get_json()["data"]
    assert payload["upload_vision_mode"] is False
    assert str(payload["upload_vision_model"]) == ""


def test_api_settings_toggle_upload_vision_mode(memory_client) -> None:
    client, _config = memory_client
    updated = client.post(
        "/api/settings",
        json={"upload_vision_mode": True, "upload_vision_model": "qwen2.5-coder:1.5b"},
    )
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert data["upload_vision_mode"] is True
    assert str(data["upload_vision_model"]) == "qwen2.5-coder:1.5b"

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    refreshed_data = refreshed.get_json()["data"]
    assert refreshed_data["upload_vision_mode"] is True
    assert str(refreshed_data["upload_vision_model"]) == "qwen2.5-coder:1.5b"


def test_api_settings_plan_quality_threshold_persists(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert int(settings.get_json()["data"]["plan_quality_threshold"]) == 0

    updated = client.post("/api/settings", json={"plan_quality_threshold": 85})
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert int(data["plan_quality_threshold"]) == 85

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    assert int(refreshed.get_json()["data"]["plan_quality_threshold"]) == 85


def test_api_settings_voice_defaults(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.get_json()["data"]
    assert payload["voice_mode_enabled"] is False
    assert payload["voice_text_only_mode"] is False
    assert payload["voice_input_mode"] == "manual"
    assert payload["voice_continuous_mode"] is False
    assert int(payload["voice_post_reply_delay_ms"]) == 450
    assert payload["voice_stop_phrases"] == ["stop listening", "end chat", "bye david"]
    assert float(payload["voice_vad_threshold"]) == 0.035
    assert int(payload["voice_vad_silence_ms"]) == 900
    assert int(payload["voice_vad_min_speech_ms"]) == 300
    assert float(payload["vad_threshold"]) == 0.035
    assert int(payload["vad_silence_ms"]) == 900
    assert int(payload["vad_min_speech_ms"]) == 300
    assert str(payload["voice_style"]) == "warm"
    assert int(payload["voice_rate"]) == 100
    assert str(payload["voice_stt_engine"]) == "none"
    assert str(payload["voice_tts_engine"]) == "browser"


def test_api_settings_toggle_voice_mode(memory_client) -> None:
    client, _config = memory_client
    updated = client.post(
        "/api/settings",
        json={
            "voice_mode_enabled": True,
            "voice_text_only_mode": True,
            "voice_input_mode": "vad",
            "voice_continuous_mode": True,
            "voice_post_reply_delay_ms": 700,
            "voice_stop_phrases": [" stop listening ", "Bye David", "bye david", "", "end chat"],
            "voice_vad_threshold": 0.045,
            "voice_vad_silence_ms": 1100,
            "voice_vad_min_speech_ms": 420,
            "voice_style": "clear",
            "voice_rate": 130,
            "voice_stt_engine": "whisper_cli",
            "voice_stt_model": "base.en",
            "voice_stt_language": "en",
            "voice_stt_command": "whisper",
            "voice_whisper_cpp_command": "whisper-cli",
            "voice_whisper_cpp_model_path": "/tmp/models/ggml-base.en.bin",
            "voice_tts_engine": "piper",
            "voice_tts_command": "piper",
            "voice_tts_model_path": "/tmp/models/en_US-amy-medium.onnx",
            "voice_chunk_chars": 210,
        },
    )
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert data["voice_mode_enabled"] is True
    assert data["voice_text_only_mode"] is True
    assert data["voice_input_mode"] == "vad"
    assert data["voice_continuous_mode"] is True
    assert int(data["voice_post_reply_delay_ms"]) == 700
    assert data["voice_stop_phrases"] == ["stop listening", "bye david", "end chat"]
    assert float(data["voice_vad_threshold"]) == 0.045
    assert int(data["voice_vad_silence_ms"]) == 1100
    assert int(data["voice_vad_min_speech_ms"]) == 420
    assert float(data["vad_threshold"]) == 0.045
    assert int(data["vad_silence_ms"]) == 1100
    assert int(data["vad_min_speech_ms"]) == 420
    assert str(data["voice_style"]) == "clear"
    assert int(data["voice_rate"]) == 130
    assert str(data["voice_stt_engine"]) == "whisper_cli"
    assert str(data["voice_tts_engine"]) == "piper"
    assert int(data["voice_chunk_chars"]) == 210


def test_api_settings_voice_vad_aliases_and_ptt_back_compat(memory_client) -> None:
    client, _config = memory_client
    updated = client.post(
        "/api/settings",
        json={
            "voice_input_mode": "ptt",
            "vad_threshold": 0.055,
            "vad_silence_ms": 1250,
            "vad_min_speech_ms": 520,
        },
    )
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert data["voice_input_mode"] == "manual"
    assert float(data["voice_vad_threshold"]) == 0.055
    assert int(data["voice_vad_silence_ms"]) == 1250
    assert int(data["voice_vad_min_speech_ms"]) == 520


def test_api_settings_voice_stop_phrases_persist_and_normalize(memory_client) -> None:
    client, _config = memory_client
    updated = client.post(
        "/api/settings",
        json={
            "voice_stop_phrases": " stop listening , END CHAT, bye david, bye david,   ",
        },
    )
    assert updated.status_code == 200
    payload = updated.get_json()["data"]
    assert payload["voice_stop_phrases"] == ["stop listening", "end chat", "bye david"]

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.get_json()["data"]
    assert refreshed_payload["voice_stop_phrases"] == ["stop listening", "end chat", "bye david"]


def test_api_settings_personality_calibration_defaults_present(memory_client) -> None:
    client, _config = memory_client
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.get_json()["data"]
    assert int(payload["personality_warmth"]) == 55
    assert int(payload["personality_verbosity"]) == 55
    assert int(payload["personality_curiosity"]) == 50


def test_api_settings_toggle_personality_calibration(memory_client) -> None:
    client, _config = memory_client
    updated = client.post(
        "/api/settings",
        json={"personality_warmth": 10, "personality_verbosity": 20, "personality_curiosity": 90},
    )
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert int(data["personality_warmth"]) == 10
    assert int(data["personality_verbosity"]) == 20
    assert int(data["personality_curiosity"]) == 90

    refreshed = client.get("/api/settings")
    assert refreshed.status_code == 200
    again = refreshed.get_json()["data"]
    assert int(again["personality_warmth"]) == 10
    assert int(again["personality_verbosity"]) == 20
    assert int(again["personality_curiosity"]) == 90


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


def test_memory_insight_mode_provides_structured_references(memory_client) -> None:
    client, config = memory_client
    session_id = "session_insight_refs"

    teach = client.post(
        "/api/chat",
        json={
            "message": "Hi David I am your dad. My Name is Charm Thiekshana.",
            "intent": "teach",
            "confirm_save": True,
            "session_id": session_id,
        },
    )
    assert teach.status_code == 200

    primer = client.post(
        "/api/chat",
        json={
            "message": "Please use step-by-step guidance in your explanations.",
            "intent": "chat",
            "session_id": session_id,
        },
    )
    assert primer.status_code == 200

    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["lessons"] = [
        {
            "timestamp_utc": "2026-02-01T00:00:00+00:00",
            "goal": "companion style",
            "lesson": "User prefers step-by-step guidance.",
            "tags": ["preference", "clarity"],
            "context": "chat",
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")

    ask = client.post(
        "/api/chat",
        json={
            "message": "Who is your father? Please answer with step-by-step guidance.",
            "intent": "ask",
            "session_id": session_id,
        },
    )
    assert ask.status_code == 200
    response = ask.get_json()["data"]["response"]
    insight = response.get("memory_insight", {})
    assert insight.get("enabled") is True
    assert str(insight.get("summary", "")).startswith("This answer was influenced by")
    influences = insight.get("influences", [])
    assert isinstance(influences, list)
    kinds = {str(item.get("type", "")) for item in influences}
    assert "fact" in kinds
    assert "lesson" in kinds
    assert "conversation" in kinds
    assert all("#" in str(item.get("reference", "")) for item in influences)


def test_memory_insight_mode_disabled_returns_no_influences(memory_client) -> None:
    client, _config = memory_client
    disable = client.post("/api/settings", json={"memory_insight_mode": False})
    assert disable.status_code == 200

    ask = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask.status_code == 200
    insight = ask.get_json()["data"].get("memory_insight", {})
    assert insight.get("enabled") is False
    assert insight.get("influences") == []


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


def test_companion_personality_calibration_affects_web_tone_only(memory_client) -> None:
    client, _config = memory_client

    low = client.post(
        "/api/settings",
        json={"personality_warmth": 0, "personality_verbosity": 0, "personality_curiosity": 0},
    )
    assert low.status_code == 200

    low_chat = client.post(
        "/api/chat",
        json={"message": "Hello David", "intent": "chat", "session_id": "session_tone_low"},
    )
    assert low_chat.status_code == 200
    low_reply = str(low_chat.get_json()["data"]["response"]["reply"])
    assert "I will keep this concise and professional." in low_reply
    assert "Would you like to teach me one small memory or ask me a gentle question?" not in low_reply

    high = client.post(
        "/api/settings",
        json={"personality_warmth": 100, "personality_verbosity": 100, "personality_curiosity": 100},
    )
    assert high.status_code == 200

    high_chat = client.post(
        "/api/chat",
        json={"message": "Hello David", "intent": "chat", "session_id": "session_tone_high"},
    )
    assert high_chat.status_code == 200
    high_reply = str(high_chat.get_json()["data"]["response"]["reply"])
    assert "Yay, you are doing great." in high_reply
    assert "Would you like to teach me one small memory or ask me a gentle question?" in high_reply
    assert "quick check question" in high_reply

    non_web_actor = client.post(
        "/api/chat",
        json={"message": "Hello David", "intent": "chat", "session_id": "session_tone_cli", "actor": "cli_runner"},
    )
    assert non_web_actor.status_code == 200
    non_web_reply = str(non_web_actor.get_json()["data"]["response"]["reply"])
    assert "Yay, you are doing great." not in non_web_reply


def test_companion_growth_chat_references_learning(memory_client) -> None:
    client, config = memory_client
    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["lessons"] = [
        {
            "timestamp_utc": "2026-02-01T00:00:00+00:00",
            "goal": "run:demo",
            "lesson": "Tests failed due to missing edge case, then passed after structure refinement.",
            "tags": ["reflection", "run", "testing"],
            "context": "status=success",
            "kind": "reflection",
            "source": "reflection_engine",
            "reflection_key": "run:demo",
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")

    chat = client.post("/api/chat", json={"message": "How have you grown over time?", "intent": "chat"})
    assert chat.status_code == 200
    reply = str(chat.get_json()["data"]["response"]["reply"])
    assert "Earlier, I struggled" in reply
    assert "software evolving through stored lessons" in reply


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


def test_project_brain_recall_returns_architecture_overview(memory_client) -> None:
    client, config = memory_client
    project_dir = config.workspace_dir / "projects" / "demo_project"
    project_dir.mkdir(parents=True, exist_ok=True)

    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["projects"] = [
        {
            "id": "project_brain_demo_project",
            "created_at": "2026-02-01T00:00:00+00:00",
            "last_updated": "2026-02-12T00:00:00+00:00",
            "project_slug": "demo_project",
            "project_path": str(project_dir),
            "project_relative_path": "projects/demo_project",
            "architecture_summary": "modular CLI structure with JSON storage and dedicated tests",
            "key_design_decisions": ["Planned around: Keep CLI and storage concerns separated."],
            "testing_approach": "Pytest tests under tests/ with iterative command validation.",
            "known_weaknesses": ["edge-case validation needed improvement."],
            "last_goal": "Revisit demo project",
            "last_run_id": "run_demo_prev",
            "last_status": "success",
            "last_message": "done",
            "source": "project_brain_engine",
            "history": [],
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")

    ask = client.post(
        "/api/chat",
        json={"message": "Summarize demo_project architecture and weaknesses.", "intent": "ask"},
    )
    assert ask.status_code == 200
    response = ask.get_json()["data"]["response"]
    answer = str(response.get("answer", ""))
    assert "modular CLI structure with JSON storage" in answer
    assert "edge-case validation needed improvement" in answer.lower()
    citations = response.get("citations", [])
    assert any(str(item.get("type", "")) == "project" for item in citations)

    snapshot = client.get("/api/memory")
    assert snapshot.status_code == 200
    snapshot_payload = snapshot.get_json()["data"]
    assert int(snapshot_payload.get("project_count", 0)) >= 1


def test_legacy_archive_persists_significant_moments(memory_client) -> None:
    client, config = memory_client
    marked = client.post(
        "/api/legacy_archive",
        json={
            "source_type": "teaching",
            "source_id": "value_patience_1",
            "summary": "User taught patience during debugging.",
            "details": "Apply patience by investigating failures step by step.",
            "timestamp_utc": "2026-05-14T10:30:00+00:00",
            "metadata": {"category": "values"},
        },
    )
    assert marked.status_code == 200
    entry = marked.get_json()["data"]
    assert entry["kind"] == "significant_moment"
    assert entry["source_type"] == "teaching"

    listed = client.get("/api/legacy_archive")
    assert listed.status_code == 200
    payload = listed.get_json()["data"]
    assert int(payload.get("total", 0)) >= 1
    assert any(str(item.get("id", "")) == str(entry.get("id", "")) for item in payload.get("items", []))

    memory_raw = json.loads(config.memory_file.read_text(encoding="utf-8"))
    archive = memory_raw.get("legacy_archive", [])
    assert any(str(item.get("id", "")) == str(entry.get("id", "")) for item in archive)

    snapshot = client.get("/api/memory")
    assert snapshot.status_code == 200
    snap_data = snapshot.get_json()["data"]
    assert int(snap_data.get("legacy_archive_count", 0)) >= 1
    assert any(str(item.get("id", "")) == str(entry.get("id", "")) for item in snap_data.get("legacy_archive", []))


def test_legacy_archive_remove_entry(memory_client) -> None:
    client, _config = memory_client
    marked = client.post(
        "/api/legacy_archive",
        json={
            "source_type": "milestone",
            "source_id": "run:demo_1",
            "summary": "First successful project completion.",
            "details": "Reached green tests with fewer iterations.",
        },
    )
    assert marked.status_code == 200
    entry_id = str(marked.get_json()["data"]["id"])

    removed = client.post(f"/api/legacy_archive/{entry_id}/remove", json={})
    assert removed.status_code == 200
    removed_payload = removed.get_json()["data"]
    assert removed_payload["removed"] is True
    assert removed_payload["removed_id"] == entry_id

    listed = client.get("/api/legacy_archive")
    assert listed.status_code == 200
    items = listed.get_json()["data"].get("items", [])
    assert all(str(item.get("id", "")) != entry_id for item in items)


def test_api_upload_csv_analyze_list_and_ask(memory_client) -> None:
    client, _config = memory_client
    csv_content = b"region,amount\nEast,120\nWest,95\n"

    uploaded = client.post(
        "/api/uploads/analyze",
        data={"actor": "web_ui", "file": (io.BytesIO(csv_content), "sales.csv")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    upload_data = uploaded.get_json()["data"]
    upload_id = str(upload_data.get("upload_id", ""))
    assert upload_id.startswith("upl_")
    analysis = upload_data.get("analysis", {})
    assert str(analysis.get("format", "")) == "csv"
    assert int((analysis.get("stats") or {}).get("rows", 0)) == 2
    assert int((analysis.get("stats") or {}).get("columns", 0)) == 2
    assert str(analysis.get("content_brief", "")).strip()
    profiles = analysis.get("column_profiles", [])
    assert isinstance(profiles, list)
    assert any(str(item.get("name", "")) == "amount" for item in profiles if isinstance(item, dict))

    listed = client.get("/api/uploads")
    assert listed.status_code == 200
    rows = listed.get_json()["data"]
    assert any(str(row.get("upload_id", "")) == upload_id for row in rows)

    detail = client.get(f"/api/uploads/{upload_id}")
    assert detail.status_code == 200
    detail_data = detail.get_json()["data"]
    assert str((detail_data.get("analysis") or {}).get("kind", "")) == "table"

    asked = client.post(
        f"/api/uploads/{upload_id}/ask",
        json={"question": "Which sampled row mentions East?"},
    )
    assert asked.status_code == 200
    asked_data = asked.get_json()["data"]
    assert "East" in str(asked_data.get("answer", ""))
    assert float(asked_data.get("confidence", 0.0)) > 0.0

    avg = client.post(
        f"/api/uploads/{upload_id}/ask",
        json={"question": "What is the average amount?"},
    )
    assert avg.status_code == 200
    avg_answer = str(avg.get_json()["data"].get("answer", ""))
    assert "107.5" in avg_answer


def test_api_upload_xlsx_analyze(memory_client) -> None:
    client, _config = memory_client
    xlsx_content = _build_test_xlsx_bytes()

    uploaded = client.post(
        "/api/uploads/analyze",
        data={
            "file": (
                io.BytesIO(xlsx_content),
                "sales.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    analysis = uploaded.get_json()["data"]["analysis"]
    assert str(analysis.get("format", "")) == "xlsx"
    stats = analysis.get("stats", {})
    assert int(stats.get("sheet_count", 0)) >= 1
    assert int(stats.get("rows", 0)) >= 2
    assert int(stats.get("columns", 0)) >= 2


def test_api_upload_pdf_and_image_analysis(memory_client) -> None:
    client, _config = memory_client

    pdf_uploaded = client.post(
        "/api/uploads/analyze",
        data={"file": (io.BytesIO(_build_test_pdf_bytes()), "brief.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )
    assert pdf_uploaded.status_code == 200
    pdf_data = pdf_uploaded.get_json()["data"]
    pdf_analysis = pdf_data.get("analysis", {})
    assert str(pdf_analysis.get("format", "")) == "pdf"
    assert int((pdf_analysis.get("stats") or {}).get("pages", 0)) >= 1
    assert str(pdf_analysis.get("content_brief", "")).strip()

    asked = client.post(
        f"/api/uploads/{pdf_data['upload_id']}/ask",
        json={"question": "What text is in the document?"},
    )
    assert asked.status_code == 200
    assert "document" in str(asked.get_json()["data"].get("answer", "")).lower() or "east" in str(
        asked.get_json()["data"].get("answer", "")
    ).lower()

    asked_summary = client.post(
        f"/api/uploads/{pdf_data['upload_id']}/ask",
        json={"question": "What is this pdf showing?"},
    )
    assert asked_summary.status_code == 200
    assert str(asked_summary.get_json()["data"].get("answer", "")).strip()

    image_uploaded = client.post(
        "/api/uploads/analyze",
        data={"file": (io.BytesIO(_build_test_png_bytes()), "tiny.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert image_uploaded.status_code == 200
    image_analysis = image_uploaded.get_json()["data"]["analysis"]
    assert str(image_analysis.get("format", "")) == "png"
    assert int((image_analysis.get("stats") or {}).get("width", 0)) == 2
    assert int((image_analysis.get("stats") or {}).get("height", 0)) == 3
    assert str(image_analysis.get("content_brief", "")).strip()


def test_api_upload_image_with_vision_enrichment(memory_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _config = memory_client

    class FakeVisionResponse:
        status_code = 200
        text = '{"message":{"content":"Vision summary"}}'

        @staticmethod
        def json() -> dict[str, dict[str, str]]:
            return {"message": {"content": "The image appears to show a small synthetic graphic used for test fixtures."}}

    def fake_post(_url, json=None, timeout=None):
        payload = json or {}
        messages = payload.get("messages", [])
        assert isinstance(messages, list)
        assert any(isinstance(msg, dict) and isinstance(msg.get("images"), list) for msg in messages)
        return FakeVisionResponse()

    monkeypatch.setattr("web.control_center.requests.post", fake_post)

    uploaded = client.post(
        "/api/uploads/analyze",
        data={
            "use_vision": "true",
            "vision_model": "qwen2.5-coder:1.5b",
            "file": (io.BytesIO(_build_test_png_bytes()), "tiny.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    analysis = uploaded.get_json()["data"]["analysis"]
    vision_meta = analysis.get("vision", {})
    assert str(vision_meta.get("status", "")) == "applied"
    assert str(vision_meta.get("model", "")) == "qwen2.5-coder:1.5b"
    assert bool((analysis.get("stats") or {}).get("vision_enriched")) is True
    assert "small synthetic graphic" in str(analysis.get("content_brief", "")).lower()


def test_self_improvement_sandbox_proposal_lifecycle(memory_client) -> None:
    client, config = memory_client
    target_path = "agent/prototype_improvement.py"
    target_file = config.project_root / target_path
    assert not target_file.exists()

    proposed = client.post(
        "/api/self_improvements/propose",
        json={
            "title": "Optimize memory lookup",
            "summary": "Prototype indexed retrieval for repeated ask flows.",
            "rationale": "Lower repeated token scanning overhead in chat sessions.",
            "files": [
                {
                    "path": target_path,
                    "content": "def optimized_lookup():\n    return 'ok'\n",
                }
            ],
        },
    )
    assert proposed.status_code == 200
    proposal = proposed.get_json()["data"]
    assert proposal["status"] == "pending"
    assert "agent_sandbox" in str(proposal.get("sandbox_dir", ""))
    assert Path(str(proposal.get("proposal_doc", ""))).exists()

    listed = client.get("/api/self_improvements")
    assert listed.status_code == 200
    listed_payload = listed.get_json()["data"]
    assert int(listed_payload.get("total", 0)) >= 1
    proposal_id = str(proposal.get("id", ""))
    assert any(str(item.get("id", "")) == proposal_id for item in listed_payload.get("items", []))

    approved = client.post(
        f"/api/self_improvements/{proposal_id}/decision",
        json={"decision": "approve", "note": "Merge prototype into main code."},
    )
    assert approved.status_code == 200
    approved_payload = approved.get_json()["data"]
    assert approved_payload["status"] == "merged"
    assert str(approved_payload.get("decision", {}).get("decision", "")) == "approve"
    assert target_file.exists()
    assert "optimized_lookup" in target_file.read_text(encoding="utf-8")


def test_meaningful_chat_triggers_autonomous_self_improvement(memory_client) -> None:
    client, _config = memory_client
    chat = client.post(
        "/api/chat",
        json={"message": "Please explain this step-by-step and keep the structure consistent.", "intent": "chat"},
    )
    assert chat.status_code == 200
    payload = chat.get_json()["data"]
    cycle = payload.get("autonomous_self_improvement", {})
    assert str(cycle.get("status", "")) in {"proposed", "skipped"}

    listed = client.get("/api/self_improvements")
    assert listed.status_code == 200
    rows = listed.get_json()["data"].get("items", [])
    assert any(bool((row.get("metadata") or {}).get("autonomous", False)) for row in rows)


def test_self_improvement_blocks_safety_logic_paths(memory_client) -> None:
    client, _config = memory_client
    blocked = client.post(
        "/api/self_improvements/propose",
        json={
            "title": "Unsafe safety rewrite",
            "summary": "Attempt to modify protected safety file should fail.",
            "files": [{"path": "web/safety.py", "content": "# blocked\n"}],
        },
    )
    assert blocked.status_code == 409
    payload = blocked.get_json()
    assert payload["ok"] is False
    assert "blocked" in str(payload.get("error", "")).lower()


def test_self_improvement_approve_blocked_when_safe_mode_enabled(memory_client) -> None:
    client, _config = memory_client
    proposed = client.post(
        "/api/self_improvements/propose",
        json={
            "title": "Small refactor",
            "summary": "Prepare a simple merge candidate.",
            "files": [{"path": "agent/refactor_demo.py", "content": "x = 1\n"}],
        },
    )
    assert proposed.status_code == 200
    proposal_id = str(proposed.get_json()["data"]["id"])

    safe = client.post("/api/settings", json={"safe_mode": True})
    assert safe.status_code == 200
    assert safe.get_json()["data"]["safe_mode"] is True

    blocked = client.post(
        f"/api/self_improvements/{proposal_id}/decision",
        json={"decision": "approve"},
    )
    assert blocked.status_code == 409
    payload = blocked.get_json()
    assert payload["ok"] is False
    assert "safe mode" in str(payload.get("error", "")).lower()
