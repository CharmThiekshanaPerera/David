from __future__ import annotations

import difflib
import io
import json
import logging
import re
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import AgentConfig, load_config
from agent.contracts import CoderOutput, CriticOutput, ExecutionResult, LessonProposal
from agent.coder import Coder
from agent.critic import Critic
from agent.llm import OllamaClient
from agent.main import parse_chat_command
from agent.memory import LongTermMemory
from agent.planner import Planner
from agent.qa import MemoryTeacherQA
from agent.safety import SafetyError, SafetyGuard, ValidatedEdit
from agent.telemetry import IterationMetric, TelemetryLogger
from agent.workspace import WorkspaceInspector
from agent.executor import RestrictedExecutor


RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{6,80}$")


@dataclass
class ControlSettings:
    safe_mode: bool = False
    rate_limit_seconds: int = 3
    max_iterations_override: int = 0
    risky_large_edit_bytes: int = 50_000
    risky_multi_file_threshold: int = 4
    run_preview_default: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlSettings":
        return cls(
            safe_mode=bool(data.get("safe_mode", False)),
            rate_limit_seconds=max(0, int(data.get("rate_limit_seconds", 3))),
            max_iterations_override=max(0, int(data.get("max_iterations_override", 0))),
            risky_large_edit_bytes=max(1_000, int(data.get("risky_large_edit_bytes", 50_000))),
            risky_multi_file_threshold=max(2, int(data.get("risky_multi_file_threshold", 4))),
            run_preview_default=bool(data.get("run_preview_default", False)),
        )


