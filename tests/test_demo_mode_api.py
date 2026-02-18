from __future__ import annotations

import json
import shutil
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


def _copy_mock_fixtures(data_root: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "mock"
    target = data_root / "mock"
    shutil.copytree(source, target, dirs_exist_ok=True)


@pytest.fixture
def demo_client(tmp_path: Path):
    config = _make_config(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    _copy_mock_fixtures(data_root)
    center = DavidControlCenter(config=config, data_root=data_root)
    center.update_settings({"demo_mode": True})
    app = create_app(control_center=center)
    app.config.update(TESTING=True)
    return app.test_client(), center


def test_demo_mode_endpoint_shapes(demo_client) -> None:
    client, _center = demo_client

    status = client.get("/api/status")
    assert status.status_code == 200
    status_data = status.get_json()["data"]
    assert status_data["demo_mode"] is True

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    settings_data = settings.get_json()["data"]
    assert settings_data["demo_mode"] is True
    assert settings_data["ui_theme_default"] == "dark"
    assert settings_data["ui_background_enabled"] is True

    models = client.get("/api/models")
    assert models.status_code == 200
    model_rows = models.get_json()["data"]["models"]
    assert isinstance(model_rows, list)
    assert len(model_rows) >= 1

    runs = client.get("/api/runs")
    assert runs.status_code == 200
    run_rows = runs.get_json()["data"]
    assert isinstance(run_rows, list)
    assert len(run_rows) >= 3
    run_id = str(run_rows[0]["id"])

    run_details = client.get(f"/api/run/{run_id}")
    assert run_details.status_code == 200
    details_payload = run_details.get_json()["data"]
    assert "meta" in details_payload
    assert "timeline" in details_payload
    assert "file_summary" in details_payload

    timeline = client.get(f"/api/run/{run_id}/timeline")
    assert timeline.status_code == 200
    assert isinstance(timeline.get_json()["data"], list)

    files = client.get(f"/api/run/{run_id}/files")
    assert files.status_code == 200
    files_data = files.get_json()["data"]
    assert "workspace_files" in files_data
    assert "workspace_dirs" in files_data

    audit = client.get(f"/api/run/{run_id}/audit")
    assert audit.status_code == 200
    assert isinstance(audit.get_json()["data"], list)

    ask = client.post(
        "/api/ask",
        json={"question": "What did you learn about tests and explanations?", "actor": "web_ui"},
    )
    assert ask.status_code == 200
    ask_data = ask.get_json()["data"]
    assert ask_data["mode"] == "ask"
    assert isinstance(ask_data["citations"], list)
    citation_types = {str(item.get("type", "")) for item in ask_data["citations"] if isinstance(item, dict)}
    assert "fact" in citation_types
    assert "lesson" in citation_types

    chat = client.post("/api/chat", json={"message": "Who is your father?"})
    assert chat.status_code == 200
    chat_data = chat.get_json()["data"]
    assert chat_data["mode"] == "chat"
    assert chat_data["selected_intent"] == "ask"
    assert "response" in chat_data


def test_demo_mode_ui_behavior_signals(demo_client) -> None:
    client, _center = demo_client

    ask_like = client.post("/api/chat", json={"message": "Who is your father?"})
    assert ask_like.status_code == 200
    ask_payload = ask_like.get_json()["data"]
    assert ask_payload["detected_intent"] == "ask"
    assert ask_payload["selected_intent"] == "ask"
    ask_response = ask_payload["response"]
    assert isinstance(ask_response.get("citations", []), list)
    assert "Charm Thiekshana" in str(ask_response.get("answer", ""))

    no_match = client.post("/api/ask", json={"question": "Explain the quarkonium hypergraph sentinel protocol."})
    assert no_match.status_code == 200
    no_match_data = no_match.get_json()["data"]
    assert int(no_match_data.get("matched_count", 0)) == 0
    assert int(no_match_data.get("lesson_match_count", 0)) == 0
    assert int(no_match_data.get("values_match_count", 0)) == 0

    teach_preview = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Bob.", "intent": "teach", "confirm_save": False},
    )
    assert teach_preview.status_code == 200
    preview_response = teach_preview.get_json()["data"]["response"]
    assert preview_response["status"] == "confirmation_required"
    assert isinstance(preview_response.get("triples", []), list)
    assert preview_response.get("requires_confirmation") is True

    teach_conflict = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Bob.", "intent": "teach", "confirm_save": True},
    )
    assert teach_conflict.status_code == 200
    conflict_response = teach_conflict.get_json()["data"]["response"]
    assert conflict_response["status"] == "overwrite_confirmation_required"
    overwrite_id = str(conflict_response.get("overwrite_id", "")).strip()
    assert overwrite_id

    overwrite_confirm = client.post(
        "/api/memory/confirm_overwrite",
        json={"overwrite_id": overwrite_id, "decision": "approve", "actor": "web_ui"},
    )
    assert overwrite_confirm.status_code == 200
    overwrite_data = overwrite_confirm.get_json()["data"]
    assert overwrite_data["status"] == "stored"

    ask_updated = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask_updated.status_code == 200
    updated_answer = ask_updated.get_json()["data"]["answer"]
    assert "Bob" in str(updated_answer)


