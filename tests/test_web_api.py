from __future__ import annotations

import base64
import io
import queue

import pytest

flask = pytest.importorskip("flask")

from web.app import create_app


class FakeCenter:
    def __init__(self) -> None:
        self._subscribers = {}
        self._facts = []
        self._conversations = []
        self._legacy_archive = []
        self._pending_overwrites = {}
        self._self_improvements = []
        self._imported_bundles = {}
        self._uploads = {}
        self._settings = {
            "safe_mode": False,
            "rate_limit_seconds": 3,
            "max_iterations_override": 0,
            "risky_large_edit_bytes": 50000,
            "risky_multi_file_threshold": 4,
            "run_preview_default": False,
            "companion_mode": True,
            "memory_insight_mode": True,
            "parent_teaching_mode": False,
            "autonomous_self_improvement_mode": True,
            "demo_mode": False,
            "upload_vision_mode": False,
            "upload_vision_model": "",
            "voice_mode_enabled": False,
            "voice_text_only_mode": False,
            "voice_input_mode": "manual",
            "voice_continuous_mode": False,
            "voice_post_reply_delay_ms": 450,
            "voice_stop_phrases": ["stop listening", "end chat", "bye david"],
            "voice_vad_threshold": 0.035,
            "voice_vad_silence_ms": 900,
            "voice_vad_min_speech_ms": 300,
            "vad_threshold": 0.035,
            "vad_silence_ms": 900,
            "vad_min_speech_ms": 300,
            "voice_style": "warm",
            "voice_rate": 100,
            "voice_stt_engine": "none",
            "voice_stt_model": "base",
            "voice_stt_language": "en",
            "voice_stt_command": "whisper",
            "voice_whisper_cpp_command": "whisper-cli",
            "voice_whisper_cpp_model_path": "",
            "voice_tts_engine": "browser",
            "voice_tts_command": "piper",
            "voice_tts_model_path": "",
            "voice_chunk_chars": 180,
            "personality_warmth": 55,
            "personality_verbosity": 55,
            "personality_curiosity": 50,
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
            "pending_self_improvements": 0,
            "autonomous_self_improvement_mode": True,
            "demo_mode": bool(self._settings.get("demo_mode", False)),
            "legacy_archive_count": len(self._legacy_archive),
            "safe_mode": False,
            "rate_limit_seconds": 3,
            "allowed_commands": ["python", "pytest"],
            "metrics": {},
            "csrf_token": "test-token",
            "app_version": "dev",
            "git_commit": "abc1234",
            "version_stamp": "dev+abc1234",
            "imported_bundle_count": len(self._imported_bundles),
            "uploaded_file_count": len(self._uploads),
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
            "health_summary": {
                "iterations": 1,
                "iterations_until_green": 1,
                "elapsed_sec": 1.2,
                "approvals_count": 0,
                "planner_model_used": "qwen2.5-coder:1.5b",
                "coder_model_used": "qwen2.5-coder:1.5b",
                "critic_model_used": "qwen2.5-coder:1.5b",
                "top_error_category": "none",
                "memory_items_referenced": 0,
            },
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

    def import_run_bundle(self, *, file_name, content, actor="web_ui"):
        if not content:
            return False, {"error": "Bundle file is empty."}
        import_id = f"imp_test_{len(self._imported_bundles) + 1}"
        self._imported_bundles[import_id] = {
            "import_id": import_id,
            "run_id": "run_test_1",
            "source_filename": str(file_name or "bundle.zip"),
            "imported_at": "2026-01-01T00:00:00+00:00",
            "read_only": True,
            "meta": {
                "id": "run_test_1",
                "status": "success",
                "started_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:00:05+00:00",
            },
            "plan": {},
            "result": {"status": "success"},
            "timeline": [
                {"step": "run_started", "timestamp_utc": "2026-01-01T00:00:00+00:00", "payload": {}},
                {"step": "run_completed", "timestamp_utc": "2026-01-01T00:00:05+00:00", "payload": {"status": "success"}},
            ],
            "iterations": [
                {
                    "iteration": "001",
                    "coder": {},
                    "execution": [{"returncode": 0, "timed_out": False, "stdout": "ok", "stderr": ""}],
                    "critic": {},
                    "diffs": [{"path": "hello.py", "added": 1, "removed": 0, "change_type": "new"}],
                }
            ],
            "audit": [{"action": "approval_requested", "timestamp_utc": "2026-01-01T00:00:01+00:00", "payload": {}}],
            "file_summary": {
                "workspace_dir": "imported_bundle_read_only",
                "artifacts_dir": f"imported_bundle:{import_id}",
                "created": [{"path": "hello.py", "change_type": "new", "after_preview": "print('hi')"}],
                "modified": [],
                "workspace_files": [{"path": "hello.py", "after_preview": "print('hi')"}],
                "workspace_dirs": [],
                "workspace_file_total": 1,
                "workspace_dir_total": 0,
                "workspace_files_truncated": False,
                "read_only": True,
            },
            "bundle_manifest": {"version_stamp": "dev+abc1234"},
            "memory_snapshot_redacted": {"counts": {"facts": 0}},
            "health_summary": {
                "iterations": 1,
                "iterations_until_green": 1,
                "elapsed_sec": 5.0,
                "approvals_count": 1,
                "planner_model_used": "qwen2.5-coder:1.5b",
                "coder_model_used": "qwen2.5-coder:1.5b",
                "critic_model_used": "qwen2.5-coder:1.5b",
                "top_error_category": "none",
                "memory_items_referenced": 1,
            },
        }
        return True, {
            "import_id": import_id,
            "run_id": "run_test_1",
            "source_filename": str(file_name or "bundle.zip"),
            "imported_at": "2026-01-01T00:00:00+00:00",
            "read_only": True,
        }

    def list_imported_bundles(self, limit=120):
        rows = []
        for import_id, row in self._imported_bundles.items():
            rows.append(
                {
                    "import_id": import_id,
                    "run_id": row["run_id"],
                    "source_filename": row["source_filename"],
                    "imported_at": row["imported_at"],
                    "read_only": True,
                    "status": row["meta"]["status"],
                    "health_summary": row.get("health_summary", {}),
                }
            )
        return rows[: int(limit or 120)]

    def get_imported_bundle(self, import_id):
        row = self._imported_bundles.get(str(import_id))
        if not row:
            return None
        payload = dict(row)
        payload["artifacts_dir"] = f"imported_bundle:{import_id}"
        payload["workspace_dir"] = "imported_bundle_read_only"
        return payload

    def get_imported_bundle_timeline(self, import_id, limit=1000):
        row = self._imported_bundles.get(str(import_id))
        if not row:
            return None
        return list(row.get("timeline", []))[: int(limit or 1000)]

    def get_imported_bundle_audit(self, import_id, limit=1000):
        row = self._imported_bundles.get(str(import_id))
        if not row:
            return None
        return list(row.get("audit", []))[: int(limit or 1000)]

    def get_imported_bundle_files(self, import_id):
        row = self._imported_bundles.get(str(import_id))
        if not row:
            return None
        payload = dict(row.get("file_summary", {}))
        payload["read_only"] = True
        return payload

    def get_imported_bundle_replay(self, import_id, iteration):
        row = self._imported_bundles.get(str(import_id))
        if not row:
            return None
        return {
            "import_id": str(import_id),
            "run_id": "run_test_1",
            "iteration": 1,
            "total_iterations": 1,
            "has_prev": False,
            "has_next": False,
            "current": row.get("iterations", [])[0],
            "comparison": {"likely_failure_cause": None},
            "read_only": True,
        }

    def get_imported_bundle_compare(self, import_id, iteration):
        row = self._imported_bundles.get(str(import_id))
        if not row:
            return None
        return {
            "iteration": int(iteration or 1),
            "previous_iteration": None,
            "changed_files_current": ["hello.py"],
            "changed_files_previous": [],
            "newly_changed_files": ["hello.py"],
            "passed_previous": False,
            "passed_current": True,
            "likely_failure_cause": None,
            "read_only": True,
        }

    def upload_and_analyze_file(
        self,
        *,
        file_name,
        content,
        content_type="",
        actor="web_ui",
        use_vision=None,
        vision_model="",
    ):
        raw = bytes(content or b"")
        if not raw:
            return False, {"error": "Upload file is empty."}
        upload_id = f"upl_test_{len(self._uploads) + 1}"
        lower_name = str(file_name or "").lower()
        fmt = "csv" if lower_name.endswith(".csv") else "pdf" if lower_name.endswith(".pdf") else "unknown"
        kind = "table" if fmt == "csv" else "document"
        analysis = {
            "kind": kind,
            "format": fmt,
            "summary": f"Analyzed {fmt} file.",
            "headers": ["col_a", "col_b"] if fmt == "csv" else [],
            "sample_rows": [{"col_a": "East", "col_b": "120"}] if fmt == "csv" else [],
            "stats": {"rows": 1, "columns": 2} if fmt == "csv" else {"pages": 1},
            "warnings": [],
            "text_excerpt": "Budget East region grows" if fmt == "pdf" else "",
            "vision": {
                "requested": bool(use_vision),
                "status": "applied" if bool(use_vision) else "disabled",
                "model": str(vision_model or ""),
            },
        }
        row = {
            "upload_id": upload_id,
            "file_name": str(file_name or "upload.bin"),
            "content_type": str(content_type or ""),
            "size_bytes": len(raw),
            "uploaded_at": "2026-01-01T00:00:00+00:00",
            "actor": actor,
            "analysis": analysis,
        }
        self._uploads[upload_id] = row
        return True, row

    def list_uploaded_files(self, limit=120):
        rows = []
        for upload_id, row in self._uploads.items():
            analysis = row.get("analysis", {})
            rows.append(
                {
                    "upload_id": upload_id,
                    "file_name": row.get("file_name", ""),
                    "content_type": row.get("content_type", ""),
                    "size_bytes": row.get("size_bytes", 0),
                    "uploaded_at": row.get("uploaded_at", ""),
                    "actor": row.get("actor", "web_ui"),
                    "kind": analysis.get("kind", ""),
                    "format": analysis.get("format", ""),
                    "summary": analysis.get("summary", ""),
                }
            )
        return rows[: int(limit or 120)]

    def get_uploaded_file(self, upload_id):
        row = self._uploads.get(str(upload_id))
        if not row:
            return None
        return dict(row)

    def ask_uploaded_file(self, upload_id, question, actor="web_ui"):
        row = self._uploads.get(str(upload_id))
        if not row:
            return False, {"error": "Uploaded file not found."}
        q = str(question or "").strip()
        if not q:
            return False, {"error": "Question cannot be empty."}
        analysis = row.get("analysis", {})
        return True, {
            "upload_id": str(upload_id),
            "file_name": row.get("file_name", ""),
            "question": q,
            "answer": analysis.get("summary", "No analysis."),
            "confidence": 0.8,
            "evidence": [{"type": "sample_row"}],
            "analysis_summary": analysis.get("summary", ""),
            "actor": actor,
            "answered_at": "2026-01-01T00:00:01+00:00",
        }

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
        return {
            "facts": list(self._facts),
            "values": [],
            "projects": [],
            "lessons": [],
            "reflections": [],
            "legacy_archive": list(self._legacy_archive),
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "values_count": 0,
            "project_count": 0,
            "reflection_count": 0,
            "legacy_archive_count": len(self._legacy_archive),
        }

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
            "memory_insight": {
                "enabled": True,
                "summary": "This answer was influenced by Fact #1 (Father name).",
                "influences": [
                    {
                        "type": "fact",
                        "reference": "Fact #1",
                        "label": "Father name",
                        "detail": "David.father_name = Charm Thiekshana",
                    }
                ],
            },
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

    def chat_message(
        self,
        message,
        intent="",
        confirm_save=False,
        parent_teaching_mode=False,
        session_id="",
        actor="web_ui",
    ):
        text = str(message).strip()
        session = str(session_id or "session_test_1")
        chosen = str(intent or "").strip().lower()
        if chosen not in {"ask", "teach", "goal", "chat"}:
            if text.endswith("?") or text.lower().startswith(("who", "what", "how", "when", "where", "why")):
                chosen = "ask"
            else:
                chosen = "chat"

        user_turn = {
            "message_id": f"user_{len(self._conversations) + 1}",
            "session_id": session,
            "role": "user",
            "text": text,
            "intent": chosen,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }
        self._conversations.append(user_turn)

        if chosen == "ask":
            response = self.ask_memory(text, actor=actor)
            assistant_text = str(response.get("answer", ""))
            kind = "ask"
        elif chosen == "teach":
            if not confirm_save:
                response = {
                    "mode": "teach",
                    "status": "confirmation_required",
                    "message": text,
                    "triples": [{"subject": "David", "predicate": "father_name", "object": "Charm Thiekshana"}],
                    "requires_confirmation": True,
                    "session_id": session,
                }
                assistant_text = "Teach confirmation required."
                kind = "teach"
            else:
                teach_payload = self.teach_memory(text, confirm_conflict=False, actor=actor)
                if teach_payload.get("status") == "conflict":
                    overwrite_id = f"ow_{len(self._pending_overwrites) + 1}"
                    self._pending_overwrites[overwrite_id] = {"message": text}
                    response = {
                        "mode": "teach",
                        "status": "overwrite_confirmation_required",
                        "message": text,
                        "overwrite_id": overwrite_id,
                        "conflicts": teach_payload.get("conflicts", []),
                        "session_id": session,
                    }
                    assistant_text = "Overwrite confirmation required."
                else:
                    response = teach_payload
                    response["session_id"] = session
                    assistant_text = f"Saved {response.get('stored_count', 0)} facts."
                kind = "teach"
        elif chosen == "goal":
            ok, run = self.start_run({"command": f"/goal {text}"})
            response = {
                "mode": "goal",
                "status": "queued" if ok else "error",
                "run": run,
                "session_id": session,
            }
            assistant_text = "Goal queued." if ok else "Goal failed."
            kind = "system"
        else:
            response = {"mode": "chat", "status": "ok", "reply": "General chat response.", "session_id": session}
            assistant_text = "General chat response."
            kind = "system"

        assistant_turn = {
            "message_id": f"assistant_{len(self._conversations) + 1}",
            "session_id": session,
            "role": "assistant",
            "text": assistant_text,
            "intent": chosen,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }
        self._conversations.append(assistant_turn)

        return {
            "mode": "chat",
            "message": text,
            "detected_intent": chosen,
            "selected_intent": chosen,
            "confirm_save": bool(confirm_save),
            "parent_teaching_mode": bool(parent_teaching_mode),
            "session_id": session,
            "user_turn": user_turn,
            "assistant_turn": assistant_turn,
            "response": response,
            "kind": kind,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }

    def memory_facts(self, query="", limit=500):
        q = str(query or "").lower().strip()
        facts = list(self._facts)
        if q:
            facts = [row for row in facts if q in f"{row.get('subject', '')} {row.get('predicate', '')} {row.get('object', '')}".lower()]
        conflicts = self.memory_snapshot().get("conflicts", [])
        return {"facts": facts[:limit], "conflicts": conflicts, "conflict_count": len(conflicts), "total": len(facts)}

    def memory_conversations(self, session_id="", limit=500):
        sid = str(session_id or "").strip()
        rows = list(self._conversations)
        if sid:
            rows = [row for row in rows if str(row.get("session_id", "")) == sid]
        return {"conversations": rows[:limit], "session_id": sid, "total": len(rows)}

    def clear_conversations(self, session_id="", actor="web_ui"):
        sid = str(session_id or "").strip()
        if self._settings.get("safe_mode"):
            return False, {"error": "Safe mode is enabled. Conversation clearing is blocked in read-only mode."}
        before = len(self._conversations)
        if sid:
            self._conversations = [row for row in self._conversations if str(row.get("session_id", "")) != sid]
        else:
            self._conversations = []
        removed = before - len(self._conversations)
        return True, {
            "status": "cleared",
            "scope": "session" if sid else "all",
            "session_id": sid,
            "removed_count": removed,
            "remaining_count": len(self._conversations),
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }

    def chat_sessions(self, limit=120):
        sessions = {}
        for row in self._conversations:
            sid = str(row.get("session_id", "")).strip()
            if not sid:
                continue
            entry = sessions.setdefault(
                sid,
                {
                    "session_id": sid,
                    "started_at": row.get("timestamp_utc", ""),
                    "last_message_at": row.get("timestamp_utc", ""),
                    "message_count": 0,
                    "preview": "",
                },
            )
            entry["message_count"] += 1
            if str(row.get("role")) == "user" and row.get("text"):
                entry["preview"] = str(row.get("text"))
            if str(row.get("timestamp_utc", "")) > str(entry.get("last_message_at", "")):
                entry["last_message_at"] = row.get("timestamp_utc", "")
        return list(sessions.values())[:limit]

    def confirm_memory_overwrite(self, overwrite_id, decision="approve", actor="web_ui"):
        oid = str(overwrite_id).strip()
        if oid not in self._pending_overwrites:
            return False, {"error": "Overwrite request not found."}
        if str(decision).lower() != "approve":
            return True, {"mode": "teach", "status": "rejected", "overwrite_id": oid}
        pending = self._pending_overwrites.pop(oid)
        stored = self.teach_memory(pending.get("message", ""), confirm_conflict=True, actor=actor)
        stored["overwrite_id"] = oid
        return True, stored

    def telemetry_tail(self, limit=100):
        return {"events": [], "metrics": [], "summary": {}, "regressions": []}

    def growth_timeline(self, limit=120):
        return {
            "milestones": [
                {
                    "id": "run:run_test_1",
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "category": "project_success",
                    "title": "Successful Project Completion",
                    "details": "Run completed with passing tests.",
                    "learned": ["Keep tests green and focused."],
                    "metrics": {
                        "goal_runs_total": 1,
                        "goal_runs_success": 1,
                        "success_rate": 1.0,
                        "tdd_success_count": 0,
                        "avg_iterations_until_green": None,
                        "memory_size_total": len(self._facts),
                    },
                }
            ],
            "summary": {
                "goal_runs_total": 1,
                "goal_runs_success": 1,
                "success_rate": 1.0,
                "tdd_success_count": 0,
                "avg_iterations_until_green": None,
                "facts": len(self._facts),
                "lessons": 0,
                "reflections": 0,
                "memory_size_total": len(self._facts),
                "milestone_count": 1,
            },
        }

    def logs_tail(self, limit=200):
        return {"web_control_center.log": []}

    def get_settings(self):
        return self._settings

    def update_settings(self, payload):
        self._settings.update(payload)
        return self._settings

    def load_demo_data(self, force=False, actor="web_ui"):
        if not force and self._facts:
            return False, {"error": "Live data already exists.", "requires_confirmation": True}
        self._settings["demo_mode"] = True
        self._facts = [
            {
                "subject": "David",
                "predicate": "father_name",
                "object": "Charm Thiekshana",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
        return True, {
            "loaded": True,
            "demo_mode": True,
            "copied_runs": 4,
            "workspace_files_materialized": 8,
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "fixture_root": "/tmp/mock",
        }

    def reset_demo_data(self, actor="web_ui"):
        self._settings["demo_mode"] = True
        self._facts = [
            {
                "subject": "David",
                "predicate": "father_name",
                "object": "Charm Thiekshana",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
        return True, {
            "loaded": True,
            "reset": True,
            "demo_mode": True,
            "copied_runs": 4,
            "workspace_files_materialized": 8,
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "fixture_root": "/tmp/mock",
        }

    def list_ollama_models(self):
        return ["qwen2.5-coder:1.5b", "llama3.2:3b"]

    def list_legacy_archive(self, limit=200):
        items = list(self._legacy_archive)[: int(limit or 200)]
        return {
            "items": items,
            "total": len(self._legacy_archive),
            "boundary_note": "Legacy Archive is a reflective journal and not a substitute for real-world relationships.",
        }

    def mark_legacy_moment(self, payload, actor="web_ui"):
        summary = str(payload.get("summary", "")).strip()
        if not summary:
            return False, {"error": "summary cannot be empty."}
        entry = {
            "id": f"legacy_{len(self._legacy_archive) + 1}",
            "kind": "significant_moment",
            "source_type": str(payload.get("source_type", "manual")),
            "source_id": str(payload.get("source_id", "")),
            "summary": summary,
            "details": str(payload.get("details", "")),
            "timestamp_utc": str(payload.get("timestamp_utc", "2026-01-01T00:00:00+00:00")),
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "actor": actor,
            "metadata": payload.get("metadata", {}),
        }
        self._legacy_archive.insert(0, entry)
        return True, entry

    def remove_legacy_moment(self, entry_id, actor="web_ui"):
        clean_id = str(entry_id).strip()
        before = len(self._legacy_archive)
        self._legacy_archive = [row for row in self._legacy_archive if str(row.get("id", "")) != clean_id]
        if len(self._legacy_archive) == before:
            return False, {"error": "Archive entry not found."}
        return True, {
            "removed_id": clean_id,
            "removed": True,
            "total": len(self._legacy_archive),
            "actor": actor,
            "timestamp_utc": "2026-01-01T00:00:01+00:00",
        }

    def list_self_improvements(self, limit=160):
        rows = list(self._self_improvements)[: int(limit or 160)]
        pending = sum(1 for row in rows if str(row.get("status", "")) == "pending")
        merged = sum(1 for row in rows if str(row.get("status", "")) == "merged")
        autonomous = sum(1 for row in rows if bool((row.get("metadata") or {}).get("autonomous", False)))
        return {
            "items": rows,
            "total": len(self._self_improvements),
            "pending_count": pending,
            "merged_count": merged,
            "autonomous_count": autonomous,
            "sandbox_root": "/tmp/workspace/agent_sandbox",
        }

    def propose_self_improvement(self, payload, actor="david_agent"):
        if not str(payload.get("title", "")).strip():
            return False, {"error": "title cannot be empty."}
        proposal_id = f"improve_{len(self._self_improvements) + 1}"
        item = {
            "id": proposal_id,
            "title": str(payload.get("title", "")).strip(),
            "summary": str(payload.get("summary", "")).strip(),
            "status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "actor": actor,
            "sandbox_dir": f"/tmp/workspace/agent_sandbox/{proposal_id}",
            "changes": payload.get("files", []),
            "decision": None,
            "merge": None,
        }
        self._self_improvements.insert(0, item)
        return True, item

    def decide_self_improvement(self, proposal_id, decision, actor="web_ui", note=""):
        for idx, row in enumerate(self._self_improvements):
            if str(row.get("id")) != str(proposal_id):
                continue
            if row.get("status") != "pending":
                return False, {"error": "Proposal is already resolved."}
            choice = str(decision).lower()
            if choice not in {"approve", "reject"}:
                return False, {"error": "decision must be approve or reject."}
            updated = dict(row)
            updated["decision"] = {
                "decision": choice,
                "actor": actor,
                "note": note,
                "decided_at": "2026-01-01T00:00:01+00:00",
            }
            updated["status"] = "merged" if choice == "approve" else "rejected"
            updated["updated_at"] = "2026-01-01T00:00:01+00:00"
            if choice == "approve":
                updated["merge"] = {
                    "merged_at": "2026-01-01T00:00:01+00:00",
                    "actor": actor,
                    "file_count": len(updated.get("changes", [])),
                    "paths": [],
                }
            self._self_improvements[idx] = updated
            return True, updated
        return False, {"error": "Proposal not found."}

    def autonomous_self_improvement_cycle(self, trigger="manual", trigger_id="", actor="david_autonomous"):
        proposal_id = f"improve_auto_{len(self._self_improvements) + 1}"
        proposal = {
            "id": proposal_id,
            "title": "Autonomous Improvement: Iteration Efficiency",
            "summary": "Drafted from reflections.",
            "status": "pending",
            "created_at": "2026-01-02T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
            "actor": actor,
            "source": "self_improvement_engine",
            "sandbox_dir": f"/tmp/workspace/agent_sandbox/{proposal_id}",
            "proposal_doc": f"/tmp/workspace/agent_sandbox/{proposal_id}/PROPOSAL.md",
            "changes": [],
            "metadata": {"autonomous": True, "trigger": trigger, "trigger_id": trigger_id},
            "decision": None,
            "merge": None,
        }
        self._self_improvements.insert(0, proposal)
        return {
            "status": "proposed",
            "trigger": trigger,
            "trigger_id": trigger_id,
            "proposal_id": proposal_id,
            "proposal": proposal,
        }

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


def test_demo_load_and_reset_endpoints(client):
    load = client.post("/api/demo/load", json={"confirm_overwrite": True, "actor": "web_ui"})
    assert load.status_code == 200
    load_data = load.get_json()["data"]
    assert load_data["loaded"] is True
    assert load_data["demo_mode"] is True

    reset = client.post("/api/demo/reset", json={"actor": "web_ui"})
    assert reset.status_code == 200
    reset_data = reset.get_json()["data"]
    assert reset_data["loaded"] is True
    assert reset_data["reset"] is True


def test_growth_timeline_endpoint(client):
    response = client.get("/api/growth_timeline?limit=50")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["summary"]["goal_runs_total"] == 1
    assert data["milestones"][0]["category"] == "project_success"


def test_legacy_archive_mark_list_remove_endpoints(client):
    empty = client.get("/api/legacy_archive")
    assert empty.status_code == 200
    assert empty.get_json()["data"]["total"] == 0

    marked = client.post(
        "/api/legacy_archive",
        json={
            "source_type": "conversation",
            "source_id": "msg_1",
            "summary": "Shared a meaningful learning moment.",
            "details": "Conversation about growth and resilience.",
        },
    )
    assert marked.status_code == 200
    entry = marked.get_json()["data"]
    assert entry["kind"] == "significant_moment"
    assert entry["source_type"] == "conversation"

    listed = client.get("/api/legacy_archive")
    assert listed.status_code == 200
    listed_data = listed.get_json()["data"]
    assert listed_data["total"] == 1
    assert listed_data["items"][0]["id"] == entry["id"]

    removed = client.post(f"/api/legacy_archive/{entry['id']}/remove", json={})
    assert removed.status_code == 200
    assert removed.get_json()["data"]["removed"] is True

def test_self_improvements_propose_list_and_decide_endpoints(client):
    empty = client.get("/api/self_improvements")
    assert empty.status_code == 200
    assert empty.get_json()["data"]["total"] == 0

    created = client.post(
        "/api/self_improvements/propose",
        json={
            "title": "Improve memory retrieval",
            "summary": "Prototype a faster lookup path.",
            "files": [{"path": "agent/memory.py", "content": "print('demo')\n"}],
        },
    )
    assert created.status_code == 200
    created_data = created.get_json()["data"]
    assert created_data["status"] == "pending"

    listed = client.get("/api/self_improvements")
    assert listed.status_code == 200
    listed_data = listed.get_json()["data"]
    assert listed_data["total"] == 1
    proposal_id = listed_data["items"][0]["id"]

    approved = client.post(
        f"/api/self_improvements/{proposal_id}/decision",
        json={"decision": "approve", "note": "Looks safe to merge."},
    )
    assert approved.status_code == 200
    approved_data = approved.get_json()["data"]
    assert approved_data["status"] == "merged"
    assert approved_data["decision"]["decision"] == "approve"


def test_self_improvements_autonomous_cycle_endpoint(client):
    response = client.post("/api/self_improvements/autonomous_cycle", json={"trigger": "manual"})
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "proposed"
    assert payload["trigger"] == "manual"
    listed = client.get("/api/self_improvements")
    assert listed.status_code == 200
    listed_payload = listed.get_json()["data"]
    assert listed_payload["total"] >= 1
    assert listed_payload["autonomous_count"] >= 1


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


def test_run_bundle_export_endpoint(client):
    response = client.get("/api/run/run_test_1/bundle")
    assert response.status_code == 200
    assert response.mimetype == "application/zip"


def test_bundle_import_and_read_only_view_endpoints(client):
    upload = client.post(
        "/api/bundles/import",
        data={
            "actor": "web_ui",
            "bundle": (io.BytesIO(b"fake bundle bytes"), "run_bundle.zip"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    upload_data = upload.get_json()["data"]
    import_id = str(upload_data["import_id"])
    assert upload_data["read_only"] is True

    listed = client.get("/api/bundles/imports")
    assert listed.status_code == 200
    listed_rows = listed.get_json()["data"]
    assert any(str(row.get("import_id", "")) == import_id for row in listed_rows)

    details = client.get(f"/api/bundles/import/{import_id}")
    assert details.status_code == 200
    details_data = details.get_json()["data"]
    assert details_data["read_only"] is True
    assert details_data["run_id"] == "run_test_1"

    timeline = client.get(f"/api/bundles/import/{import_id}/timeline")
    assert timeline.status_code == 200
    assert isinstance(timeline.get_json()["data"], list)

    files = client.get(f"/api/bundles/import/{import_id}/files")
    assert files.status_code == 200
    files_data = files.get_json()["data"]
    assert files_data["read_only"] is True

    audit = client.get(f"/api/bundles/import/{import_id}/audit")
    assert audit.status_code == 200
    assert isinstance(audit.get_json()["data"], list)

    replay = client.get(f"/api/bundles/import/{import_id}/replay?iteration=1")
    assert replay.status_code == 200
    replay_data = replay.get_json()["data"]
    assert replay_data["read_only"] is True

    compare = client.get(f"/api/bundles/import/{import_id}/compare?iteration=1")
    assert compare.status_code == 200
    compare_data = compare.get_json()["data"]
    assert compare_data["iteration"] == 1


def test_upload_analyze_list_get_and_ask_endpoints(client):
    uploaded = client.post(
        "/api/uploads/analyze",
        data={
            "actor": "web_ui",
            "use_vision": "true",
            "vision_model": "llama3.2:3b",
            "file": (io.BytesIO(b"region,amount\nEast,120\n"), "sales.csv"),
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    upload_data = uploaded.get_json()["data"]
    upload_id = str(upload_data.get("upload_id", ""))
    assert upload_id.startswith("upl_")
    assert str((upload_data.get("analysis") or {}).get("format", "")) == "csv"
    vision_meta = (upload_data.get("analysis") or {}).get("vision", {})
    assert bool(vision_meta.get("requested")) is True
    assert str(vision_meta.get("model", "")) == "llama3.2:3b"

    listed = client.get("/api/uploads")
    assert listed.status_code == 200
    rows = listed.get_json()["data"]
    assert any(str(row.get("upload_id", "")) == upload_id for row in rows)

    details = client.get(f"/api/uploads/{upload_id}")
    assert details.status_code == 200
    details_data = details.get_json()["data"]
    assert str(details_data.get("upload_id", "")) == upload_id

    asked = client.post(
        f"/api/uploads/{upload_id}/ask",
        json={"question": "What is in this file?", "actor": "web_ui"},
    )
    assert asked.status_code == 200
    asked_data = asked.get_json()["data"]
    assert str(asked_data.get("upload_id", "")) == upload_id
    assert float(asked_data.get("confidence", 0.0)) > 0.0


def test_sse_endpoints_available(client):
    status_stream = client.get("/api/stream/status", buffered=False)
    try:
        assert status_stream.status_code == 200
        assert status_stream.mimetype == "text/event-stream"
    finally:
        status_stream.close()

    logs_stream = client.get("/api/stream/logs", buffered=False)
    try:
        assert logs_stream.status_code == 200
        assert logs_stream.mimetype == "text/event-stream"
    finally:
        logs_stream.close()

    run_stream = client.get("/api/stream/run/run_test_1", buffered=False)
    try:
        assert run_stream.status_code == 200
        assert run_stream.mimetype == "text/event-stream"
    finally:
        run_stream.close()


def _enable_voice_mode(client):
    response = client.post("/api/settings", json={"voice_mode_enabled": True})
    assert response.status_code == 200
    return response


def test_voice_transcribe_endpoint_requires_local_stt_setup(client):
    _enable_voice_mode(client)
    raw_audio = b"RIFF\x00\x00\x00\x00WAVEfmt "
    response = client.post(
        "/api/voice/transcribe",
        json={
            "audio_base64": base64.b64encode(raw_audio).decode("ascii"),
            "mime_type": "audio/wav",
        },
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Voice STT is disabled" in payload["error"]


def test_voice_endpoints_require_voice_mode_enabled(client):
    response = client.post("/api/voice/tts", json={"text": "hello"})
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Voice mode is disabled" in payload["error"]


def test_voice_tts_endpoint_returns_browser_engine_payload(client):
    _enable_voice_mode(client)
    response = client.post("/api/voice/tts", json={"text": "Hello from local voice mode."})
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["engine"] == "browser"
    assert payload["audio_base64"] == ""


def test_voice_tts_endpoint_rejects_text_too_long(client):
    _enable_voice_mode(client)
    response = client.post("/api/voice/tts", json={"text": "a" * 4001})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "text exceeds max length" in payload["error"]


def test_voice_chat_stream_requires_confirmation_for_goal(client):
    _enable_voice_mode(client)
    stream = client.post(
        "/api/voice/chat/stream",
        json={"message": "Build a TODO app with tests.", "intent": "goal", "confirm_sensitive": False},
        buffered=True,
    )
    assert stream.status_code == 200
    body = stream.get_data(as_text=True)
    assert "event: confirmation_required" in body
    assert "Voice goal execution requires explicit confirmation." in body


def test_voice_chat_stream_rejects_message_too_long(client):
    _enable_voice_mode(client)
    response = client.post(
        "/api/voice/chat/stream",
        json={"message": "x" * 4001, "intent": "ask", "confirm_sensitive": True},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "message exceeds max length" in payload["error"]


def test_voice_chat_stream_returns_final_event(client):
    _enable_voice_mode(client)
    stream = client.post(
        "/api/voice/chat/stream",
        json={
            "message": "Who is your father?",
            "intent": "ask",
            "confirm_sensitive": True,
            "text_only_mode": True,
            "turn_id": "turn_test_1",
        },
        buffered=True,
    )
    assert stream.status_code == 200
    assert stream.headers.get("Cache-Control") == "no-cache, no-transform"
    assert stream.headers.get("X-Accel-Buffering") == "no"
    body = stream.get_data(as_text=True)
    assert "event: assistant_final" in body
    assert "\"selected_intent\": \"ask\"" in body
    assert "\"turn_id\": \"turn_test_1\"" in body


def test_voice_diagnostics_endpoint_reports_readiness(client):
    response = client.get("/api/voice/diagnostics")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert "stt" in payload
    assert "tts" in payload
    assert isinstance(payload["stt"].get("ready"), bool)
    assert isinstance(payload["tts"].get("ready"), bool)


def test_voice_stream_ping_returns_sse(client):
    response = client.get("/api/voice/stream/ping", buffered=True)
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    body = response.get_data(as_text=True)
    assert "event: connected" in body


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


def test_chat_endpoint_requires_confirm_for_teach(client):
    response = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": False},
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["response"]["status"] == "confirmation_required"

    facts = client.get("/api/memory/facts")
    assert facts.status_code == 200
    assert facts.get_json()["data"]["total"] == 0


def test_chat_endpoint_forwards_parent_teaching_mode(client):
    response = client.post(
        "/api/chat",
        json={
            "message": "Always value patience.",
            "intent": "teach",
            "confirm_save": True,
            "parent_teaching_mode": True,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["parent_teaching_mode"] is True


def test_chat_teach_confirm_and_overwrite_flow(client):
    first = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Charm Thiekshana.", "intent": "teach", "confirm_save": True},
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["response"]["status"] == "stored"

    second = client.post(
        "/api/chat",
        json={"message": "Hi David I am your dad. My Name is Bob.", "intent": "teach", "confirm_save": True},
    )
    assert second.status_code == 200
    second_payload = second.get_json()["data"]["response"]
    assert second_payload["status"] == "overwrite_confirmation_required"
    overwrite_id = second_payload["overwrite_id"]

    confirm = client.post(
        "/api/memory/confirm_overwrite",
        json={"overwrite_id": overwrite_id, "decision": "approve"},
    )
    assert confirm.status_code == 200
    confirm_payload = confirm.get_json()["data"]
    assert confirm_payload["status"] == "stored"


def test_memory_conversations_and_sessions_endpoints(client):
    chat = client.post("/api/chat", json={"message": "Who is your father?", "intent": "ask"})
    assert chat.status_code == 200
    session_id = chat.get_json()["data"]["session_id"]

    conv = client.get(f"/api/memory/conversations?session_id={session_id}")
    assert conv.status_code == 200
    conv_payload = conv.get_json()["data"]
    assert conv_payload["session_id"] == session_id
    assert conv_payload["total"] >= 2

    sessions = client.get("/api/chat/sessions")
    assert sessions.status_code == 200
    session_rows = sessions.get_json()["data"]
    assert any(str(item.get("session_id")) == session_id for item in session_rows)


def test_memory_clear_conversations_endpoint(client):
    first = client.post("/api/chat", json={"message": "Question 1?", "intent": "ask", "session_id": "session_a"})
    assert first.status_code == 200
    second = client.post("/api/chat", json={"message": "Question 2?", "intent": "ask", "session_id": "session_b"})
    assert second.status_code == 200

    clear_session = client.post("/api/memory/conversations/clear", json={"session_id": "session_a"})
    assert clear_session.status_code == 200
    clear_data = clear_session.get_json()["data"]
    assert clear_data["scope"] == "session"
    assert clear_data["session_id"] == "session_a"
    assert int(clear_data["removed_count"]) >= 2

    session_a_rows = client.get("/api/memory/conversations?session_id=session_a").get_json()["data"]
    session_b_rows = client.get("/api/memory/conversations?session_id=session_b").get_json()["data"]
    assert int(session_a_rows["total"]) == 0
    assert int(session_b_rows["total"]) >= 2

    clear_all = client.post("/api/memory/conversations/clear", json={})
    assert clear_all.status_code == 200
    clear_all_data = clear_all.get_json()["data"]
    assert clear_all_data["scope"] == "all"

    all_rows = client.get("/api/memory/conversations").get_json()["data"]
    assert int(all_rows["total"]) == 0
