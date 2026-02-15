from __future__ import annotations

import io
import queue

import pytest

flask = pytest.importorskip("flask")

from web.app import create_app


class FakeCenter:
    def __init__(self) -> None:
        self._subscribers = {}
        self._facts = []
        self._settings = {
            "safe_mode": False,
            "rate_limit_seconds": 3,
            "max_iterations_override": 0,
            "risky_large_edit_bytes": 50000,
            "risky_multi_file_threshold": 4,
            "run_preview_default": False,
            "model": "qwen2.5-coder:1.5b",
            "planner_model": "qwen2.5-coder:1.5b",
            "coder_model": "qwen2.5-coder:1.5b",
            "critic_model": "qwen2.5-coder:1.5b",
            "planner_model_default": "qwen2.5-coder:1.5b",
            "coder_model_default": "qwen2.5-coder:1.5b",
            "critic_model_default": "qwen2.5-coder:1.5b",
            "tdd_mode": False,
            "allowed_commands": ["python", "pytest"],
            "max_iterations_default": 8,
            "workspace_dir": "/tmp/workspace",
            "goal_templates": [],
        }

    def get_status(self):
        return {
            "status": "idle",
            "active_run_id": None,
            "selected_model": "qwen2.5-coder:1.5b",
            "planner_model_used": "qwen2.5-coder:1.5b",
            "coder_model_used": "qwen2.5-coder:1.5b",
            "critic_model_used": "qwen2.5-coder:1.5b",
            "tdd_mode": False,
            "iterations_until_green": None,
            "iteration": 0,
            "max_iterations": 8,
            "progress_percent": 0,
            "last_command": "",
            "latest_success": None,
            "latest_message": "",
            "pending_approvals": 0,
            "safe_mode": False,
            "rate_limit_seconds": 3,
            "allowed_commands": ["python", "pytest"],
            "metrics": {},
            "csrf_token": "test-token",
        }

    def get_csrf_token(self):
        return "test-token"

    def subscribe(self, channel):
        q = queue.Queue()
        q.put({"type": "connected", "channel": channel})
        self._subscribers.setdefault(channel, []).append(q)
        return q

    def unsubscribe(self, channel, q):
        rows = self._subscribers.get(channel, [])
        if q in rows:
            rows.remove(q)

    def start_run(self, payload):
        command = str(payload.get("command", ""))
        if command.startswith("/goal ") or command.startswith("/ask ") or command.startswith("/teach "):
            return True, {"run_id": "run_test_1", "status": "queued"}
        return False, {"error": "Only /goal, /ask, and /teach are allowed."}

    def stop_active_run(self):
        return {"stopped": False, "error": "No active run."}

    def get_runs(self, search="", status="", limit=100):
        return [
            {
                "id": "run_test_1",
                "mode": "goal",
                "status": "success",
                "started_at": "2026-01-01T00:00:00+00:00",
                "message": "ok",
                "command": "/goal demo",
            }
        ]

    def get_run(self, run_id):
        if run_id != "run_test_1":
            return None
        return {
            "meta": {
                "id": "run_test_1",
                "status": "success",
                "failure_explanation": "",
            },
            "plan": {},
            "result": {"status": "success"},
            "timeline": [],
            "iterations": [],
            "approvals": [],
        }

    def get_run_timeline(self, run_id, limit=1000):
        if run_id != "run_test_1":
            return None
        return [{"step": "run_started", "timestamp_utc": "2026-01-01T00:00:00+00:00", "payload": {}}]

    def get_run_files(self, run_id):
        if run_id != "run_test_1":
            return None
        return {
            "artifacts_dir": "/tmp/data/runs/run_test_1",
            "workspace_dir": "/tmp/workspace",
            "created": [{"path": "hello.py", "change_type": "new", "after_preview": "print('hi')"}],
            "modified": [],
            "workspace_files": [{"path": "projects/demo/hello.py", "change_type": "workspace", "after_preview": "print('hi')"}],
            "workspace_dirs": ["projects", "projects/demo"],
            "workspace_file_total": 1,
            "workspace_dir_total": 2,
            "workspace_files_truncated": False,
        }

    def workspace_tree(self, limit=20000):
        return {
            "workspace_dir": "/tmp/workspace",
            "entries": [
                {"path": "projects", "type": "folder"},
                {"path": "projects/demo", "type": "folder"},
                {"path": "projects/demo/hello.py", "type": "file"},
            ],
            "file_total": 1,
            "dir_total": 2,
            "truncated": False,
        }

    def workspace_edit_file(self, relative_path, content, actor="web_ui"):
        return {
            "action": "edit_file",
            "path": str(relative_path),
            "workspace_path": f"/tmp/workspace/{relative_path}",
            "size_bytes": len(str(content).encode("utf-8")),
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }

    def workspace_delete_path(self, relative_path, actor="web_ui"):
        return {
            "action": "delete_path",
            "path": str(relative_path),
            "path_type": "folder" if str(relative_path).endswith("/") else "file",
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }

    def workspace_rename_path(self, relative_path, new_relative_path, actor="web_ui"):
        return {
            "action": "rename_path",
            "from_path": str(relative_path),
            "to_path": str(new_relative_path),
            "path_type": "folder",
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }

    def get_run_audit(self, run_id, limit=1000):
        if run_id != "run_test_1":
            return None
        return [{"action": "approval_requested", "timestamp_utc": "2026-01-01T00:00:00+00:00", "payload": {}}]

    def get_run_replay(self, run_id, iteration):
        if run_id != "run_test_1":
            return None
        return {
            "run_id": run_id,
            "iteration": 1,
            "total_iterations": 1,
            "has_prev": False,
            "has_next": False,
            "current": {"coder": {}, "execution": [], "critic": {}, "diffs": []},
            "comparison": {"likely_failure_cause": None},
        }

    def compare_iterations(self, run_id, iteration):
        if run_id != "run_test_1":
            return None
        return {
            "iteration": 1,
            "previous_iteration": None,
            "changed_files_current": [],
            "changed_files_previous": [],
            "newly_changed_files": [],
            "passed_previous": False,
            "passed_current": True,
            "likely_failure_cause": None,
        }

    def retry_run(self, run_id):
        if run_id == "run_test_1":
            return True, {"run_id": "run_test_retry", "status": "queued"}
        return False, {"error": "Run not found."}

    def run_bundle_zip(self, run_id):
        if run_id != "run_test_1":
            return None
        return io.BytesIO(b"PK")

    def memory_snapshot(self):
        conflicts = []
        for fact in self._facts:
            subject = str(fact.get("subject", "")).lower()
            predicate = str(fact.get("predicate", "")).lower()
            values = sorted(
                {
                    row.get("object")
                    for row in self._facts
                    if str(row.get("subject", "")).lower() == subject and str(row.get("predicate", "")).lower() == predicate
                }
            )
            if len(values) > 1:
                conflicts.append({"subject": subject, "predicate": predicate, "values": values})
        return {"facts": list(self._facts), "lessons": [], "conflicts": conflicts, "conflict_count": len(conflicts)}

    def ask_memory(self, question, actor="web_ui"):
        q = str(question).strip()
        father = None
        for row in reversed(self._facts):
            if str(row.get("subject", "")).lower() == "david" and str(row.get("predicate", "")).lower() == "father_name":
                father = row.get("object")
                break
        answer = f"My father is {father}." if father and "father" in q.lower() else 'I do not know yet. Please teach me using --teach "...".'
        return {
            "mode": "ask",
            "question": q,
            "answer": answer,
            "matched_facts": list(self._facts[-8:]),
            "matched_count": len(self._facts[-8:]),
            "actor": actor,
        }

    def teach_memory(self, message, confirm_conflict=False, actor="web_ui"):
        text = str(message).strip()
        lower = text.lower()
        fact = None
        if "my name is charm" in lower:
            fact = {"subject": "David", "predicate": "father_name", "object": "Charm Thiekshana", "timestamp": "2026-01-01T00:00:00+00:00"}
        elif "my name is bob" in lower:
            fact = {"subject": "David", "predicate": "father_name", "object": "Bob", "timestamp": "2026-01-01T00:00:00+00:00"}

        conflicts = []
        if fact:
            for row in self._facts:
                if (
                    str(row.get("subject", "")).lower() == str(fact["subject"]).lower()
                    and str(row.get("predicate", "")).lower() == str(fact["predicate"]).lower()
                    and str(row.get("object", "")).lower() != str(fact["object"]).lower()
                ):
                    conflicts.append(
                        {
                            "subject": fact["subject"],
                            "predicate": fact["predicate"],
                            "existing": row.get("object"),
                            "incoming": fact["object"],
                        }
                    )
                    break

        if conflicts and not confirm_conflict:
            return {
                "mode": "teach",
                "status": "conflict",
                "message": text,
                "requires_confirmation": True,
                "stored_facts": [],
                "stored_count": 0,
                "skipped_items": [],
                "notes": "Conflict detected. Confirm to continue.",
                "conflicts": conflicts,
                "actor": actor,
            }

        stored = []
        if fact:
            self._facts.append(fact)
            stored = [fact]
        return {
            "mode": "teach",
            "status": "stored",
            "message": text,
            "requires_confirmation": False,
            "confirmed_conflict": bool(conflicts),
            "stored_facts": stored,
            "stored_count": len(stored),
            "skipped_items": [],
            "notes": "",
            "conflicts": conflicts,
            "actor": actor,
        }

    def telemetry_tail(self, limit=100):
        return {"events": [], "metrics": [], "summary": {}, "regressions": []}

    def logs_tail(self, limit=200):
        return {"web_control_center.log": []}

    def get_settings(self):
        return self._settings

    def update_settings(self, payload):
        self._settings.update(payload)
        return self._settings

    def list_ollama_models(self):
        return ["qwen2.5-coder:1.5b", "llama3.2:3b"]

    def list_approvals(self):
        return []

    def submit_approval(self, approval_id, decision, note="", actor="local_user", confirmation=""):
        if decision == "approve":
            return True, {"approval_id": approval_id, "decision": "approve"}
        return False, {"error": "Approval request not found."}


