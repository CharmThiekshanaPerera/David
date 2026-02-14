from __future__ import annotations

import io
import queue

import pytest

flask = pytest.importorskip("flask")

from web.app import create_app


class FakeCenter:
    def __init__(self) -> None:
        self._subscribers = {}
        self._settings = {
            "safe_mode": False,
            "rate_limit_seconds": 3,
            "max_iterations_override": 0,
            "risky_large_edit_bytes": 50000,
            "risky_multi_file_threshold": 4,
            "run_preview_default": False,
            "model": "qwen2.5-coder:1.5b",
            "allowed_commands": ["python", "pytest"],
            "max_iterations_default": 8,
            "workspace_dir": "/tmp/workspace",
        }

    def get_status(self):
        return {
            "status": "idle",
            "active_run_id": None,
            "selected_model": "qwen2.5-coder:1.5b",
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
        return {"facts": [], "lessons": [], "conflicts": [], "conflict_count": 0}

    def telemetry_tail(self, limit=100):
        return {"events": [], "metrics": [], "summary": {}, "regressions": []}

    def logs_tail(self, limit=200):
        return {"web_control_center.log": []}

    def get_settings(self):
        return self._settings

    def update_settings(self, payload):
        self._settings.update(payload)
        return self._settings

    def list_approvals(self):
        return []

    def submit_approval(self, approval_id, decision, note=""):
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


def test_run_files_and_timeline_endpoints(client):
    files_response = client.get("/api/run/run_test_1/files")
    assert files_response.status_code == 200
    files_data = files_response.get_json()["data"]
    assert files_data["created"][0]["path"] == "hello.py"

    timeline_response = client.get("/api/run/run_test_1/timeline")
    assert timeline_response.status_code == 200
    timeline_data = timeline_response.get_json()["data"]
    assert timeline_data[0]["step"] == "run_started"


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