def test_demo_mode_approvals_and_replay_compare(demo_client) -> None:
    client, _center = demo_client

    approvals = client.get("/api/approvals")
    assert approvals.status_code == 200
    pending = [row for row in approvals.get_json()["data"] if str(row.get("status", "")) == "pending"]
    assert pending
    typed = next((row for row in pending if bool(row.get("requires_typed_confirmation"))), None)
    assert typed is not None
    approval_id = str(typed["id"])
    run_id = str(typed["run_id"])

    reject_missing_typed = client.post(
        f"/api/approval/{approval_id}",
        json={"decision": "approve", "actor": "web_ui"},
    )
    assert reject_missing_typed.status_code == 409
    assert "Typed confirmation required" in reject_missing_typed.get_json()["error"]

    approve_typed = client.post(
        f"/api/approval/{approval_id}",
        json={"decision": "approve", "actor": "web_ui", "confirmation": f"approve {run_id}"},
    )
    assert approve_typed.status_code == 200
    assert approve_typed.get_json()["data"]["decision"] == "approve"

    audit = client.get(f"/api/run/{run_id}/audit")
    assert audit.status_code == 200
    audit_rows = audit.get_json()["data"]
    assert any(str(row.get("action", "")) == "approval_decision" for row in audit_rows if isinstance(row, dict))

    replay_first = client.get("/api/run/run_20260210T101500_a1b2c3d4/replay?iteration=1")
    assert replay_first.status_code == 200
    replay_first_data = replay_first.get_json()["data"]
    assert replay_first_data["has_prev"] is False
    assert replay_first_data["has_next"] is True

    replay_last = client.get("/api/run/run_20260210T101500_a1b2c3d4/replay?iteration=3")
    assert replay_last.status_code == 200
    replay_last_data = replay_last.get_json()["data"]
    assert replay_last_data["has_prev"] is True

    compare = client.get("/api/run/run_20260211T113000_b2c3d4e5/compare?iteration=2")
    assert compare.status_code == 200
    compare_data = compare.get_json()["data"]
    assert compare_data["passed_previous"] is True
    assert compare_data["passed_current"] is False
    assert isinstance(compare_data.get("likely_failure_cause"), dict)

    tree = client.get("/api/workspace/tree")
    assert tree.status_code == 200
    entries = tree.get_json()["data"]["entries"]
    folder_paths = {str(item.get("path", "")) for item in entries if str(item.get("type", "")) == "folder"}
    assert any(path.startswith("projects/") and path.endswith("/src") for path in folder_paths)
    assert any(path.startswith("projects/") and path.endswith("/tests") for path in folder_paths)


def test_demo_load_and_reset_endpoints_require_confirmation(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    _copy_mock_fixtures(data_root)
    center = DavidControlCenter(config=config, data_root=data_root)

    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["facts"] = [
        {
            "subject": "User",
            "predicate": "name",
            "object": "Live Data",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")

    app = create_app(control_center=center)
    app.config.update(TESTING=True)
    client = app.test_client()

    blocked = client.post("/api/demo/load", json={"confirm_overwrite": False, "actor": "web_ui"})
    assert blocked.status_code == 409
    blocked_payload = blocked.get_json()
    assert blocked_payload["ok"] is False
    assert blocked_payload["requires_confirmation"] is True

    loaded = client.post("/api/demo/load", json={"confirm_overwrite": True, "actor": "web_ui"})
    assert loaded.status_code == 200
    loaded_data = loaded.get_json()["data"]
    assert loaded_data["loaded"] is True
    assert loaded_data["demo_mode"] is True

    reset = client.post("/api/demo/reset", json={"actor": "web_ui"})
    assert reset.status_code == 200
    reset_data = reset.get_json()["data"]
    assert reset_data["loaded"] is True
    assert reset_data["reset"] is True
