from __future__ import annotations

import difflib
import io
import json
import logging
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agent.config import AgentConfig, load_config, sanitize_model_name
from agent.contracts import CoderOutput, CriticOutput, ExecutionResult, LessonProposal
from agent.coder import Coder
from agent.critic import Critic
from agent.llm import OllamaClient
from agent.main import parse_chat_command
from agent.memory import LongTermMemory
from agent.planner import Planner
from agent.projects import ensure_workspace_layout, prepare_project_for_goal
from agent.qa import MemoryTeacherQA
from agent.safety import SafetyError, SafetyGuard, ValidatedEdit
from agent.telemetry import IterationMetric, TelemetryLogger
from agent.workspace import WorkspaceInspector
from agent.executor import RestrictedExecutor


RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{6,80}$")
GOAL_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "build_cli_tool",
        "name": "Build CLI Tool",
        "description": "Build modular CLI app with tests and clean structure.",
        "goal": (
            "Build a modular Python CLI app inside the active project with clear package structure, "
            "argument parsing, and pytest coverage for core flows."
        ),
        "tdd_mode": False,
    },
    {
        "id": "bug_fix_mode",
        "name": "Bug Fix Mode",
        "description": "Analyze failing test, isolate root cause, fix only related code.",
        "goal": (
            "Analyze the failing tests, isolate the root cause, and apply a minimal fix "
            "without rewriting unrelated files. Keep regression risk low."
        ),
        "tdd_mode": False,
    },
    {
        "id": "refactor_mode",
        "name": "Refactor Mode",
        "description": "Improve readability, add docstrings, and increase test coverage.",
        "goal": (
            "Refactor the target module for readability, add useful docstrings, and improve "
            "test coverage while preserving behavior."
        ),
        "tdd_mode": False,
    },
    {
        "id": "strict_tdd_mode",
        "name": "Strict TDD Mode",
        "description": "Write failing tests first, then implement until tests pass.",
        "goal": (
            "Use strict TDD: write failing tests first under tests/ in the active project, do not implement "
            "production code until tests fail, then iterate to green."
        ),
        "tdd_mode": True,
    },
]


@dataclass
class ControlSettings:
    safe_mode: bool = False
    rate_limit_seconds: int = 3
    max_iterations_override: int = 0
    risky_large_edit_bytes: int = 50_000
    risky_multi_file_threshold: int = 4
    run_preview_default: bool = False
    planner_model: str = ""
    coder_model: str = ""
    critic_model: str = ""
    tdd_mode: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlSettings":
        planner_model = str(data.get("planner_model", "")).strip()
        coder_model = str(data.get("coder_model", "")).strip()
        critic_model = str(data.get("critic_model", "")).strip()
        return cls(
            safe_mode=bool(data.get("safe_mode", False)),
            rate_limit_seconds=max(0, int(data.get("rate_limit_seconds", 3))),
            max_iterations_override=max(0, int(data.get("max_iterations_override", 0))),
            risky_large_edit_bytes=max(1_000, int(data.get("risky_large_edit_bytes", 50_000))),
            risky_multi_file_threshold=max(2, int(data.get("risky_multi_file_threshold", 4))),
            run_preview_default=bool(data.get("run_preview_default", False)),
            planner_model=planner_model,
            coder_model=coder_model,
            critic_model=critic_model,
            tdd_mode=bool(data.get("tdd_mode", False)),
        )


@dataclass
class DiffEntry:
    path: str
    added: int
    removed: int
    patch: str
    change_type: str
    workspace_path: str
    before_preview: str
    after_preview: str