@pytest.fixture
def client():
    app = create_app(control_center=FakeCenter())
    app.config.update(TESTING=True)
    return app.test_client()


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "idle"


def test_run_endpoint_rejects_invalid_command(client):
    response = client.post("/api/run", json={"command": "ls -la"})
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Only /goal" in payload["error"]


def test_run_and_details_endpoints(client):
    run_response = client.post("/api/run", json={"command": "/goal build test"})
    assert run_response.status_code == 200
    assert run_response.get_json()["data"]["run_id"] == "run_test_1"

    details = client.get("/api/run/run_test_1")
    assert details.status_code == 200
    assert details.get_json()["data"]["meta"]["id"] == "run_test_1"


def test_memory_endpoint(client):
    response = client.get("/api/memory")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["conflict_count"] == 0


def test_models_endpoint(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "qwen2.5-coder:1.5b" in payload["data"]["models"]


def test_run_files_and_timeline_endpoints(client):
    files_response = client.get("/api/run/run_test_1/files")
    assert files_response.status_code == 200
    files_data = files_response.get_json()["data"]
    assert files_data["created"][0]["path"] == "hello.py"

    timeline_response = client.get("/api/run/run_test_1/timeline")
    assert timeline_response.status_code == 200
    timeline_data = timeline_response.get_json()["data"]
    assert timeline_data[0]["step"] == "run_started"


def test_workspace_edit_delete_rename_endpoints(client):
    edit_response = client.post("/api/workspace/file/edit", json={"path": "projects/demo/main.py", "content": "print('ok')\n"})
    assert edit_response.status_code == 200
    edit_data = edit_response.get_json()["data"]
    assert edit_data["action"] == "edit_file"
    assert edit_data["path"] == "projects/demo/main.py"

    delete_response = client.post("/api/workspace/path/delete", json={"path": "projects/demo/main.py"})
    assert delete_response.status_code == 200
    delete_data = delete_response.get_json()["data"]
    assert delete_data["action"] == "delete_path"
    assert delete_data["path"] == "projects/demo/main.py"

    rename_response = client.post(
        "/api/workspace/path/rename",
        json={"path": "projects/demo", "new_path": "projects/demo_renamed"},
    )
    assert rename_response.status_code == 200
    rename_data = rename_response.get_json()["data"]
    assert rename_data["action"] == "rename_path"
    assert rename_data["from_path"] == "projects/demo"
    assert rename_data["to_path"] == "projects/demo_renamed"


def test_workspace_tree_endpoint(client):
    response = client.get("/api/workspace/tree")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["workspace_dir"] == "/tmp/workspace"
    assert payload["file_total"] == 1
    assert payload["dir_total"] == 2
    assert {"path": "projects/demo/hello.py", "type": "file"} in payload["entries"]


def test_replay_compare_and_audit_endpoints(client):
    replay = client.get("/api/run/run_test_1/replay?iteration=1")
    assert replay.status_code == 200

    compare = client.get("/api/run/run_test_1/compare?iteration=1")
    assert compare.status_code == 200

    audit = client.get("/api/run/run_test_1/audit")
    assert audit.status_code == 200


def test_sse_endpoints_available(client):
    status_stream = client.get("/api/stream/status", buffered=False)
    assert status_stream.status_code == 200
    assert status_stream.mimetype == "text/event-stream"

    logs_stream = client.get("/api/stream/logs", buffered=False)
    assert logs_stream.status_code == 200
    assert logs_stream.mimetype == "text/event-stream"

    run_stream = client.get("/api/stream/run/run_test_1", buffered=False)
    assert run_stream.status_code == 200
    assert run_stream.mimetype == "text/event-stream"


def test_approval_endpoint(client):
    response = client.post("/api/approval/approval_1", json={"decision": "approve"})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_ask_endpoint(client):
    teach = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Charm Thiekshana."})
    assert teach.status_code == 200

    ask = client.post("/api/ask", json={"question": "Who is your father?"})
    assert ask.status_code == 200
    payload = ask.get_json()["data"]
    assert payload["mode"] == "ask"
    assert "Charm Thiekshana" in payload["answer"]


def test_teach_endpoint_conflict_confirmation(client):
    first = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Charm Thiekshana."})
    assert first.status_code == 200
    assert first.get_json()["data"]["status"] == "stored"

    conflict = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Bob."})
    assert conflict.status_code == 200
    conflict_payload = conflict.get_json()["data"]
    assert conflict_payload["status"] == "conflict"
    assert conflict_payload["requires_confirmation"] is True

    confirmed = client.post("/api/teach", json={"message": "Hi David I am your dad. My Name is Bob.", "confirm_conflict": True})
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.get_json()["data"]
    assert confirmed_payload["status"] == "stored"
    assert confirmed_payload["confirmed_conflict"] is True