@dataclass
class DiffEntry:
    path: str
    added: int
    removed: int
    patch: str


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

        self._logger = logging.getLogger("david.control_center")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.FileHandler(self.config.logs_dir / "web_control_center.log", encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

        self.settings = self._load_settings()

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
        }

    def get_settings(self) -> dict[str, Any]:
        return {
            **asdict(self.settings),
            "model": self.config.model,
            "allowed_commands": list(self.config.allowed_commands),
            "max_iterations_default": self.config.max_iterations,
            "workspace_dir": str(self.config.workspace_dir),
        }

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = asdict(self.settings)
        for key in list(current.keys()):
            if key in payload:
                current[key] = payload[key]
        self.settings = ControlSettings.from_dict(current)
        self._save_settings()
        return self.get_settings()

    def effective_max_iterations(self) -> int:
        if self.settings.max_iterations_override > 0:
            return self.settings.max_iterations_override
        return self.config.max_iterations

    def start_run(self, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        command = str(payload.get("command", "")).strip()
        preview = bool(payload.get("preview", self.settings.run_preview_default))

        if not command:
            mode = str(payload.get("mode", "")).strip().lower()
            content = str(payload.get("payload", "")).strip()
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
                "started_at": self._now_iso(),
                "ended_at": None,
                "model": self.config.model,
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
            }
            self._write_json(run_dir / "meta.json", meta)

            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._execute_run,
                args=(run_id, mode, content, preview, cancel_event),
                daemon=True,
                name=f"david-run-{run_id}",
            )

            self._active_thread = worker
            self._active_run_id = run_id
            self._active_cancel = cancel_event
            self._last_run_started_at = now
            worker.start()

        return True, {"run_id": run_id, "status": "queued"}

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

        self._update_run_meta(run_id, status="stopping", message="Stop requested by user.")
        return {"stopped": True, "run_id": run_id}

    def submit_approval(self, approval_id: str, decision: str, note: str = "") -> tuple[bool, dict[str, Any]]:
        choice = decision.strip().lower()
        if choice not in {"approve", "reject"}:
            return False, {"error": "Decision must be approve or reject."}

        with self._lock:
            approval = self._pending_approvals.get(approval_id)
            if not approval:
                return False, {"error": "Approval request not found."}
            if approval.get("status") != "pending":
                return False, {"error": "Approval is already resolved."}

            approval["status"] = "approved" if choice == "approve" else "rejected"
            approval["decision"] = choice
            approval["decision_note"] = note.strip()
            approval["decided_at"] = self._now_iso()

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
        }

    def retry_run(self, run_id: str) -> tuple[bool, dict[str, Any]]:
        current = self.get_run(run_id)
        if not current:
            return False, {"error": "Run not found."}
        command = str(current["meta"].get("command", "")).strip()
        if not command:
            return False, {"error": "Original command missing."}
        return self.start_run({"command": command, "preview": False})

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

    def _execute_run(self, run_id: str, mode: str, payload: str, preview: bool, cancel_event: threading.Event) -> None:
        try:
            self._update_run_meta(run_id, status="running")
            self._append_timeline(run_id, "run_started", {"mode": mode, "preview": preview})

            if mode == "ask":
                self._execute_ask(run_id, payload)
            elif mode == "teach":
                self._execute_teach(run_id, payload)
            else:
                self._execute_goal(run_id, payload, preview=preview, cancel_event=cancel_event)

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
        )

    def _execute_teach(self, run_id: str, message: str) -> None:
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
        )

    def _execute_goal(self, run_id: str, goal: str, preview: bool, cancel_event: threading.Event) -> None:
        llm = OllamaClient(self.config)
        planner = Planner(llm)
        coder = Coder(llm)
        critic = Critic(llm)
        safety = SafetyGuard(
            workspace_dir=self.config.workspace_dir,
            max_file_write_bytes=self.config.max_file_write_bytes,
            max_total_write_bytes=self.config.max_total_write_bytes,
            allowed_commands=self.config.allowed_commands,
        )
        executor = RestrictedExecutor(
            workspace_dir=self.config.workspace_dir,
            timeout_sec=self.config.command_timeout_sec,
            max_output_chars=self.config.max_command_output_chars,
        )
        memory = LongTermMemory(self.config.memory_file)
        workspace = WorkspaceInspector(self.config.workspace_dir)
        telemetry = TelemetryLogger(self.config.logs_dir)

        iteration_limit = self.effective_max_iterations()

        initial_snapshot = workspace.snapshot()
        memory_context = memory.render_context(goal)
        plan = planner.create_plan(goal=goal, workspace_snapshot=initial_snapshot, memory_context=memory_context)
        self._write_json(self._run_dir(run_id) / "plan.json", plan.to_dict())
        self._append_timeline(run_id, "plan_created", plan.to_dict())
        telemetry.event("plan_created", {"run_id": run_id, "goal": goal, "plan": plan.to_dict()})

        critic_feedback = "No critic feedback yet."
        tests_ran = False
        tests_passed: bool | None = None

        for iteration in range(1, iteration_limit + 1):
            if cancel_event.is_set():
                self._finalize_stopped(run_id, "Run stopped by user.", tests_ran, tests_passed)
                return

            started = time.perf_counter()
            self._update_run_meta(
                run_id,
                iteration=iteration,
                status="running",
                progress_percent=int(((iteration - 1) / max(1, iteration_limit)) * 100),
            )

            workspace_snapshot = workspace.snapshot()
            memory_context = memory.render_context(goal)
            coder_output = coder.propose(
                goal=goal,
                plan_json=plan.to_dict(),
                workspace_snapshot=workspace_snapshot,
                memory_context=memory_context,
                critic_feedback=critic_feedback,
                iteration=iteration,
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
                },
            )

            try:
                validated_edits = safety.validate_edits(coder_output.edits)
                diffs = self._build_diff_entries(validated_edits)
            except SafetyError as exc:
                reason = f"Safety guard rejected edits: {exc}"
                telemetry.event("safety_violation", {"run_id": run_id, "iteration": iteration, "error": str(exc)})
                self._write_json(iter_dir / "risk.json", {"safety_error": str(exc)})
                self._append_timeline(run_id, "safety_violation", {"iteration": iteration, "error": str(exc)})
                self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                memory.append_lessons(
                    goal=goal,
                    lessons=[
                        LessonProposal(
                            lesson="Safety validation must pass before any file write.", tags=["safety", "files"]
                        )
                    ],
                    context=reason,
                )
                critic_feedback = reason
                continue

            self._write_json(iter_dir / "diffs.json", [asdict(item) for item in diffs])

            risk_reasons = self._detect_risky_edit_reasons(validated_edits)
            self._write_json(iter_dir / "risk.json", {"reasons": risk_reasons})
            if risk_reasons:
                approval_id = self._register_approval(
                    run_id=run_id,
                    iteration=iteration,
                    approval_type="risky_edit",
                    reasons=risk_reasons,
                    payload={"diffs": [asdict(item) for item in diffs], "goal": goal},
                )
                self._update_run_meta(
                    run_id,
                    status="awaiting_approval",
                    message="Awaiting approval for risky edit set.",
                    iteration=iteration,
                )
                decision = self._wait_for_approval(approval_id)
                if decision != "approve":
                    self._finalize_rejected(run_id, "Risky edit set was rejected.", tests_ran, tests_passed)
                    return
                self._append_timeline(run_id, "approval_granted", {"iteration": iteration, "approval_id": approval_id})

            if preview:
                self._write_json(
                    self._run_dir(run_id) / "result.json",
                    {
                        "preview": True,
                        "iteration": iteration,
                        "coder": coder_output.to_dict(),
                        "diffs": [asdict(item) for item in diffs],
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
                )
                return

            written_paths = safety.apply_edits(validated_edits)

            try:
                command_specs = safety.validate_commands(coder_output.commands)
            except SafetyError as exc:
                reason = f"Safety guard rejected commands: {exc}"
                telemetry.event("safety_violation", {"run_id": run_id, "iteration": iteration, "error": str(exc)})
                self._append_timeline(run_id, "safety_violation", {"iteration": iteration, "error": str(exc)})
                self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                memory.append_lessons(
                    goal=goal,
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
                telemetry.event("execution_skipped", {"run_id": run_id, "iteration": iteration, "error": reason})
                self._append_timeline(run_id, "execution_skipped", {"iteration": iteration, "error": reason})
                self._record_iteration_metric(telemetry, iteration, "retry", 0, 0, started)
                memory.append_lessons(
                    goal=goal,
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
            self._update_run_meta(run_id, last_command=command_values[-1], iteration=iteration)
            execution_results = executor.run(command_specs)
            self._write_json(iter_dir / "execution.json", [item.to_dict() for item in execution_results])

            for result in execution_results:
                if "pytest" in result.command:
                    tests_ran = True

            all_ok = bool(execution_results) and all(item.returncode == 0 and not item.timed_out for item in execution_results)
            if tests_ran:
                tests_passed = all_ok

            critic_output = critic.review(
                goal=goal,
                plan_json=plan.to_dict(),
                coder_json=coder_output.to_dict(),
                execution_results=execution_results,
            )
            self._write_json(iter_dir / "critic.json", critic_output.to_dict())

            memory.append_lessons(goal=goal, lessons=critic_output.lessons, context=critic_output.analysis)

            commands_passed = self._count_passed_commands(execution_results)
            self._record_iteration_metric(
                telemetry,
                iteration,
                critic_output.status,
                len(execution_results),
                commands_passed,
                started,
            )

            telemetry.event(
                "iteration_complete",
                {
                    "run_id": run_id,
                    "iteration": iteration,
                    "status": critic_output.status,
                    "written_paths": written_paths,
                    "commands_passed": commands_passed,
                    "commands_total": len(execution_results),
                    "analysis": critic_output.analysis,
                },
            )

            self._append_timeline(
                run_id,
                "iteration_complete",
                {
                    "iteration": iteration,
                    "status": critic_output.status,
                    "analysis": critic_output.analysis,
                    "commands_total": len(execution_results),
                    "commands_passed": commands_passed,
                },
            )

            if self._is_success(critic_output, coder_output, execution_results):
                self._finalize_success(
                    run_id,
                    critic_output.analysis,
                    iteration,
                    tests_ran,
                    tests_passed,
                    result_payload={
                        "goal": goal,
                        "status": "success",
                        "analysis": critic_output.analysis,
                        "iterations_used": iteration,
                    },
                )
                return

            if critic_output.status == "abort":
                self._finalize_failure(
                    run_id,
                    critic_output.analysis,
                    iteration,
                    execution_results,
                    tests_ran,
                    tests_passed,
                )
                return

            critic_feedback = self._render_feedback(critic_output, execution_results)

        self._finalize_failure(
            run_id,
            "Iteration limit reached before meeting success criteria.",
            iteration_limit,
            execution_results=[],
            tests_ran=tests_ran,
            tests_passed=tests_passed,
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
            before = ""
            if edit.absolute_path.exists():
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
                )
            )
        return rows

    def _register_approval(
        self,
        run_id: str,
        iteration: int,
        approval_type: str,
        reasons: list[str],
        payload: dict[str, Any],
    ) -> str:
        approval_id = f"{run_id}-{iteration}-{uuid.uuid4().hex[:6]}"
        record = {
            "id": approval_id,
            "run_id": run_id,
            "iteration": iteration,
            "type": approval_type,
            "reasons": reasons,
            "payload": payload,
            "status": "pending",
            "decision": None,
            "decision_note": "",
            "created_at": self._now_iso(),
        }
        with self._lock:
            self._pending_approvals[approval_id] = record
        self._append_timeline(run_id, "approval_requested", record)
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
        )

    def _finalize_failure(
        self,
        run_id: str,
        message: str,
        iteration: int,
        execution_results: list[ExecutionResult],
        tests_ran: bool,
        tests_passed: bool | None,
    ) -> None:
        explanation = self._explain_failure(execution_results)
        self._write_json(
            self._run_dir(run_id) / "result.json",
            {
                "status": "failed",
                "analysis": message,
                "iteration": iteration,
                "explain_failure": explanation,
            },
        )
        self._update_run_meta(
            run_id,
            status="failed",
            success=False,
            message=message,
            failure_explanation=explanation,
            ended_at=self._now_iso(),
            iteration=iteration,
            progress_percent=100,
            tests_ran=tests_ran,
            tests_passed=tests_passed,
        )

    def _finalize_stopped(
        self,
        run_id: str,
        message: str,
        tests_ran: bool,
        tests_passed: bool | None,
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
        )

    def _finalize_rejected(
        self,
        run_id: str,
        message: str,
        tests_ran: bool = False,
        tests_passed: bool | None = None,
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
        )

    @staticmethod
    def _explain_failure(results: list[ExecutionResult]) -> str:
        if not results:
            return "No execution results available."
        failing = [row for row in results if row.returncode != 0 or row.timed_out]
        if not failing:
            return "Commands passed; failure likely came from critic abort or iteration cap."

        first = failing[0]
        if first.timed_out:
            return f"Command timed out: {first.command} after {first.duration_sec}s."

        snippets: list[str] = []
        for source in (first.stderr, first.stdout):
            for line in source.splitlines():
                clean = line.strip()
                if not clean:
                    continue
                if "error" in clean.lower() or clean.startswith("E ") or "failed" in clean.lower():
                    snippets.append(clean)
                if len(snippets) >= 3:
                    break
            if len(snippets) >= 3:
                break

        detail = "; ".join(snippets) if snippets else "No clear error snippet in output."
        return f"First failing command: {first.command} (rc={first.returncode}). {detail}"

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

    def _append_timeline(self, run_id: str, step: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp_utc": self._now_iso(),
            "step": step,
            "payload": payload,
        }
        path = self._run_dir(run_id) / "timeline.jsonl"
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


def create_control_center(config: AgentConfig | None = None, data_root: Path | None = None) -> DavidControlCenter:
    return DavidControlCenter(config=config, data_root=data_root)


__all__ = ["DavidControlCenter", "create_control_center", "ControlSettings"]