class DavidControlCenter:
    """Coordinates local-only web control operations for David."""

    def __init__(self, config: AgentConfig | None = None, data_root: Path | None = None) -> None:
        self.config = config or load_config()
        self.project_root = self.config.project_root
        self.data_root = (data_root or (self.project_root / "data")).resolve()
        self.runs_root = (self.data_root / "runs").resolve()
        self.settings_file = (self.data_root / "control_settings.json").resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._active_thread: threading.Thread | None = None
        self._active_run_id: str | None = None
        self._active_cancel: threading.Event | None = None
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._last_run_started_at: float = 0.0
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {"status": [], "logs": []}
        self._csrf_token = uuid.uuid4().hex

        self._logger = logging.getLogger("david.control_center")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.FileHandler(self.config.logs_dir / "web_control_center.log", encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

        self.settings = self._load_settings()
        self._validate_role_models()
        ensure_workspace_layout(self.config.workspace_dir)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            active = self._active_run_id
            pending_count = len([p for p in self._pending_approvals.values() if p.get("status") == "pending"])

        current_meta = self._read_run_meta(active) if active else None
        runs = self.get_runs(limit=30)
        latest = runs[0] if runs else None
        metrics = self.metrics_summary()

        return {
            "status": current_meta.get("status") if current_meta else "idle",
            "active_run_id": active,
            "selected_model": self.config.model,
            "planner_model_used": current_meta.get("planner_model_used") if current_meta else self._planner_model(),
            "coder_model_used": current_meta.get("coder_model_used") if current_meta else self._coder_model(),
            "critic_model_used": current_meta.get("critic_model_used") if current_meta else self._critic_model(),
            "tdd_mode": current_meta.get("tdd_mode") if current_meta else self.settings.tdd_mode,
            "iterations_until_green": current_meta.get("iterations_until_green") if current_meta else None,
            "project_slug": current_meta.get("project_slug", "") if current_meta else "",
            "project_path": current_meta.get("project_path", "") if current_meta else "",
            "project_created_new": current_meta.get("project_created_new") if current_meta else None,
            "workspace_target_path": current_meta.get("workspace_target_path", "") if current_meta else "",
            "workspace_target_type": current_meta.get("workspace_target_type", "") if current_meta else "",
            "current_stage": current_meta.get("current_stage", "idle") if current_meta else "idle",
            "stages": ["planner", "coder", "safety", "executor", "critic", "memory"],
            "iteration": current_meta.get("iteration", 0) if current_meta else 0,
            "max_iterations": current_meta.get("max_iterations", self.effective_max_iterations()) if current_meta else self.effective_max_iterations(),
            "progress_percent": current_meta.get("progress_percent", 0) if current_meta else 0,
            "last_command": current_meta.get("last_command", "") if current_meta else "",
            "latest_success": current_meta.get("success") if current_meta else (latest.get("success") if latest else None),
            "latest_message": current_meta.get("message", "") if current_meta else (latest.get("message", "") if latest else ""),
            "pending_approvals": pending_count,
            "safe_mode": self.settings.safe_mode,
            "rate_limit_seconds": self.settings.rate_limit_seconds,
            "allowed_commands": list(self.config.allowed_commands),
            "metrics": metrics,
            "csrf_token": self._csrf_token,
        }

    def get_csrf_token(self) -> str:
        return self._csrf_token

    def subscribe(self, channel: str) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.setdefault(channel, []).append(q)
        return q

    def unsubscribe(self, channel: str, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            rows = self._subscribers.get(channel, [])
            if q in rows:
                rows.remove(q)

    def publish_event(self, channel: str, event: dict[str, Any]) -> None:
        with self._lock:
            queues = list(self._subscribers.get(channel, []))
        for q in queues:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(event)
                except queue.Full:
                    continue

    def get_settings(self) -> dict[str, Any]:
        return {
            **asdict(self.settings),
            "model": self.config.model,
            "planner_model_default": self.config.planner_model,
            "coder_model_default": self.config.coder_model,
            "critic_model_default": self.config.critic_model,
            "allowed_commands": list(self.config.allowed_commands),
            "max_iterations_default": self.config.max_iterations,
            "workspace_dir": str(self.config.workspace_dir),
            "goal_templates": self.goal_templates(),
        }

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = asdict(self.settings)
        for key in list(current.keys()):
            if key in payload:
                current[key] = payload[key]
        self.settings = ControlSettings.from_dict(current)
        self._validate_role_models()
        self._save_settings()
        return self.get_settings()

    def goal_templates(self) -> list[dict[str, Any]]:
        return [dict(item) for item in GOAL_TEMPLATES]

    def _template_by_id(self, template_id: str) -> dict[str, Any] | None:
        cleaned = template_id.strip()
        if not cleaned:
            return None
        for item in GOAL_TEMPLATES:
            if item.get("id") == cleaned:
                return dict(item)
        return None

    def list_ollama_models(self) -> list[str]:
        tags_url = self.config.ollama_url.replace("/api/chat", "/api/tags")
        try:
            response = requests.get(tags_url, timeout=(5, 10))
            response.raise_for_status()
            payload = response.json()
        except Exception:
            base = [self.config.model, self._planner_model(), self._coder_model(), self._critic_model()]
            return sorted({item for item in base if item})

        rows = payload.get("models", []) if isinstance(payload, dict) else []
        names: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            try:
                names.append(sanitize_model_name(name, "ollama_model"))
            except ValueError:
                continue

        if not names:
            names = [self.config.model, self._planner_model(), self._coder_model(), self._critic_model()]
        return sorted({item for item in names if item})

    def effective_max_iterations(self) -> int:
        if self.settings.max_iterations_override > 0:
            return self.settings.max_iterations_override
        return self.config.max_iterations

    def _planner_model(self) -> str:
        chosen = self.settings.planner_model or self.config.planner_model or self.config.model
        return sanitize_model_name(chosen, "planner_model")

    def _coder_model(self) -> str:
        chosen = self.settings.coder_model or self.config.coder_model or self.config.model
        return sanitize_model_name(chosen, "coder_model")

    def _critic_model(self) -> str:
        chosen = self.settings.critic_model or self.config.critic_model or self.config.model
        return sanitize_model_name(chosen, "critic_model")

    def _validate_role_models(self) -> None:
        # Sanitizes configured names and normalizes to safe values.
        self.settings.planner_model = sanitize_model_name(
            self.settings.planner_model or self.config.planner_model or self.config.model,
            "planner_model",
        )
        self.settings.coder_model = sanitize_model_name(
            self.settings.coder_model or self.config.coder_model or self.config.model,
            "coder_model",
        )
        self.settings.critic_model = sanitize_model_name(
            self.settings.critic_model or self.config.critic_model or self.config.model,
            "critic_model",
        )

    def start_run(self, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        template_id = str(payload.get("template_id", "")).strip()
        template = self._template_by_id(template_id)
        if template_id and template is None:
            return False, {"error": "Unknown goal template."}

        command = str(payload.get("command", "")).strip()
        preview = bool(payload.get("preview", self.settings.run_preview_default))
        requested_mode = str(payload.get("mode", "")).strip().lower()
        requested_payload = str(payload.get("payload", "")).strip()

        if not command and requested_mode == "goal" and not requested_payload and template:
            command = f"/goal {template['goal']}"

        if not command:
            mode = requested_mode
            content = requested_payload
            if mode in {"goal", "ask", "teach"} and content:
                command = f"/{mode} {content}"

        parsed = parse_chat_command(command)
        if parsed is None:
            return False, {"error": "Command cannot be empty."}

        mode, content = parsed
        if mode not in {"goal", "ask", "teach"}:
            return False, {"error": "Only /goal, /ask, and /teach are allowed."}
        if not content:
            return False, {"error": f"/{mode} requires content."}

        try:
            planner_model_used = sanitize_model_name(
                str(payload.get("planner_model", self._planner_model())).strip() or self._planner_model(),
                "planner_model",
            )
            coder_model_used = sanitize_model_name(
                str(payload.get("coder_model", self._coder_model())).strip() or self._coder_model(),
                "coder_model",
            )
            critic_model_used = sanitize_model_name(
                str(payload.get("critic_model", self._critic_model())).strip() or self._critic_model(),
                "critic_model",
            )
        except ValueError as exc:
            return False, {"error": str(exc)}

        tdd_mode = bool(payload.get("tdd_mode", template.get("tdd_mode", self.settings.tdd_mode) if template else self.settings.tdd_mode))
        if mode != "goal":
            tdd_mode = False

        project_slug = ""
        project_path = ""
        project_created_new: bool | None = None
        workspace_target_path = ""
        workspace_target_type = ""

        with self._lock:
            if self._active_thread and self._active_thread.is_alive():
                return False, {"error": "Another run is already active."}

            now = time.monotonic()
            if mode == "goal" and self.settings.rate_limit_seconds > 0:
                elapsed = now - self._last_run_started_at
                if elapsed < self.settings.rate_limit_seconds:
                    wait_for = round(self.settings.rate_limit_seconds - elapsed, 2)
                    return False, {
                        "error": f"Rate limit active. Wait {wait_for}s before starting another goal run."
                    }

            if self.settings.safe_mode:
                if mode == "teach":
                    return False, {"error": "Safe mode is enabled. /teach is blocked in read-only mode."}
                if mode == "goal" and not preview:
                    return False, {
                        "error": "Safe mode is enabled. Use preview=true for /goal in read-only mode."
                    }

            if mode == "goal":
                requested_target = str(payload.get("workspace_target_path", "")).strip()
                if requested_target:
                    try:
                        target_path, normalized_target, target_type = self._resolve_existing_goal_target(requested_target)
                    except ValueError as exc:
                        return False, {"error": str(exc)}
                    goal_workspace_dir = target_path if target_type == "folder" else target_path.parent
                    project_slug = goal_workspace_dir.name or "workspace"
                    project_path = str(goal_workspace_dir)
                    project_created_new = False
                    workspace_target_path = normalized_target
                    workspace_target_type = target_type
                else:
                    project = prepare_project_for_goal(self.config.workspace_dir, content)
                    project_slug = project.project_slug
                    project_path = str(project.project_path)
                    project_created_new = project.project_created_new

            run_id = self._new_run_id()
            run_dir = self._run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "iterations").mkdir(parents=True, exist_ok=True)

            meta = {
                "id": run_id,
                "command": command,
                "mode": mode,
                "payload": content,
                "preview": preview,
                "status": "queued",
                "current_stage": "queued",
                "started_at": self._now_iso(),
                "ended_at": None,
                "model": self.config.model,
                "planner_model_used": planner_model_used,
                "coder_model_used": coder_model_used,
                "critic_model_used": critic_model_used,
                "tdd_mode": tdd_mode,
                "iterations_until_green": None,
                "template_id": template.get("id") if template else "",
                "project_slug": project_slug,
                "project_path": project_path,
                "project_created_new": project_created_new,
                "workspace_target_path": workspace_target_path,
                "workspace_target_type": workspace_target_type,
                "iteration": 0,
                "max_iterations": self.effective_max_iterations(),
                "progress_percent": 0,
                "last_command": "",
                "success": None,
                "message": "",
                "failure_explanation": "",
                "tests_ran": False,
                "tests_passed": None,
                "safe_mode": self.settings.safe_mode,
                "rate_limit_seconds": self.settings.rate_limit_seconds,
                "artifacts_dir": str(run_dir),
                "workspace_dir": str(self.config.workspace_dir),
            }
            self._write_json(run_dir / "meta.json", meta)

            run_options = {
                "planner_model_used": planner_model_used,
                "coder_model_used": coder_model_used,
                "critic_model_used": critic_model_used,
                "tdd_mode": tdd_mode,
                "template_id": template.get("id") if template else "",
                "project_slug": project_slug,
                "project_path": project_path,
                "project_created_new": project_created_new,
                "workspace_target_path": workspace_target_path,
                "workspace_target_type": workspace_target_type,
            }
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._execute_run,
                args=(run_id, mode, content, preview, cancel_event, run_options),
                daemon=True,
                name=f"david-run-{run_id}",
            )

            self._active_thread = worker
            self._active_run_id = run_id
            self._active_cancel = cancel_event
            self._last_run_started_at = now
            worker.start()

        return True, {
            "run_id": run_id,
            "status": "queued",
            "planner_model_used": planner_model_used,
            "coder_model_used": coder_model_used,
            "critic_model_used": critic_model_used,
            "tdd_mode": tdd_mode,
            "template_id": template.get("id") if template else "",
            "project_slug": project_slug,
            "project_path": project_path,
            "project_created_new": project_created_new,
            "workspace_target_path": workspace_target_path,
            "workspace_target_type": workspace_target_type,
        }

    def stop_active_run(self) -> dict[str, Any]:
        with self._lock:
            if not self._active_run_id:
                return {"stopped": False, "error": "No active run."}
            run_id = self._active_run_id
            cancel = self._active_cancel
            if cancel:
                cancel.set()

            for approval in self._pending_approvals.values():
                if approval.get("run_id") == run_id and approval.get("status") == "pending":
                    approval["status"] = "rejected"
                    approval["decision"] = "reject"
                    approval["decision_note"] = "Stopped by user"
                    approval["decided_at"] = self._now_iso()
            self._logger.info("stop requested run_id=%s", run_id)

        self._update_run_meta(run_id, status="stopping", message="Stop requested by user.", current_stage="executor")
        return {"stopped": True, "run_id": run_id}

    def ask_memory(self, question: str, actor: str = "web_ui") -> dict[str, Any]:
        clean_question = self._sanitize_user_text(question, field_name="question")
        llm = OllamaClient(self.config)
        memory = LongTermMemory(self.config.memory_file)
        teacher = MemoryTeacherQA(llm=llm, memory=memory)

        answer = teacher.ask(clean_question)
        matched = memory.search_facts(clean_question, limit=8)
        payload = {
            "mode": "ask",
            "question": clean_question,
            "answer": answer,
            "matched_facts": [asdict(item) for item in matched],
            "matched_count": len(matched),
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("status", {"type": "memory_ask_answered", "payload": payload})
        self.publish_event("logs", {"type": "memory_ask_answered", "payload": payload})
        return payload

    def teach_memory(
        self,
        message: str,
        *,
        confirm_conflict: bool = False,
        actor: str = "web_ui",
    ) -> dict[str, Any]:
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. /teach is blocked in read-only mode.")

        clean_message = self._sanitize_user_text(message, field_name="message")
        llm = OllamaClient(self.config)
        memory = LongTermMemory(self.config.memory_file)
        teacher = MemoryTeacherQA(llm=llm, memory=memory)

        conflicts = self._preview_teach_conflicts(teacher, memory, clean_message)
        if conflicts and not confirm_conflict:
            payload = {
                "mode": "teach",
                "status": "conflict",
                "message": clean_message,
                "requires_confirmation": True,
                "stored_facts": [],
                "stored_count": 0,
                "skipped_items": [],
                "notes": "Conflict detected. Confirm to continue.",
                "conflicts": conflicts,
                "actor": actor.strip() or "web_ui",
                "timestamp_utc": self._now_iso(),
            }
            self.publish_event("status", {"type": "memory_teach_conflict", "payload": payload})
            self.publish_event("logs", {"type": "memory_teach_conflict", "payload": payload})
            return payload

        result = teacher.teach(clean_message)
        payload = {
            "mode": "teach",
            "status": "stored",
            "message": clean_message,
            "requires_confirmation": False,
            "confirmed_conflict": bool(conflicts),
            "stored_facts": [asdict(fact) for fact in result.stored_facts],
            "stored_count": len(result.stored_facts),
            "skipped_items": list(result.skipped_items),
            "notes": result.notes,
            "conflicts": conflicts,
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("status", {"type": "memory_teach_completed", "payload": payload})
        self.publish_event("logs", {"type": "memory_teach_completed", "payload": payload})
        return payload

    def submit_approval(
        self,
        approval_id: str,
        decision: str,
        note: str = "",
        actor: str = "local_user",
        confirmation: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        choice = decision.strip().lower()
        if choice not in {"approve", "reject"}:
            return False, {"error": "Decision must be approve or reject."}

        with self._lock:
            approval = self._pending_approvals.get(approval_id)
            if not approval:
                return False, {"error": "Approval request not found."}
            if approval.get("status") != "pending":
                return False, {"error": "Approval is already resolved."}
            if choice == "approve" and bool(approval.get("requires_typed_confirmation")):
                expected = f"approve {approval.get('run_id')}"
                if confirmation.strip().lower() != expected.lower():
                    return False, {"error": f"Typed confirmation required: `{expected}`"}

            approval["status"] = "approved" if choice == "approve" else "rejected"
            approval["decision"] = choice
            approval["decision_note"] = note.strip()
            approval["decided_at"] = self._now_iso()
            approval["actor"] = actor.strip() or "local_user"
            run_id = str(approval.get("run_id", ""))

        self._append_audit(
            run_id=run_id,
            action="approval_decision",
            payload={
                "approval_id": approval_id,
                "decision": choice,
                "actor": actor.strip() or "local_user",
                "note": note.strip(),
            },
        )
        self.publish_event(
            f"run:{run_id}",
            {"type": "approval_decision", "run_id": run_id, "approval_id": approval_id, "decision": choice},
        )
        self.publish_event(
            "status",
            {"type": "approval_decision", "run_id": run_id, "approval_id": approval_id, "decision": choice},
        )
        return True, {"approval_id": approval_id, "decision": choice}

    def list_approvals(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._pending_approvals.values())
        rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return rows

    def get_runs(self, search: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for run_dir in self.runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            meta = self._read_json(run_dir / "meta.json", default=None)
            if not isinstance(meta, dict):
                continue
            rows.append(meta)

        rows.sort(key=lambda item: item.get("started_at", ""), reverse=True)

        if search.strip():
            query = search.casefold().strip()
            rows = [
                item
                for item in rows
                if query in str(item.get("command", "")).casefold()
                or query in str(item.get("message", "")).casefold()
                or query in str(item.get("id", "")).casefold()
            ]

        if status.strip():
            wanted = status.strip().casefold()
            rows = [item for item in rows if str(item.get("status", "")).casefold() == wanted]

        warnings = self.regression_warnings(rows)
        warning_by_run = {item["run_id"]: item["warning"] for item in warnings}
        for idx, row in enumerate(rows):
            if row.get("id") in warning_by_run:
                updated = row.copy()
                updated["regression_warning"] = warning_by_run[str(row.get("id"))]
                rows[idx] = updated

        return rows[: max(1, min(limit, 500))]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not self._is_safe_run_id(run_id):
            return None

        run_dir = self._run_dir(run_id)
        meta = self._read_json(run_dir / "meta.json", default=None)
        if not isinstance(meta, dict):
            return None

        plan = self._read_json(run_dir / "plan.json", default={})
        result = self._read_json(run_dir / "result.json", default={})
        timeline = self._read_jsonl(run_dir / "timeline.jsonl", limit=1_000)

        iteration_rows: list[dict[str, Any]] = []
        iterations_dir = run_dir / "iterations"
        if iterations_dir.exists():
            for item in sorted(iterations_dir.iterdir()):
                if not item.is_dir():
                    continue
                iteration_rows.append(
                    {
                        "iteration": item.name,
                        "coder": self._read_json(item / "coder.json", default={}),
                        "execution": self._read_json(item / "execution.json", default=[]),
                        "critic": self._read_json(item / "critic.json", default={}),
                        "diffs": self._read_json(item / "diffs.json", default=[]),
                        "risk": self._read_json(item / "risk.json", default={}),
                    }
                )

        return {
            "meta": meta,
            "plan": plan,
            "result": result,
            "timeline": timeline,
            "iterations": iteration_rows,
            "approvals": [a for a in self.list_approvals() if a.get("run_id") == run_id],
            "artifacts_dir": str(run_dir),
            "workspace_dir": str(self.config.workspace_dir),
            "file_summary": self.get_run_files(run_id),
        }

    def get_run_timeline(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return None
        return self._read_jsonl(run_dir / "timeline.jsonl", limit=max(1, min(limit, 2000)))

    def get_run_audit(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return None
        return self._read_jsonl(run_dir / "audit.jsonl", limit=max(1, min(limit, 2000)))

    def get_run_files(self, run_id: str) -> dict[str, Any] | None:
        if not self._is_safe_run_id(run_id):
            return None

        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return None
        meta = self._read_json(run_dir / "meta.json", default={})
        project_slug = ""
        project_path_str = ""
        project_dir: Path | None = None
        if isinstance(meta, dict):
            project_slug = str(meta.get("project_slug", "")).strip()
            project_path_str = str(meta.get("project_path", "")).strip()
            if project_path_str:
                try:
                    project_dir = self._resolve_goal_project_path(project_path_str)
                except ValueError:
                    project_dir = None

        created: dict[str, dict[str, Any]] = {}
        modified: dict[str, dict[str, Any]] = {}

        iterations_dir = run_dir / "iterations"
        if iterations_dir.exists():
            for iter_dir in sorted(iterations_dir.iterdir()):
                if not iter_dir.is_dir():
                    continue
                diffs = self._read_json(iter_dir / "diffs.json", default=[])
                if not isinstance(diffs, list):
                    continue
                for diff in diffs:
                    if not isinstance(diff, dict):
                        continue
                    path = str(diff.get("path", "")).strip()
                    if not path:
                        continue
                    record = {
                        "path": path,
                        "change_type": str(diff.get("change_type", "edited")),
                        "workspace_path": str(diff.get("workspace_path", path)),
                        "added": int(diff.get("added", 0)),
                        "removed": int(diff.get("removed", 0)),
                        "after_preview": str(diff.get("after_preview", "")),
                    }
                    if record["change_type"] == "new":
                        created[path] = record
                        modified.pop(path, None)
                    elif path not in created:
                        modified[path] = record

        workspace_files, workspace_dirs, workspace_file_total, workspace_dir_total, workspace_files_truncated = self._list_workspace_files(
            limit=20_000
        )
        return {
            "artifacts_dir": str(run_dir),
            "workspace_dir": str(self.config.workspace_dir),
            "project_slug": project_slug,
            "project_path": project_path_str,
            "created": sorted(created.values(), key=lambda row: row["path"]),
            "modified": sorted(modified.values(), key=lambda row: row["path"]),
            "project_files": self._list_project_files(project_dir, limit=1200),
            "workspace_files": workspace_files,
            "workspace_dirs": workspace_dirs,
            "workspace_file_total": workspace_file_total,
            "workspace_dir_total": workspace_dir_total,
            "workspace_files_truncated": workspace_files_truncated,
        }

    def get_run_replay(self, run_id: str, iteration: int) -> dict[str, Any] | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_dir = self._run_dir(run_id)
        iterations_dir = run_dir / "iterations"
        if not iterations_dir.exists():
            return None

        all_items = sorted([item for item in iterations_dir.iterdir() if item.is_dir()])
        if not all_items:
            return None
        idx = max(0, min(iteration - 1, len(all_items) - 1))
        item = all_items[idx]
        chosen = int(item.name)

        current = {
            "iteration": chosen,
            "coder": self._read_json(item / "coder.json", default={}),
            "execution": self._read_json(item / "execution.json", default=[]),
            "critic": self._read_json(item / "critic.json", default={}),
            "diffs": self._read_json(item / "diffs.json", default=[]),
        }
        compare = self.compare_iterations(run_id, chosen)

        return {
            "run_id": run_id,
            "iteration": chosen,
            "total_iterations": len(all_items),
            "has_prev": idx > 0,
            "has_next": idx < len(all_items) - 1,
            "prev_iteration": int(all_items[idx - 1].name) if idx > 0 else None,
            "next_iteration": int(all_items[idx + 1].name) if idx < len(all_items) - 1 else None,
            "current": current,
            "comparison": compare,
        }

    def compare_iterations(self, run_id: str, iteration: int) -> dict[str, Any] | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_dir = self._run_dir(run_id)
        iterations_dir = run_dir / "iterations"
        if not iterations_dir.exists():
            return None
        curr_dir = iterations_dir / f"{iteration:03d}"
        prev_dir = iterations_dir / f"{iteration - 1:03d}"
        if not curr_dir.exists():
            return None

        curr_exec = self._read_json(curr_dir / "execution.json", default=[])
        prev_exec = self._read_json(prev_dir / "execution.json", default=[]) if prev_dir.exists() else []
        curr_diffs = self._read_json(curr_dir / "diffs.json", default=[])
        prev_diffs = self._read_json(prev_dir / "diffs.json", default=[]) if prev_dir.exists() else []

        def _passed(rows: list[dict[str, Any]]) -> bool:
            if not rows:
                return False
            return all(int(item.get("returncode", 1)) == 0 and not bool(item.get("timed_out")) for item in rows if isinstance(item, dict))

        changed_now = sorted({str(item.get("path", "")).strip() for item in curr_diffs if isinstance(item, dict) and str(item.get("path", "")).strip()})
        changed_prev = sorted({str(item.get("path", "")).strip() for item in prev_diffs if isinstance(item, dict) and str(item.get("path", "")).strip()})
        new_changes = [path for path in changed_now if path not in changed_prev]

        likely_cause = None
        if _passed(prev_exec) and not _passed(curr_exec):
            likely_cause = {
                "reason": "First failing iteration after a passing iteration.",
                "files": new_changes or changed_now,
            }

        return {
            "iteration": iteration,
            "previous_iteration": iteration - 1 if prev_dir.exists() else None,
            "changed_files_current": changed_now,
            "changed_files_previous": changed_prev,
            "newly_changed_files": new_changes,
            "passed_previous": _passed(prev_exec),
            "passed_current": _passed(curr_exec),
            "likely_failure_cause": likely_cause,
        }

    def retry_run(self, run_id: str) -> tuple[bool, dict[str, Any]]:
        current = self.get_run(run_id)
        if not current:
            return False, {"error": "Run not found."}
        meta = current.get("meta", {}) if isinstance(current, dict) else {}
        command = str(meta.get("command", "")).strip()
        if not command:
            return False, {"error": "Original command missing."}
        payload: dict[str, Any] = {
            "command": command,
            "preview": False,
            "template_id": str(meta.get("template_id", "")).strip(),
            "planner_model": str(meta.get("planner_model_used", "")).strip(),
            "coder_model": str(meta.get("coder_model_used", "")).strip(),
            "critic_model": str(meta.get("critic_model_used", "")).strip(),
            "tdd_mode": bool(meta.get("tdd_mode", False)),
            "workspace_target_path": str(meta.get("workspace_target_path", "")).strip(),
        }
        return self.start_run(payload)

    def run_bundle_zip(self, run_id: str) -> io.BytesIO | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_dir = self._run_dir(run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            return None

        buff = io.BytesIO()
        with zipfile.ZipFile(buff, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in run_dir.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(run_dir).as_posix()
                    archive.write(path, arcname=f"{run_id}/{rel}")
        buff.seek(0)
        return buff

    def memory_snapshot(self) -> dict[str, Any]:
        payload = self._read_json(self.config.memory_file, default={"facts": [], "lessons": [], "preferences": []})
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        conflicts = self._detect_memory_conflicts(facts)
        return {
            "facts": facts[-300:],
            "lessons": lessons[-300:],
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
        }

    def telemetry_tail(self, limit: int = 100) -> dict[str, Any]:
        events = self._read_jsonl(self.config.logs_dir / "telemetry.jsonl", limit=max(1, min(limit, 1000)))
        metrics = self._read_json(self.config.logs_dir / "metrics.json", default={"iterations": []})
        rows = metrics.get("iterations", []) if isinstance(metrics, dict) else []
        if not isinstance(rows, list):
            rows = []

        success = 0
        retries = 0
        aborts = 0
        durations: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "")).lower()
            if status == "success":
                success += 1
            elif status == "retry":
                retries += 1
            elif status == "abort":
                aborts += 1
            try:
                durations.append(float(row.get("duration_sec", 0.0)))
            except (TypeError, ValueError):
                pass

        total = max(1, success + retries + aborts)
        avg_duration = round(sum(durations) / len(durations), 3) if durations else 0.0
        summary = {
            "total_iterations": success + retries + aborts,
            "success_rate": round(success / total, 3),
            "error_frequency": round((retries + aborts) / total, 3),
            "avg_duration_sec": avg_duration,
        }

        return {
            "events": events,
            "metrics": rows[-500:],
            "summary": summary,
            "regressions": self.regression_warnings(self.get_runs(limit=200)),
        }

    def logs_tail(self, limit: int = 200) -> dict[str, Any]:
        files = [
            self.config.logs_dir / "web_control_center.log",
            self.config.logs_dir / "telemetry.jsonl",
        ]
        payload: dict[str, Any] = {}
        for path in files:
            payload[path.name] = self._tail_lines(path, max(1, min(limit, 2000)))

        runs = self.get_runs(limit=1)
        if runs:
            run_id = str(runs[0].get("id", "")).strip()
            if run_id and self._is_safe_run_id(run_id):
                timeline_path = self._run_dir(run_id) / "timeline.jsonl"
                payload[f"run_{run_id}_timeline.jsonl"] = self._tail_lines(
                    timeline_path, max(1, min(limit, 2000))
                )
        return payload

    def metrics_summary(self) -> dict[str, Any]:
        telemetry = self.telemetry_tail(limit=50)
        summary = telemetry.get("summary", {})
        summary["recent_durations"] = [
            item.get("duration_sec", 0.0)
            for item in telemetry.get("metrics", [])[-30:]
            if isinstance(item, dict)
        ]
        return summary

    def regression_warnings(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(runs, key=lambda item: item.get("started_at", ""))
        warnings: list[dict[str, Any]] = []
        had_passing_tests = False
        for row in ordered:
            if row.get("mode") != "goal":
                continue
            tests_ran = bool(row.get("tests_ran"))
            tests_passed = row.get("tests_passed")
            if tests_ran and tests_passed is True:
                had_passing_tests = True
            if tests_ran and tests_passed is False and had_passing_tests:
                warnings.append(
                    {
                        "run_id": row.get("id"),
                        "warning": "Regression detector: tests failed after earlier passing runs.",
                    }
                )
        return warnings

    def _execute_run(
        self,
        run_id: str,
        mode: str,
        payload: str,
        preview: bool,
        cancel_event: threading.Event,
        run_options: dict[str, Any],
    ) -> None:
        try:
            self._update_run_meta(run_id, status="running", current_stage="planner")
            self._append_timeline(
                run_id,
                "run_started",
                {
                    "mode": mode,
                    "preview": preview,
                    "planner_model_used": run_options.get("planner_model_used"),
                    "coder_model_used": run_options.get("coder_model_used"),
                    "critic_model_used": run_options.get("critic_model_used"),
                    "tdd_mode": bool(run_options.get("tdd_mode", False)),
                    "template_id": run_options.get("template_id", ""),
                    "project_slug": run_options.get("project_slug", ""),
                    "project_path": run_options.get("project_path", ""),
                    "project_created_new": run_options.get("project_created_new"),
                    "workspace_target_path": run_options.get("workspace_target_path", ""),
                    "workspace_target_type": run_options.get("workspace_target_type", ""),
                },
            )

            if mode == "ask":
                self._execute_ask(run_id, payload)
            elif mode == "teach":
                self._execute_teach(run_id, payload)
            else:
                self._execute_goal(
                    run_id,
                    payload,
                    preview=preview,
                    cancel_event=cancel_event,
                    run_options=run_options,
                )

        except Exception as exc:  # pragma: no cover - defensive boundary
            self._logger.exception("run failed run_id=%s", run_id)
            self._update_run_meta(
                run_id,
                status="failed",
                success=False,
                message=str(exc),
                failure_explanation=f"Unhandled exception: {exc}",
                ended_at=self._now_iso(),
            )
            self._write_json(self._run_dir(run_id) / "result.json", {"error": str(exc)})
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None
                    self._active_cancel = None
                    self._active_thread = None

    def _execute_ask(self, run_id: str, question: str) -> None:
        self._update_run_meta(run_id, current_stage="memory")
        llm = OllamaClient(self.config)
        memory = LongTermMemory(self.config.memory_file)
        teacher = MemoryTeacherQA(llm=llm, memory=memory)

        answer = teacher.ask(question)
        result = {"question": question, "answer": answer}
        self._write_json(self._run_dir(run_id) / "result.json", result)
        self._append_timeline(run_id, "ask_answered", result)
        self._update_run_meta(
            run_id,
            status="success",
            success=True,
            message=answer,
            ended_at=self._now_iso(),
            progress_percent=100,
            current_stage="memory",
        )

    def _execute_teach(self, run_id: str, message: str) -> None:
        self._update_run_meta(run_id, current_stage="memory")
        llm = OllamaClient(self.config)
        memory = LongTermMemory(self.config.memory_file)
        teacher = MemoryTeacherQA(llm=llm, memory=memory)

        conflicts = self._preview_teach_conflicts(teacher, memory, message)
        if conflicts:
            approval_id = self._register_approval(
                run_id=run_id,
                iteration=0,
                approval_type="memory_conflict",
                reasons=["Teaching payload conflicts with existing memory facts."],
                payload={"conflicts": conflicts, "message": message},
            )
            self._update_run_meta(run_id, status="awaiting_approval", message="Awaiting memory conflict approval.")
            decision = self._wait_for_approval(approval_id)
            if decision != "approve":
                self._finalize_rejected(run_id, "Teach operation rejected due to memory conflict.")
                return

        result = teacher.teach(message)
        payload = {
            "stored_facts": [asdict(fact) for fact in result.stored_facts],
            "skipped_items": list(result.skipped_items),
            "notes": result.notes,
        }
        self._write_json(self._run_dir(run_id) / "result.json", payload)
        self._append_timeline(run_id, "teach_completed", {"stored_facts": len(result.stored_facts)})
        self._update_run_meta(
            run_id,
            status="success",
            success=True,
            message=f"Stored {len(result.stored_facts)} facts.",
            ended_at=self._now_iso(),
            progress_percent=100,
            current_stage="memory",
        )

    def _execute_goal(
        self,
        run_id: str,
        goal: str,
        preview: bool,
        cancel_event: threading.Event,
        run_options: dict[str, Any] | None = None,
    ) -> None:
        options = run_options or {}
        planner_model_used = sanitize_model_name(
            str(options.get("planner_model_used", self._planner_model())).strip() or self._planner_model(),
            "planner_model",
        )
        coder_model_used = sanitize_model_name(
            str(options.get("coder_model_used", self._coder_model())).strip() or self._coder_model(),
            "coder_model",
        )
        critic_model_used = sanitize_model_name(
            str(options.get("critic_model_used", self._critic_model())).strip() or self._critic_model(),
            "critic_model",
        )
        tdd_mode = bool(options.get("tdd_mode", self.settings.tdd_mode))
        project_slug = str(options.get("project_slug", "")).strip()
        project_path_raw = str(options.get("project_path", "")).strip()
        project_created_new = options.get("project_created_new")
        workspace_target_path = str(options.get("workspace_target_path", "")).strip()
        workspace_target_type = str(options.get("workspace_target_type", "")).strip().lower()
        if not project_path_raw:
            if workspace_target_path:
                target_path, normalized_target, target_type = self._resolve_existing_goal_target(workspace_target_path)
                workspace_target_path = normalized_target
                workspace_target_type = target_type
                goal_workspace_dir = target_path if target_type == "folder" else target_path.parent
                project_slug = goal_workspace_dir.name or "workspace"
                project_path_raw = str(goal_workspace_dir)
                project_created_new = False
            else:
                project = prepare_project_for_goal(self.config.workspace_dir, goal)
                project_slug = project.project_slug
                project_path_raw = str(project.project_path)
                project_created_new = project.project_created_new
        project_path = self._resolve_goal_project_path(project_path_raw)
        if not project_slug:
            project_slug = project_path.name or "workspace"

        effective_goal = self._augment_goal_with_workspace_target(goal, workspace_target_path, workspace_target_type)

        llm = OllamaClient(self.config)
        planner = Planner(llm, model_name=planner_model_used)
        coder = Coder(llm, model_name=coder_model_used)
        critic = Critic(llm, model_name=critic_model_used)
        safety = SafetyGuard(
            workspace_dir=project_path,
            max_file_write_bytes=self.config.max_file_write_bytes,
            max_total_write_bytes=self.config.max_total_write_bytes,
            allowed_commands=self.config.allowed_commands,
        )
        executor = RestrictedExecutor(
            workspace_dir=project_path,
            timeout_sec=self.config.command_timeout_sec,
            max_output_chars=self.config.max_command_output_chars,
        )
        memory = LongTermMemory(self.config.memory_file)
        workspace = WorkspaceInspector(project_path)
        telemetry = TelemetryLogger(self.config.logs_dir)
        project_meta = {
            "project_slug": project_slug,
            "project_path": str(project_path),
            "project_created_new": project_created_new,
            "workspace_target_path": workspace_target_path,
            "workspace_target_type": workspace_target_type,
        }

        iteration_limit = self.effective_max_iterations()
        tdd_red_phase_complete = False
        iterations_until_green: int | None = None

        self._update_run_meta(
            run_id,
            current_stage="planner",
            planner_model_used=planner_model_used,
            coder_model_used=coder_model_used,
            critic_model_used=critic_model_used,
            tdd_mode=tdd_mode,
            project_slug=project_slug,
            project_path=str(project_path),
            project_created_new=project_created_new,
            workspace_target_path=workspace_target_path,
            workspace_target_type=workspace_target_type,
        )
        initial_snapshot = workspace.snapshot()
        memory_context = memory.render_context(effective_goal)
        plan = planner.create_plan(
            goal=effective_goal,
            workspace_snapshot=initial_snapshot,
            memory_context=memory_context,
            tdd_mode=tdd_mode,
        )
        self._write_json(self._run_dir(run_id) / "plan.json", plan.to_dict())
        self._append_timeline(
            run_id,
            "plan_created",
            {
                "plan": plan.to_dict(),
                "planner_model_used": planner_model_used,
                "coder_model_used": coder_model_used,
                "critic_model_used": critic_model_used,
                "tdd_mode": tdd_mode,
                **project_meta,
            },
        )
        telemetry.event(
            "plan_created",
            {
                "run_id": run_id,
                "goal": effective_goal,
                "plan": plan.to_dict(),
                "planner_model_used": planner_model_used,
                "coder_model_used": coder_model_used,
                "critic_model_used": critic_model_used,
                "tdd_mode": tdd_mode,
                **project_meta,
            },
        )

        critic_feedback = "No critic feedback yet."
        tests_ran = False
        tests_passed: bool | None = None

        for iteration in range(1, iteration_limit + 1):
            if cancel_event.is_set():
                telemetry.event(
                    "run_complete",
                    {
                        "run_id": run_id,
                        "goal": effective_goal,
                        "success": False,
                        "iterations_used": max(0, iteration - 1),
                        "planner_model_used": planner_model_used,
                        "coder_model_used": coder_model_used,
                        "critic_model_used": critic_model_used,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                        **project_meta,
                    },
                )
                self._finalize_stopped(
                    run_id,
                    "Run stopped by user.",
                    tests_ran,
                    tests_passed,
                    iterations_until_green=iterations_until_green,
                )
                return

            started = time.perf_counter()
            tdd_phase = (
                "implementation"
                if (tdd_mode and tdd_red_phase_complete)
                else ("tests_first" if tdd_mode else "normal")
            )
            self._update_run_meta(
                run_id,
                iteration=iteration,
                status="running",
                progress_percent=int(((iteration - 1) / max(1, iteration_limit)) * 100),
                current_stage="coder",
            )

            workspace_snapshot = workspace.snapshot()
            memory_context = memory.render_context(effective_goal)
            coder_output = coder.propose(
                goal=effective_goal,
                plan_json=plan.to_dict(),
                workspace_snapshot=workspace_snapshot,
                memory_context=memory_context,
                critic_feedback=critic_feedback,
                iteration=iteration,
                tdd_mode=tdd_mode,
                tdd_phase=tdd_phase,
            )

            iter_dir = self._run_dir(run_id) / "iterations" / f"{iteration:03d}"
            iter_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(iter_dir / "coder.json", coder_output.to_dict())
            self._append_timeline(
                run_id,
                "coder_output",
                {
                    "iteration": iteration,
                    "summary": coder_output.summary,
                    "edit_count": len(coder_output.edits),
                    "commands": coder_output.commands,
                    "done": coder_output.done,
                    "planner_model_used": planner_model_used,
                    "coder_model_used": coder_model_used,
                    "critic_model_used": critic_model_used,
                    "tdd_mode": tdd_mode,
                    "tdd_phase": tdd_phase,
                    **project_meta,
                },
            )

            try:
                self._update_run_meta(run_id, current_stage="safety")
                validated_edits = safety.validate_edits(coder_output.edits)
                if tdd_mode and not tdd_red_phase_complete:
                    has_tests_edit, has_non_test_edit = self._summarize_tdd_test_edits(validated_edits)
                    if not has_tests_edit or has_non_test_edit:
                        reason = (
                            "TDD mode requires tests-first edits under tests/ in the active project before implementation. "
                            "Only test files are allowed until a failing pytest run is observed."
                        )
                        self._write_json(
                            iter_dir / "risk.json",
                            {
                                "reasons": [reason],
                                "tdd_violation": True,
                                "has_tests_edit": has_tests_edit,
                                "has_non_test_edit": has_non_test_edit,
                            },
                        )
                        telemetry.event(
                            "tdd_violation",
                            {
                                "run_id": run_id,
                                "iteration": iteration,
                                "reason": reason,
                                "has_tests_edit": has_tests_edit,
                                "has_non_test_edit": has_non_test_edit,
                                **project_meta,
                            },
                        )
                        self._append_timeline(
                            run_id,
                            "tdd_violation",
                            {
                                "iteration": iteration,
                                "reason": reason,
                                "has_tests_edit": has_tests_edit,
                                "has_non_test_edit": has_non_test_edit,
                                **project_meta,
                            },
                        )
                        self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                        memory.append_lessons(
                            goal=effective_goal,
                            lessons=[
                                LessonProposal(
                                    lesson="In TDD mode, write tests under tests/ before implementation edits.",
                                    tags=["tdd", "testing", "discipline"],
                                )
                            ],
                            context=reason,
                        )
                        critic_feedback = reason
                        continue
                diffs = self._build_diff_entries(validated_edits)
            except SafetyError as exc:
                reason = f"Safety guard rejected edits: {exc}"
                telemetry.event(
                    "safety_violation",
                    {"run_id": run_id, "iteration": iteration, "error": str(exc), **project_meta},
                )
                self._write_json(iter_dir / "risk.json", {"safety_error": str(exc)})
                self._append_timeline(
                    run_id,
                    "safety_violation",
                    {"iteration": iteration, "error": str(exc), **project_meta},
                )
                self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                memory.append_lessons(
                    goal=effective_goal,
                    lessons=[
                        LessonProposal(
                            lesson="Safety validation must pass before any file write.",
                            tags=["safety", "files"],
                        )
                    ],
                    context=reason,
                )
                critic_feedback = reason
                continue

            self._write_json(iter_dir / "diffs.json", [asdict(item) for item in diffs])
            self.publish_event(
                f"run:{run_id}",
                {
                    "type": "diff_summary",
                    "run_id": run_id,
                    "iteration": iteration,
                    "diff_count": len(diffs),
                    "created": sum(1 for d in diffs if d.change_type == "new"),
                    "edited": sum(1 for d in diffs if d.change_type != "new"),
                },
            )

            risk_reasons = self._detect_risky_edit_reasons(validated_edits)
            self._write_json(iter_dir / "risk.json", {"reasons": risk_reasons})
            if risk_reasons:
                approval_id = self._register_approval(
                    run_id=run_id,
                    iteration=iteration,
                    approval_type="risky_edit",
                    reasons=risk_reasons,
                    payload={"diffs": [asdict(item) for item in diffs], "goal": effective_goal},
                )
                self._update_run_meta(
                    run_id,
                    status="awaiting_approval",
                    message="Awaiting approval for risky edit set.",
                    iteration=iteration,
                )
                decision = self._wait_for_approval(approval_id)
                if decision != "approve":
                    telemetry.event(
                        "run_complete",
                        {
                            "run_id": run_id,
                            "goal": effective_goal,
                            "success": False,
                            "iterations_used": iteration,
                            "planner_model_used": planner_model_used,
                            "coder_model_used": coder_model_used,
                            "critic_model_used": critic_model_used,
                            "tdd_mode": tdd_mode,
                            "iterations_until_green": iterations_until_green,
                            **project_meta,
                        },
                    )
                    self._finalize_rejected(
                        run_id,
                        "Risky edit set was rejected.",
                        tests_ran,
                        tests_passed,
                        iterations_until_green=iterations_until_green,
                    )
                    return
                self._append_timeline(
                    run_id,
                    "approval_granted",
                    {"iteration": iteration, "approval_id": approval_id, **project_meta},
                )

            if preview:
                self._write_json(
                    self._run_dir(run_id) / "result.json",
                    {
                        "preview": True,
                        "iteration": iteration,
                        "coder": coder_output.to_dict(),
                        "diffs": [asdict(item) for item in diffs],
                        "planner_model_used": planner_model_used,
                        "coder_model_used": coder_model_used,
                        "critic_model_used": critic_model_used,
                        "tdd_mode": tdd_mode,
                        **project_meta,
                    },
                )
                telemetry.event(
                    "run_complete",
                    {
                        "run_id": run_id,
                        "goal": effective_goal,
                        "success": True,
                        "preview": True,
                        "iterations_used": iteration,
                        "planner_model_used": planner_model_used,
                        "coder_model_used": coder_model_used,
                        "critic_model_used": critic_model_used,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                        **project_meta,
                    },
                )
                self._update_run_meta(
                    run_id,
                    status="preview_ready",
                    success=True,
                    message="Preview generated. No files were changed.",
                    ended_at=self._now_iso(),
                    progress_percent=100,
                    tests_ran=False,
                    tests_passed=None,
                    iterations_until_green=iterations_until_green,
                )
                return

            written_paths = safety.apply_edits(validated_edits)

            try:
                self._update_run_meta(run_id, current_stage="safety")
                commands_to_run = self._prepare_commands_for_iteration(coder_output.commands, tdd_mode=tdd_mode)
                command_specs = safety.validate_commands(commands_to_run)
            except SafetyError as exc:
                reason = f"Safety guard rejected commands: {exc}"
                telemetry.event(
                    "safety_violation",
                    {"run_id": run_id, "iteration": iteration, "error": str(exc), **project_meta},
                )
                self._append_timeline(
                    run_id,
                    "safety_violation",
                    {"iteration": iteration, "error": str(exc), **project_meta},
                )
                self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                memory.append_lessons(
                    goal=effective_goal,
                    lessons=[
                        LessonProposal(
                            lesson="Command execution must stay inside the allow-list.",
                            tags=["safety", "execution"],
                        )
                    ],
                    context=reason,
                )
                critic_feedback = reason
                continue

            if not command_specs:
                reason = "No validation commands were proposed. At least one allowed command is required."
                telemetry.event(
                    "execution_skipped",
                    {"run_id": run_id, "iteration": iteration, "error": reason, **project_meta},
                )
                self._append_timeline(
                    run_id,
                    "execution_skipped",
                    {"iteration": iteration, "error": reason, **project_meta},
                )
                self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                memory.append_lessons(
                    goal=effective_goal,
                    lessons=[
                        LessonProposal(
                            lesson="Every iteration must include at least one validation command.",
                            tags=["testing", "discipline"],
                        )
                    ],
                    context=reason,
                )
                critic_feedback = reason
                continue

            command_values = [spec.raw for spec in command_specs]
            self._update_run_meta(run_id, last_command=command_values[-1], iteration=iteration, current_stage="executor")
            execution_results = executor.run(command_specs)
            self._write_json(iter_dir / "execution.json", [item.to_dict() for item in execution_results])
            self.publish_event(
                f"run:{run_id}",
                {
                    "type": "execution_update",
                    "run_id": run_id,
                    "iteration": iteration,
                    "results": [item.to_dict() for item in execution_results],
                },
            )

            pytest_results = self._extract_pytest_results(execution_results)
            tests_ran_iteration = bool(pytest_results)
            tests_passed_iteration = tests_ran_iteration and all(
                item.returncode == 0 and not item.timed_out for item in pytest_results
            )
            tests_failed_iteration = tests_ran_iteration and not tests_passed_iteration

            if tests_ran_iteration:
                tests_ran = True
                tests_passed = tests_passed_iteration

            if tdd_mode and not tests_ran_iteration:
                reason = "TDD mode requires pytest execution in every iteration."
                telemetry.event(
                    "tdd_violation",
                    {"run_id": run_id, "iteration": iteration, "reason": reason, **project_meta},
                )
                self._append_timeline(
                    run_id,
                    "tdd_violation",
                    {"iteration": iteration, "reason": reason, **project_meta},
                )
                self._record_iteration_metric(
                    telemetry,
                    iteration,
                    "retry",
                    len(execution_results),
                    self._count_passed_commands(execution_results),
                    started,
                )
                memory.append_lessons(
                    goal=effective_goal,
                    lessons=[
                        LessonProposal(
                            lesson="TDD loops must run pytest to observe red/green feedback each iteration.",
                            tags=["tdd", "testing"],
                        )
                    ],
                    context=reason,
                )
                critic_feedback = reason
                continue

            self._update_run_meta(run_id, current_stage="critic")
            critic_output = critic.review(
                goal=effective_goal,
                plan_json=plan.to_dict(),
                coder_json=coder_output.to_dict(),
                execution_results=execution_results,
                tdd_mode=tdd_mode,
                tdd_red_phase_complete=tdd_red_phase_complete,
            )
            self._write_json(iter_dir / "critic.json", critic_output.to_dict())

            self._update_run_meta(run_id, current_stage="memory")
            memory.append_lessons(goal=effective_goal, lessons=critic_output.lessons, context=critic_output.analysis)

            commands_passed = self._count_passed_commands(execution_results)
            iteration_status = critic_output.status
            if tdd_mode and not tdd_red_phase_complete:
                if tests_failed_iteration:
                    tdd_red_phase_complete = True
                    iteration_status = "retry"
                    critic_feedback = (
                        "TDD red phase complete. Keep tests and implement minimal code to make them pass."
                    )
                    self._append_timeline(
                        run_id,
                        "tdd_red_phase_complete",
                        {"iteration": iteration, **project_meta},
                    )
                    telemetry.event(
                        "tdd_red_phase_complete",
                        {"run_id": run_id, "iteration": iteration, **project_meta},
                    )
                else:
                    iteration_status = "retry"
                    critic_feedback = (
                        "TDD mode expects failing tests before implementation. Strengthen tests first."
                    )
                    self._append_timeline(
                        run_id,
                        "tdd_violation",
                        {
                            "iteration": iteration,
                            "reason": "Tests passed before observing required red phase.",
                            **project_meta,
                        },
                    )
                    telemetry.event(
                        "tdd_violation",
                        {
                            "run_id": run_id,
                            "iteration": iteration,
                            "reason": "Tests passed before observing required red phase.",
                            **project_meta,
                        },
                    )

            self._record_iteration_metric(
                telemetry,
                iteration,
                iteration_status,
                len(execution_results),
                commands_passed,
                started,
            )

            telemetry.event(
                "iteration_complete",
                {
                    "run_id": run_id,
                    "iteration": iteration,
                    "status": iteration_status,
                    "written_paths": written_paths,
                    "commands_passed": commands_passed,
                    "commands_total": len(execution_results),
                    "analysis": critic_output.analysis,
                    "planner_model_used": planner_model_used,
                    "coder_model_used": coder_model_used,
                    "critic_model_used": critic_model_used,
                    "tdd_mode": tdd_mode,
                    "tdd_red_phase_complete": tdd_red_phase_complete,
                    **project_meta,
                },
            )

            self._append_timeline(
                run_id,
                "iteration_complete",
                {
                    "iteration": iteration,
                    "status": iteration_status,
                    "analysis": critic_output.analysis,
                    "commands_total": len(execution_results),
                    "commands_passed": commands_passed,
                    "planner_model_used": planner_model_used,
                    "coder_model_used": coder_model_used,
                    "critic_model_used": critic_model_used,
                    "tdd_mode": tdd_mode,
                    "tdd_red_phase_complete": tdd_red_phase_complete,
                    **project_meta,
                },
            )

            if (
                self._is_success(critic_output, coder_output, execution_results)
                and (not tdd_mode or (tdd_red_phase_complete and tests_passed_iteration))
            ):
                if tdd_mode and iterations_until_green is None:
                    iterations_until_green = iteration
                telemetry.event(
                    "run_complete",
                    {
                        "run_id": run_id,
                        "goal": effective_goal,
                        "success": True,
                        "iterations_used": iteration,
                        "planner_model_used": planner_model_used,
                        "coder_model_used": coder_model_used,
                        "critic_model_used": critic_model_used,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                        **project_meta,
                    },
                )
                self._finalize_success(
                    run_id,
                    critic_output.analysis,
                    iteration,
                    tests_ran,
                    tests_passed,
                    result_payload={
                        "goal": effective_goal,
                        "status": "success",
                        "analysis": critic_output.analysis,
                        "iterations_used": iteration,
                        "planner_model_used": planner_model_used,
                        "coder_model_used": coder_model_used,
                        "critic_model_used": critic_model_used,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                    },
                    iterations_until_green=iterations_until_green,
                )
                return

            if critic_output.status == "abort":
                telemetry.event(
                    "run_complete",
                    {
                        "run_id": run_id,
                        "goal": effective_goal,
                        "success": False,
                        "iterations_used": iteration,
                        "planner_model_used": planner_model_used,
                        "coder_model_used": coder_model_used,
                        "critic_model_used": critic_model_used,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                        **project_meta,
                    },
                )
                self._finalize_failure(
                    run_id,
                    critic_output.analysis,
                    iteration,
                    execution_results,
                    tests_ran,
                    tests_passed,
                    iterations_until_green=iterations_until_green,
                )
                return

            if not (tdd_mode and not tdd_red_phase_complete):
                critic_feedback = self._render_feedback(critic_output, execution_results)

        telemetry.event(
            "run_complete",
            {
                "run_id": run_id,
                "goal": effective_goal,
                "success": False,
                "iterations_used": iteration_limit,
                "planner_model_used": planner_model_used,
                "coder_model_used": coder_model_used,
                "critic_model_used": critic_model_used,
                "tdd_mode": tdd_mode,
                "iterations_until_green": iterations_until_green,
                **project_meta,
            },
        )
        self._finalize_failure(
            run_id,
            "Iteration limit reached before meeting success criteria.",
            iteration_limit,
            execution_results=[],
            tests_ran=tests_ran,
            tests_passed=tests_passed,
            iterations_until_green=iterations_until_green,
        )

    def _preview_teach_conflicts(
        self, teacher: MemoryTeacherQA, memory: LongTermMemory, message: str
    ) -> list[dict[str, str]]:
        # Uses internal extractor methods to preview potential writes before persisting.
        extracted = teacher._extract_facts(message)  # type: ignore[attr-defined]
        heuristic = teacher._heuristic_facts(message)  # type: ignore[attr-defined]
        rows = teacher._merge_fact_rows(extracted.get("facts", []), heuristic)  # type: ignore[attr-defined]

        conflicts: list[dict[str, str]] = []
        for row in rows:
            subject = str(row.get("subject", "")).strip()
            predicate = str(row.get("predicate", "")).strip()
            object_value = str(row.get("object", "")).strip()
            if not subject or not predicate or not object_value:
                continue
            try:
                existing = memory.get_fact(subject, predicate)
            except ValueError:
                existing = None
            if existing and existing.object.casefold() != object_value.casefold():
                conflicts.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "existing": existing.object,
                        "incoming": object_value,
                    }
                )
        return conflicts

    def _detect_risky_edit_reasons(self, edits: list[ValidatedEdit]) -> list[str]:
        reasons: list[str] = []
        total_bytes = sum(len(item.content.encode("utf-8")) for item in edits)

        if total_bytes >= self.settings.risky_large_edit_bytes:
            reasons.append(
                f"Large edit set: {total_bytes} bytes exceeds threshold {self.settings.risky_large_edit_bytes}."
            )

        if len(edits) >= self.settings.risky_multi_file_threshold:
            reasons.append(
                f"Multi-file rewrite: {len(edits)} files meets threshold {self.settings.risky_multi_file_threshold}."
            )

        for edit in edits:
            if edit.relative_path == "long_term.json" or edit.relative_path.endswith("memory/long_term.json"):
                reasons.append("Potential memory overwrite detected.")
                break

        return reasons

    def _build_diff_entries(self, edits: list[ValidatedEdit]) -> list[DiffEntry]:
        rows: list[DiffEntry] = []
        for edit in edits:
            existed_before = edit.absolute_path.exists()
            before = ""
            if existed_before:
                try:
                    before = edit.absolute_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    before = ""
            after = edit.content
            diff_lines = list(
                difflib.unified_diff(
                    before.splitlines(),
                    after.splitlines(),
                    fromfile=f"a/{edit.relative_path}",
                    tofile=f"b/{edit.relative_path}",
                    lineterm="",
                )
            )
            added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
            rows.append(
                DiffEntry(
                    path=edit.relative_path,
                    added=added,
                    removed=removed,
                    patch="\n".join(diff_lines),
                    change_type="edited" if existed_before else "new",
                    workspace_path=str(edit.absolute_path),
                    before_preview=self._clip_preview(before),
                    after_preview=self._clip_preview(after),
                )
            )
        return rows

    @staticmethod
    def _clip_preview(text: str, max_chars: int = 1800) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[truncated preview]"

    def _register_approval(
        self,
        run_id: str,
        iteration: int,
        approval_type: str,
        reasons: list[str],
        payload: dict[str, Any],
    ) -> str:
        approval_id = f"{run_id}-{iteration}-{uuid.uuid4().hex[:6]}"
        diff_count = 0
        file_count = 0
        if isinstance(payload.get("diffs"), list):
            diff_count = len(payload.get("diffs", []))
            file_count = len(
                {
                    str(item.get("path", "")).strip()
                    for item in payload.get("diffs", [])
                    if isinstance(item, dict) and str(item.get("path", "")).strip()
                }
            )
        high_risk = approval_type == "risky_edit"
        record = {
            "id": approval_id,
            "run_id": run_id,
            "iteration": iteration,
            "type": approval_type,
            "reasons": reasons,
            "payload": payload,
            "diff_count": diff_count,
            "file_count": file_count,
            "requires_typed_confirmation": high_risk,
            "status": "pending",
            "decision": None,
            "decision_note": "",
            "created_at": self._now_iso(),
        }
        with self._lock:
            self._pending_approvals[approval_id] = record
        self._append_timeline(run_id, "approval_requested", record)
        self._append_audit(
            run_id=run_id,
            action="approval_requested",
            payload={"approval_id": approval_id, "type": approval_type, "reasons": reasons, "file_count": file_count},
        )
        self.publish_event("status", {"type": "approval_needed", "run_id": run_id, "approval": record})
        self.publish_event(f"run:{run_id}", {"type": "approval_needed", "run_id": run_id, "approval": record})
        return approval_id

    def _wait_for_approval(self, approval_id: str, timeout_sec: int = 1800) -> str:
        started = time.monotonic()
        while time.monotonic() - started < timeout_sec:
            with self._lock:
                approval = self._pending_approvals.get(approval_id)
                if not approval:
                    return "reject"
                decision = approval.get("decision")
                if decision in {"approve", "reject"}:
                    return str(decision)
            time.sleep(0.2)
        with self._lock:
            approval = self._pending_approvals.get(approval_id)
            if approval and approval.get("status") == "pending":
                approval["status"] = "rejected"
                approval["decision"] = "reject"
                approval["decision_note"] = "Approval timed out"
                approval["decided_at"] = self._now_iso()
        return "reject"

    def _finalize_success(
        self,
        run_id: str,
        message: str,
        iteration: int,
        tests_ran: bool,
        tests_passed: bool | None,
        result_payload: dict[str, Any],
        iterations_until_green: int | None = None,
    ) -> None:
        self._write_json(self._run_dir(run_id) / "result.json", result_payload)
        self._update_run_meta(
            run_id,
            status="success",
            success=True,
            message=message,
            ended_at=self._now_iso(),
            iteration=iteration,
            progress_percent=100,
            tests_ran=tests_ran,
            tests_passed=tests_passed,
            iterations_until_green=iterations_until_green,
            current_stage="memory",
        )
        self.publish_event("status", {"type": "run_success", "run_id": run_id, "iteration": iteration, "message": message})
        self.publish_event(f"run:{run_id}", {"type": "run_success", "run_id": run_id, "iteration": iteration, "message": message})

    def _finalize_failure(
        self,
        run_id: str,
        message: str,
        iteration: int,
        execution_results: list[ExecutionResult],
        tests_ran: bool,
        tests_passed: bool | None,
        iterations_until_green: int | None = None,
    ) -> None:
        iter_dir = self._run_dir(run_id) / "iterations" / f"{iteration:03d}"
        diffs = self._read_json(iter_dir / "diffs.json", default=[])
        failure = self._build_failure_details(execution_results, diffs if isinstance(diffs, list) else [])
        explanation = failure["summary"]
        self._write_json(
            self._run_dir(run_id) / "result.json",
            {
                "status": "failed",
                "analysis": message,
                "iteration": iteration,
                "explain_failure": explanation,
                "failure_details": failure,
            },
        )
        self._update_run_meta(
            run_id,
            status="failed",
            success=False,
            message=message,
            failure_explanation=explanation,
            failure_details=failure,
            ended_at=self._now_iso(),
            iteration=iteration,
            progress_percent=100,
            tests_ran=tests_ran,
            tests_passed=tests_passed,
            iterations_until_green=iterations_until_green,
            current_stage="critic",
        )
        self.publish_event("status", {"type": "run_failed", "run_id": run_id, "iteration": iteration, "failure": failure})
        self.publish_event(f"run:{run_id}", {"type": "run_failed", "run_id": run_id, "iteration": iteration, "failure": failure})

    def _finalize_stopped(
        self,
        run_id: str,
        message: str,
        tests_ran: bool,
        tests_passed: bool | None,
        iterations_until_green: int | None = None,
    ) -> None:
        self._write_json(self._run_dir(run_id) / "result.json", {"status": "stopped", "message": message})
        self._update_run_meta(
            run_id,
            status="stopped",
            success=False,
            message=message,
            ended_at=self._now_iso(),
            tests_ran=tests_ran,
            tests_passed=tests_passed,
            iterations_until_green=iterations_until_green,
            current_stage="executor",
        )
        self.publish_event("status", {"type": "run_stopped", "run_id": run_id, "message": message})
        self.publish_event(f"run:{run_id}", {"type": "run_stopped", "run_id": run_id, "message": message})

    def _finalize_rejected(
        self,
        run_id: str,
        message: str,
        tests_ran: bool = False,
        tests_passed: bool | None = None,
        iterations_until_green: int | None = None,
    ) -> None:
        self._write_json(self._run_dir(run_id) / "result.json", {"status": "rejected", "message": message})
        self._update_run_meta(
            run_id,
            status="rejected",
            success=False,
            message=message,
            ended_at=self._now_iso(),
            tests_ran=tests_ran,
            tests_passed=tests_passed,
            iterations_until_green=iterations_until_green,
            current_stage="safety",
        )
        self.publish_event("status", {"type": "run_rejected", "run_id": run_id, "message": message})
        self.publish_event(f"run:{run_id}", {"type": "run_rejected", "run_id": run_id, "message": message})

    def _build_failure_details(self, results: list[ExecutionResult], diffs: list[dict[str, Any]]) -> dict[str, Any]:
        if not results:
            return {
                "category": "unknown",
                "summary": "No execution results available.",
                "top_errors": [],
                "related_files": [],
                "suggested_actions": ["retry", "open run details"],
            }
        failing = [row for row in results if row.returncode != 0 or row.timed_out]
        if not failing:
            return {
                "category": "unknown",
                "summary": "Commands passed; failure likely came from critic abort or iteration cap.",
                "top_errors": [],
                "related_files": self._related_files(diffs),
                "suggested_actions": ["retry", "review critic output"],
            }

        first = failing[0]
        if first.timed_out:
            category = "timeout"
            top_errors = [f"Command timed out: {first.command} after {first.duration_sec}s."]
        else:
            snippets: list[str] = []
            raw_lines = (first.stderr + "\n" + first.stdout).splitlines()
            for line in raw_lines:
                clean = line.strip()
                if not clean:
                    continue
                if any(marker in clean.lower() for marker in ["error", "failed", "exception", "traceback"]) or clean.startswith("E "):
                    snippets.append(clean)
                if len(snippets) >= 5:
                    break
            top_errors = snippets[:3]
            category = self._categorize_failure(first.stderr + "\n" + first.stdout)

        detail = "; ".join(top_errors) if top_errors else "No clear error snippet in output."
        related_files = self._related_files(diffs)
        summary = f"First failing command: {first.command} (rc={first.returncode}). {detail}"
        return {
            "category": category,
            "summary": summary,
            "top_errors": top_errors,
            "related_files": related_files,
            "suggested_actions": ["retry", "rollback", "open file", "approve patch"],
        }

    @staticmethod
    def _categorize_failure(text: str) -> str:
        lowered = text.lower()
        if "syntaxerror" in lowered:
            return "syntax"
        if "modulenotfounderror" in lowered or "importerror" in lowered:
            return "import"
        if "assert" in lowered or "assertionerror" in lowered:
            return "test_assertion"
        if "timeout" in lowered:
            return "timeout"
        return "runtime"

    def _related_files(self, diffs: list[dict[str, Any]]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for item in diffs[:8]:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            workspace_path = str(item.get("workspace_path", "")).strip()
            if workspace_path:
                open_path = workspace_path
            else:
                open_path = self.config.workspace_dir.joinpath(path).as_posix()
            safe_open_path = open_path.replace('"', '\\"')
            rows.append(
                {
                    "path": path,
                    "vscode_command": f'code -g "{safe_open_path}:1"',
                }
            )
        return rows

    def _list_project_files(self, project_dir: Path | None, limit: int = 300) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not project_dir:
            return rows
        if not project_dir.exists() or not project_dir.is_dir():
            return rows

        count = 0
        for path in sorted(project_dir.rglob("*")):
            if count >= max(1, min(limit, 2000)):
                break
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(project_dir).as_posix()
            except ValueError:
                continue
            if not relative:
                continue
            try:
                after_preview = self._clip_preview(path.read_text(encoding="utf-8"), max_chars=1200)
            except UnicodeDecodeError:
                after_preview = "[binary file preview not available]"
            except OSError:
                after_preview = "[file preview unavailable]"

            rows.append(
                {
                    "path": relative,
                    "change_type": "workspace",
                    "workspace_path": str(path),
                    "added": 0,
                    "removed": 0,
                    "after_preview": after_preview,
                }
            )
            count += 1
        return rows

    def _list_workspace_files(self, limit: int = 20_000) -> tuple[list[dict[str, Any]], list[str], int, int, bool]:
        rows: list[dict[str, Any]] = []
        dir_rows: list[str] = []
        workspace_root = self.config.workspace_dir.resolve()
        if not workspace_root.exists() or not workspace_root.is_dir():
            return rows, dir_rows, 0, 0, False

        max_items = max(1, min(limit, 50_000))
        total_files = 0
        total_dirs = 0
        for path in sorted(workspace_root.rglob("*")):
            if path.is_dir():
                try:
                    relative_dir = path.relative_to(workspace_root).as_posix()
                except ValueError:
                    continue
                if relative_dir:
                    total_dirs += 1
                    if len(dir_rows) < max_items:
                        dir_rows.append(relative_dir)
                continue
            if not path.is_file() or path.is_symlink():
                continue
            try:
                relative = path.relative_to(workspace_root).as_posix()
            except ValueError:
                continue
            if not relative:
                continue
            total_files += 1
            if len(rows) >= max_items:
                continue

            try:
                after_preview = self._clip_preview(path.read_text(encoding="utf-8"), max_chars=1200)
            except UnicodeDecodeError:
                after_preview = "[binary file preview not available]"
            except OSError:
                after_preview = "[file preview unavailable]"

            rows.append(
                {
                    "path": relative,
                    "change_type": "workspace",
                    "workspace_path": str(path),
                    "added": 0,
                    "removed": 0,
                    "after_preview": after_preview,
                }
            )

        truncated = total_files > len(rows) or total_dirs > len(dir_rows)
        return rows, dir_rows, total_files, total_dirs, truncated

    def workspace_tree(self, limit: int = 20_000) -> dict[str, Any]:
        files, dirs, total_files, total_dirs, truncated = self._list_workspace_files(limit=limit)
        entries: list[dict[str, str]] = []
        entries.extend({"path": row, "type": "folder"} for row in dirs if row)
        entries.extend(
            {"path": str(item.get("path", "")).strip(), "type": "file"}
            for item in files
            if str(item.get("path", "")).strip()
        )
        entries.sort(key=lambda row: (str(row.get("path", "")).count("/"), str(row.get("path", ""))))
        return {
            "workspace_dir": str(self.config.workspace_dir),
            "entries": entries,
            "file_total": total_files,
            "dir_total": total_dirs,
            "truncated": truncated,
        }

    @staticmethod
    def _render_feedback(critic: CriticOutput, results: list[ExecutionResult]) -> str:
        lines = [critic.analysis, "Next actions:"]
        for action in critic.next_actions:
            lines.append(f"- {action}")
        if results:
            lines.append("Command results:")
            for item in results:
                lines.append(
                    f"- `{item.command}` => rc={item.returncode}, timeout={item.timed_out}, "
                    f"stdout_len={len(item.stdout)}, stderr_len={len(item.stderr)}"
                )
        return "\n".join(lines)

    @staticmethod
    def _count_passed_commands(results: list[ExecutionResult]) -> int:
        return sum(1 for item in results if item.returncode == 0 and not item.timed_out)

    @staticmethod
    def _is_test_path(relative_path: str) -> bool:
        path = relative_path.strip().replace("\\", "/")
        return path.startswith("tests/")

    @classmethod
    def _summarize_tdd_test_edits(cls, edits: list[ValidatedEdit]) -> tuple[bool, bool]:
        has_tests_edit = any(cls._is_test_path(item.relative_path) for item in edits)
        has_non_test_edit = any(not cls._is_test_path(item.relative_path) for item in edits)
        return has_tests_edit, has_non_test_edit

    @staticmethod
    def _command_mentions_pytest(raw_command: str) -> bool:
        lowered = raw_command.strip().lower()
        if lowered == "pytest" or lowered.startswith("pytest "):
            return True
        return lowered.startswith("python -m pytest")

    @classmethod
    def _prepare_commands_for_iteration(cls, commands: list[str], tdd_mode: bool) -> list[str]:
        prepared = [item for item in commands if item.strip()]
        if tdd_mode and not any(cls._command_mentions_pytest(item) for item in prepared):
            prepared.append("pytest -q")
        return prepared

    @classmethod
    def _extract_pytest_results(cls, results: list[ExecutionResult]) -> list[ExecutionResult]:
        return [item for item in results if cls._command_mentions_pytest(item.command)]

    @staticmethod
    def _is_success(critic: CriticOutput, coder_output: CoderOutput, results: list[ExecutionResult]) -> bool:
        commands_ok = bool(results) and all(item.returncode == 0 and not item.timed_out for item in results)
        if critic.status == "success" and commands_ok:
            return True
        return coder_output.done and commands_ok

    def _record_iteration_metric(
        self,
        telemetry: TelemetryLogger,
        iteration: int,
        status: str,
        commands_total: int,
        commands_passed: int,
        started: float,
    ) -> None:
        duration = round(time.perf_counter() - started, 3)
        telemetry.metric(
            IterationMetric(
                iteration=iteration,
                status=status,
                duration_sec=duration,
                commands_total=commands_total,
                commands_passed=commands_passed,
            )
        )

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def _read_run_meta(self, run_id: str | None) -> dict[str, Any] | None:
        if not run_id:
            return None
        return self._read_json(self._run_dir(run_id) / "meta.json", default=None)

    def _update_run_meta(self, run_id: str, **patch: Any) -> None:
        path = self._run_dir(run_id) / "meta.json"
        meta = self._read_json(path, default={})
        if not isinstance(meta, dict):
            meta = {}
        meta.update(patch)
        self._write_json(path, meta)
        event = {"type": "status_update", "run_id": run_id, "meta": meta}
        self.publish_event("status", event)
        self.publish_event(f"run:{run_id}", event)

    def _append_timeline(self, run_id: str, step: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp_utc": self._now_iso(),
            "step": step,
            "payload": payload,
        }
        path = self._run_dir(run_id) / "timeline.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        self.publish_event("status", {"type": "timeline", "run_id": run_id, "record": record})
        self.publish_event(f"run:{run_id}", {"type": "timeline", "run_id": run_id, "record": record})
        self.publish_event("logs", {"type": "timeline", "run_id": run_id, "record": record})

    def _append_audit(self, run_id: str, action: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp_utc": self._now_iso(),
            "action": action,
            "payload": payload,
        }
        path = self._run_dir(run_id) / "audit.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def _save_settings(self) -> None:
        self._write_json(self.settings_file, asdict(self.settings))

    def _load_settings(self) -> ControlSettings:
        raw = self._read_json(self.settings_file, default={})
        if not isinstance(raw, dict):
            raw = {}
        settings = ControlSettings.from_dict(raw)
        self._write_json(self.settings_file, asdict(settings))
        return settings

    def workspace_edit_file(self, relative_path: str, content: str, actor: str = "web_ui") -> dict[str, Any]:
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. Manual file edits are blocked in read-only mode.")
        target, normalized = self._resolve_workspace_path(relative_path)
        if target.exists() and target.is_dir():
            raise ValueError("Target path is a folder. File edit requires a file path.")
        clean_content = str(content).replace("\x00", "")
        if len(clean_content) > 1_000_000:
            raise ValueError("File content exceeds max length (1000000 chars).")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(clean_content, encoding="utf-8")
        payload = {
            "action": "edit_file",
            "path": normalized,
            "workspace_path": str(target),
            "size_bytes": len(clean_content.encode("utf-8")),
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("logs", {"type": "workspace_file_edited", "payload": payload})
        return payload

    def workspace_delete_path(self, relative_path: str, actor: str = "web_ui") -> dict[str, Any]:
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. Manual deletes are blocked in read-only mode.")
        target, normalized = self._resolve_workspace_path(relative_path)
        if not target.exists():
            raise ValueError("Path not found in workspace.")

        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
            target_type = "folder"
        else:
            target.unlink()
            target_type = "file"
        payload = {
            "action": "delete_path",
            "path": normalized,
            "path_type": target_type,
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("logs", {"type": "workspace_path_deleted", "payload": payload})
        return payload

    def workspace_rename_path(self, relative_path: str, new_relative_path: str, actor: str = "web_ui") -> dict[str, Any]:
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. Manual rename is blocked in read-only mode.")
        source_path, source_rel = self._resolve_workspace_path(relative_path)
        if not source_path.exists():
            raise ValueError("Source path not found in workspace.")
        target_path, target_rel = self._resolve_workspace_path(new_relative_path)
        if target_path.exists():
            raise ValueError("Destination path already exists.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.rename(target_path)
        payload = {
            "action": "rename_path",
            "from_path": source_rel,
            "to_path": target_rel,
            "path_type": "folder" if target_path.is_dir() else "file",
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("logs", {"type": "workspace_path_renamed", "payload": payload})
        return payload

    def _resolve_workspace_path(self, relative_path: str) -> tuple[Path, str]:
        raw = str(relative_path).replace("\\", "/").strip()
        cleaned = "/".join(part for part in raw.split("/") if part not in {"", "."})
        if not cleaned:
            raise ValueError("Path cannot be empty.")
        if cleaned.startswith("..") or "/.." in cleaned:
            raise ValueError("Path escapes workspace boundary.")

        workspace_root = self.config.workspace_dir.resolve()
        candidate = (workspace_root / cleaned).resolve()
        if candidate == workspace_root or workspace_root not in candidate.parents:
            raise ValueError("Path escapes workspace boundary.")
        return candidate, cleaned

    def _resolve_existing_goal_target(self, target_path: str) -> tuple[Path, str, str]:
        target, normalized = self._resolve_workspace_path(target_path)
        if not target.exists():
            raise ValueError("Selected workspace target does not exist.")
        target_type = "folder" if target.is_dir() and not target.is_symlink() else "file"
        return target, normalized, target_type

    def _resolve_goal_project_path(self, project_path: str | Path) -> Path:
        workspace_root = self.config.workspace_dir.resolve()
        candidate = Path(project_path)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        candidate = candidate.resolve()
        if candidate != workspace_root and workspace_root not in candidate.parents:
            raise ValueError("Project path escapes workspace boundary.")
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError("Project path does not exist in workspace.")
        return candidate

    @staticmethod
    def _augment_goal_with_workspace_target(goal: str, target_path: str, target_type: str) -> str:
        clean_goal = goal.strip()
        if not target_path:
            return clean_goal
        safe_target = target_path.replace("\\", "/")
        if target_type == "file":
            directive = (
                f"\n\nWorkspace focus target: file `{safe_target}`.\n"
                "Keep changes centered on this file or nearby files in the same folder."
            )
        else:
            directive = (
                f"\n\nWorkspace focus target: folder `{safe_target}`.\n"
                "Create or update files inside this folder tree."
            )
        return f"{clean_goal}{directive}".strip()

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines[-limit:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    @staticmethod
    def _tail_lines(path: Path, limit: int) -> list[str]:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-limit:]

    @staticmethod
    def _detect_memory_conflicts(facts: list[Any]) -> list[dict[str, Any]]:
        by_key: dict[tuple[str, str], set[str]] = {}
        for raw in facts:
            if not isinstance(raw, dict):
                continue
            subject = str(raw.get("subject", "")).strip()
            predicate = str(raw.get("predicate", "")).strip()
            object_value = str(raw.get("object", "")).strip()
            if not subject or not predicate or not object_value:
                continue
            key = (subject.casefold(), predicate.casefold())
            by_key.setdefault(key, set()).add(object_value)

        rows: list[dict[str, Any]] = []
        for (subject, predicate), values in by_key.items():
            if len(values) > 1:
                rows.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "values": sorted(values),
                        "warning": "Conflicting memory values detected.",
                    }
                )
        return rows

    @staticmethod
    def _is_safe_run_id(run_id: str) -> bool:
        return bool(RUN_ID_PATTERN.match(run_id))

    @staticmethod
    def _new_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"run_{stamp}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_user_text(value: str, *, field_name: str, max_chars: int = 4_000) -> str:
        text = str(value).replace("\x00", "").strip()
        if not text:
            raise ValueError(f"{field_name} cannot be empty.")
        if len(text) > max_chars:
            raise ValueError(f"{field_name} exceeds max length ({max_chars} chars).")
        return text


def create_control_center(config: AgentConfig | None = None, data_root: Path | None = None) -> DavidControlCenter:
    return DavidControlCenter(config=config, data_root=data_root)


__all__ = ["DavidControlCenter", "create_control_center", "ControlSettings"]
