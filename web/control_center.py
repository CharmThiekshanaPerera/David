from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import logging
import os
import queue
import re
import shutil
import subprocess
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
from web.upload_analysis import (
    SUPPORTED_UPLOAD_EXTENSIONS,
    analyze_uploaded_content,
    answer_question_from_analysis,
    sanitize_upload_filename,
)


RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{6,80}$")
IMPORT_ID_PATTERN = re.compile(r"^imp_[a-zA-Z0-9_-]{6,80}$")
UPLOAD_ID_PATTERN = re.compile(r"^upl_[a-zA-Z0-9_-]{6,80}$")
MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024
INTENT_CHOICES = {"teach", "ask", "goal", "chat"}
MEMORY_UNKNOWN_ANSWER = 'I do not know yet. Please teach me using --teach "...".'
REFLECTION_KIND = "reflection"
REFLECTION_SOURCE = "reflection_engine"
PROJECT_BRAIN_SOURCE = "project_brain_engine"
SELF_IMPROVEMENT_SOURCE = "self_improvement_engine"
SELF_IMPROVEMENT_BLOCKED_PATHS = {
    "agent/safety.py",
    "web/safety.py",
}
LEGACY_ARCHIVE_BOUNDARY_NOTE = (
    "Legacy Archive is a reflective journal of shared learning and does not replace real-world relationships."
)
FAMILY_CONTEXT_PATTERNS = (
    r"\bfather\b",
    r"\bmother\b",
    r"\bdad\b",
    r"\bmom\b",
    r"\bparent\b",
    r"\bfamily\b",
    r"\bchild\b",
    r"\bson\b",
    r"\bdaughter\b",
)
GRIEF_CONTEXT_PATTERNS = (
    r"\bgrief\b",
    r"\bgrieving\b",
    r"\bgrieve\b",
    r"\bloss\b",
    r"\bmiss\b",
    r"\bsad\b",
    r"\bsadness\b",
    r"\blonely\b",
    r"\bheartbroken\b",
    r"\bhurting\b",
)
CRISIS_CONTEXT_PATTERNS = (
    r"\bsuicid(?:e|al)\b",
    r"\bkill myself\b",
    r"\bend my life\b",
    r"\bhurt myself\b",
    r"\bself[- ]harm\b",
    r"\bdon't want to live\b",
    r"\bdo not want to live\b",
    r"\bcan't go on\b",
    r"\bcannot go on\b",
)
GROWTH_CONTEXT_PATTERNS = (
    r"\bgrowth\b",
    r"\bimprov(?:e|ed|ing)\b",
    r"\blearn(?:ed|ing)\b",
    r"\bevolv(?:e|ed|ing)\b",
    r"\bprogress\b",
    r"\bstruggl(?:e|ed|ing)\b",
    r"\bover time\b",
)
EXPLICIT_TEACH_SIGNAL_PATTERNS = (
    r"\bremember this\b",
    r"\bsave this\b",
    r"\bteach\b",
    r"\bmy name is\b",
    r"\bi am your\b",
    r"\bfrom now on\b",
    r"\byou should know\b",
    r"\bcall me\b",
    r"\bmy birth(?:day| date|date) is\b",
    r"\bmy favorite (?:saying|quote) is\b",
    r"\bour shared (?:goal|routine) is\b",
    r"\bshared (?:goal|routine)[: ]",
)
GRIEF_MEMORY_CONFIRM_PATTERNS = (
    r"\b(?:save|store|remember)\s+(?:this|it)\s+(?:as\s+)?(?:a\s+)?(?:fact|memory)\b",
    r"\b(?:permanent|permanently)\s+(?:save|store|remember)\b",
    r"\bcommit\s+(?:this|it)\s+to\s+memory\b",
    r"\bconfirm\s+(?:save|memory)\b",
)
INTENT_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "on",
    "in",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "you",
    "me",
    "my",
    "i",
    "it",
    "this",
    "that",
    "with",
    "from",
    "as",
    "at",
    "by",
}
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
    companion_mode: bool = True
    memory_insight_mode: bool = True
    parent_teaching_mode: bool = False
    autonomous_self_improvement_mode: bool = True
    demo_mode: bool = False
    personality_warmth: int = 55
    personality_verbosity: int = 55
    personality_curiosity: int = 50
    planner_model: str = ""
    coder_model: str = ""
    critic_model: str = ""
    tdd_mode: bool = False
    upload_vision_mode: bool = False
    upload_vision_model: str = ""
    voice_mode_enabled: bool = False
    voice_text_only_mode: bool = False
    voice_input_mode: str = "manual"
    voice_vad_threshold: float = 0.035
    voice_vad_silence_ms: int = 900
    voice_vad_min_speech_ms: int = 300
    voice_style: str = "warm"
    voice_rate: int = 100
    voice_stt_engine: str = "none"
    voice_stt_model: str = "base"
    voice_stt_language: str = "en"
    voice_stt_command: str = "whisper"
    voice_whisper_cpp_command: str = "whisper-cli"
    voice_whisper_cpp_model_path: str = ""
    voice_tts_engine: str = "browser"
    voice_tts_command: str = "piper"
    voice_tts_model_path: str = ""
    voice_chunk_chars: int = 180

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlSettings":
        planner_model = str(data.get("planner_model", "")).strip()
        coder_model = str(data.get("coder_model", "")).strip()
        critic_model = str(data.get("critic_model", "")).strip()
        upload_vision_model = str(data.get("upload_vision_model", "")).strip()
        voice_style = str(data.get("voice_style", "warm")).strip().lower()
        if voice_style not in {"warm", "balanced", "clear"}:
            voice_style = "warm"
        voice_stt_engine = str(data.get("voice_stt_engine", "none")).strip().lower()
        if voice_stt_engine not in {"none", "whisper_cli", "whisper_cpp"}:
            voice_stt_engine = "none"
        voice_tts_engine = str(data.get("voice_tts_engine", "browser")).strip().lower()
        if voice_tts_engine not in {"browser", "piper", "none"}:
            voice_tts_engine = "browser"
        voice_input_mode = str(data.get("voice_input_mode", "manual")).strip().lower()
        if voice_input_mode == "ptt":
            voice_input_mode = "manual"
        if voice_input_mode not in {"manual", "vad"}:
            voice_input_mode = "manual"

        def _safe_command(name: str, default: str) -> str:
            clean = str(data.get(name, default)).strip() or default
            if re.match(r"^[A-Za-z0-9_./:-]+$", clean):
                return clean
            return default

        def _safe_language(value: Any) -> str:
            clean = re.sub(r"[^a-zA-Z-]", "", str(value or "").strip())
            if not clean:
                return ""
            return clean[:12].lower()

        def _bounded(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(data.get(name, default))
            except (TypeError, ValueError):
                value = default
            return max(low, min(high, value))

        def _bounded_float(name: str, default: float, low: float, high: float) -> float:
            try:
                value = float(data.get(name, default))
            except (TypeError, ValueError):
                value = float(default)
            return max(low, min(high, value))

        def _pct(name: str, default: int) -> int:
            try:
                value = int(data.get(name, default))
            except (TypeError, ValueError):
                value = default
            return max(0, min(100, value))
        return cls(
            safe_mode=bool(data.get("safe_mode", False)),
            rate_limit_seconds=max(0, int(data.get("rate_limit_seconds", 3))),
            max_iterations_override=max(0, int(data.get("max_iterations_override", 0))),
            risky_large_edit_bytes=max(1_000, int(data.get("risky_large_edit_bytes", 50_000))),
            risky_multi_file_threshold=max(2, int(data.get("risky_multi_file_threshold", 4))),
            run_preview_default=bool(data.get("run_preview_default", False)),
            companion_mode=bool(data.get("companion_mode", True)),
            memory_insight_mode=bool(data.get("memory_insight_mode", True)),
            parent_teaching_mode=bool(data.get("parent_teaching_mode", False)),
            autonomous_self_improvement_mode=bool(data.get("autonomous_self_improvement_mode", True)),
            demo_mode=bool(data.get("demo_mode", False)),
            personality_warmth=_pct("personality_warmth", 55),
            personality_verbosity=_pct("personality_verbosity", 55),
            personality_curiosity=_pct("personality_curiosity", 50),
            planner_model=planner_model,
            coder_model=coder_model,
            critic_model=critic_model,
            tdd_mode=bool(data.get("tdd_mode", False)),
            upload_vision_mode=bool(data.get("upload_vision_mode", False)),
            upload_vision_model=upload_vision_model,
            voice_mode_enabled=bool(data.get("voice_mode_enabled", False)),
            voice_text_only_mode=bool(data.get("voice_text_only_mode", False)),
            voice_input_mode=voice_input_mode,
            voice_vad_threshold=_bounded_float(
                "voice_vad_threshold" if "voice_vad_threshold" in data else "vad_threshold",
                0.035,
                0.005,
                0.2,
            ),
            voice_vad_silence_ms=_bounded(
                "voice_vad_silence_ms" if "voice_vad_silence_ms" in data else "vad_silence_ms",
                900,
                250,
                2500,
            ),
            voice_vad_min_speech_ms=_bounded(
                "voice_vad_min_speech_ms" if "voice_vad_min_speech_ms" in data else "vad_min_speech_ms",
                300,
                120,
                4000,
            ),
            voice_style=voice_style,
            voice_rate=_bounded("voice_rate", 100, 60, 180),
            voice_stt_engine=voice_stt_engine,
            voice_stt_model=str(data.get("voice_stt_model", "base")).strip() or "base",
            voice_stt_language=_safe_language(data.get("voice_stt_language", "en")) or "en",
            voice_stt_command=_safe_command("voice_stt_command", "whisper"),
            voice_whisper_cpp_command=_safe_command("voice_whisper_cpp_command", "whisper-cli"),
            voice_whisper_cpp_model_path=str(data.get("voice_whisper_cpp_model_path", "")).strip(),
            voice_tts_engine=voice_tts_engine,
            voice_tts_command=_safe_command("voice_tts_command", "piper"),
            voice_tts_model_path=str(data.get("voice_tts_model_path", "")).strip(),
            voice_chunk_chars=_bounded("voice_chunk_chars", 180, 80, 400),
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
        self.uploads_root = (self.data_root / "uploads").resolve()
        self.uploads_files_root = (self.uploads_root / "files").resolve()
        self.uploads_index_file = (self.uploads_root / "index.json").resolve()
        self.settings_file = (self.data_root / "control_settings.json").resolve()
        self.self_improvements_file = (self.data_root / "self_improvements.json").resolve()
        self.mock_data_root = (self.project_root / "data" / "mock").resolve()
        self.agent_sandbox_root = (self.config.workspace_dir / "agent_sandbox").resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.agent_sandbox_root.mkdir(parents=True, exist_ok=True)
        self.uploads_files_root.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._active_thread: threading.Thread | None = None
        self._active_run_id: str | None = None
        self._active_cancel: threading.Event | None = None
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._last_run_started_at: float = 0.0
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {"status": [], "logs": []}
        self._csrf_token = uuid.uuid4().hex
        self._pending_memory_overwrites: dict[str, dict[str, Any]] = {}
        self._pending_parent_teaching: dict[str, dict[str, Any]] = {}
        self._chat_session_by_actor: dict[str, str] = {}
        self._imported_bundle_views: dict[str, dict[str, Any]] = {}
        self._imported_bundle_order: list[str] = []
        self._max_imported_bundles = 25
        self._max_uploaded_files = 500
        self._conversations_file = self.config.memory_file.parent / "conversations.jsonl"
        self._demo_runtime: dict[str, Any] = {
            "initialized": False,
            "approvals": [],
            "pending_overwrites": {},
            "conversation_appends": [],
            "pending_parent_teaching": {},
            "approval_audit_appends": {},
        }
        self._ensure_conversation_store()
        self._ensure_upload_store()

        self._logger = logging.getLogger("david.control_center")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.FileHandler(self.config.logs_dir / "web_control_center.log", encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

        self.app_version = self._resolve_app_version()
        self.git_commit = self._resolve_git_commit()
        self.version_stamp = self._compose_version_stamp(self.app_version, self.git_commit)
        self.settings = self._load_settings()
        self._validate_role_models()
        ensure_workspace_layout(self.config.workspace_dir)

    def get_status(self) -> dict[str, Any]:
        demo_mode = self._demo_mode_enabled()
        with self._lock:
            active = self._active_run_id
            if demo_mode:
                pending_count = len(
                    [
                        p
                        for p in self._demo_list_approvals_runtime()
                        if str(p.get("status", "")).strip().lower() == "pending"
                    ]
                )
                self_improvement_pending_count = sum(
                    1
                    for item in self._demo_self_improvement_rows()
                    if str(item.get("status", "")).strip().lower() == "pending"
                )
            else:
                pending_count = len([p for p in self._pending_approvals.values() if p.get("status") == "pending"])
                self_improvement_pending_count = sum(
                    1
                    for item in self._self_improvement_rows()
                    if str(item.get("status", "")).strip().lower() == "pending"
                )

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
            "pending_self_improvements": self_improvement_pending_count,
            "autonomous_self_improvement_mode": self.settings.autonomous_self_improvement_mode,
            "demo_mode": demo_mode,
            "app_version": self.app_version,
            "git_commit": self.git_commit,
            "version_stamp": self.version_stamp,
            "imported_bundle_count": len(self.list_imported_bundles(limit=500)),
            "uploaded_file_count": len(self.list_uploaded_files(limit=5_000)),
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
        payload = {
            **asdict(self.settings),
            "vad_threshold": self.settings.voice_vad_threshold,
            "vad_silence_ms": self.settings.voice_vad_silence_ms,
            "vad_min_speech_ms": self.settings.voice_vad_min_speech_ms,
            "demo_mode_env_override": self._demo_mode_env_enabled(),
            "model": self.config.model,
            "planner_model_default": self.config.planner_model,
            "coder_model_default": self.config.coder_model,
            "critic_model_default": self.config.critic_model,
            "allowed_commands": list(self.config.allowed_commands),
            "max_iterations_default": self.config.max_iterations,
            "workspace_dir": str(self.config.workspace_dir),
            "goal_templates": self.goal_templates(),
            "app_version": self.app_version,
            "git_commit": self.git_commit,
            "version_stamp": self.version_stamp,
        }
        if self._demo_mode_enabled():
            mock_settings = self._read_demo_json("mock_settings.json", default={})
            if isinstance(mock_settings, dict):
                if "ui_theme_default" in mock_settings:
                    payload["ui_theme_default"] = str(mock_settings.get("ui_theme_default", "dark")).strip() or "dark"
                if "ui_background_enabled" in mock_settings:
                    payload["ui_background_enabled"] = bool(mock_settings.get("ui_background_enabled"))
                if "demo_badge_text" in mock_settings:
                    payload["demo_badge_text"] = str(mock_settings.get("demo_badge_text", "DEMO")).strip() or "DEMO"
        return payload

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        alias_map = {
            "vad_threshold": "voice_vad_threshold",
            "vad_silence_ms": "voice_vad_silence_ms",
            "vad_min_speech_ms": "voice_vad_min_speech_ms",
        }
        for alias, canonical in alias_map.items():
            if alias in payload and canonical not in payload:
                payload[canonical] = payload[alias]
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
        if self._demo_mode_enabled():
            payload = self._read_demo_json("mock_models.json", default={})
            rows = payload.get("models", []) if isinstance(payload, dict) else []
            models = [str(item).strip() for item in rows if str(item).strip()]
            if models:
                return sorted(set(models))
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
        if self.settings.upload_vision_model:
            self.settings.upload_vision_model = sanitize_model_name(
                self.settings.upload_vision_model,
                "upload_vision_model",
            )

    def start_run(self, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return False, {
                "error": "Demo mode is active. Runs are read from deterministic mock fixtures. Disable demo mode to execute live runs.",
            }
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

    def classify_chat_intent(self, message: str) -> dict[str, Any]:
        text = self._sanitize_user_text(message, field_name="message")
        parsed = parse_chat_command(text)
        if parsed and parsed[0] in INTENT_CHOICES:
            intent = str(parsed[0])
            topics = self._extract_topics(parsed[1] or text)
            return {"intent": intent, "confidence": 1.0, "topics": topics, "reason": "explicit_command"}

        lowered = text.casefold()
        ask_like = text.endswith("?") or bool(re.match(r"^(who|what|when|where|why|how|is|are|can|could|do|does|did)\b", lowered))
        goal_like = bool(
            re.match(
                r"^(build|create|implement|refactor|fix|update|add|remove|improve|write|generate)\b",
                lowered,
            )
        ) or "workspace" in lowered
        explicit_teach_like = self._has_explicit_teach_signal(text)
        soft_teach_like = bool(re.search(r"\bremember\b", lowered))
        sensitive_context = self._is_grief_context(text) or self._is_crisis_context(text)
        teach_like = explicit_teach_like or soft_teach_like
        if sensitive_context and soft_teach_like and not explicit_teach_like:
            teach_like = False

        if teach_like:
            intent = "teach"
            confidence = 0.88
            reason = "memory_statement"
        elif ask_like:
            intent = "ask"
            confidence = 0.82
            reason = "question_shape"
        elif goal_like:
            intent = "goal"
            confidence = 0.7
            reason = "task_instruction"
        else:
            intent = "chat"
            confidence = 0.62
            reason = "default_chat"
        return {"intent": intent, "confidence": confidence, "topics": self._extract_topics(text), "reason": reason}

    def ask_memory(self, question: str, actor: str = "web_ui") -> dict[str, Any]:
        if self._demo_mode_enabled():
            payload = self._demo_ask_memory(question, actor=actor.strip() or "web_ui")
            self.publish_event("status", {"type": "memory_ask_answered", "payload": payload})
            self.publish_event("logs", {"type": "memory_ask_answered", "payload": payload})
            return payload
        clean_question = self._sanitize_user_text(question, field_name="question")
        payload = self._ask_memory_first(clean_question, actor=actor.strip() or "web_ui", session_id="")
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
        if self._demo_mode_enabled():
            payload = self._demo_teach_memory(
                message,
                actor=actor.strip() or "web_ui",
                confirm_conflict=confirm_conflict,
            )
            self.publish_event("status", {"type": "memory_teach_completed", "payload": payload})
            self.publish_event("logs", {"type": "memory_teach_completed", "payload": payload})
            return payload
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. /teach is blocked in read-only mode.")

        clean_message = self._sanitize_user_text(message, field_name="message")
        payload = self._teach_confirmed(
            clean_message,
            actor=actor.strip() or "web_ui",
            session_id="",
            allow_overwrite=confirm_conflict,
            legacy_mode=True,
        )
        if payload.get("status") == "overwrite_confirmation_required":
            payload["status"] = "conflict"
            payload["requires_confirmation"] = True
            payload["notes"] = "Conflict detected. Confirm to continue."
            payload["stored_facts"] = []
            payload["stored_count"] = 0
            payload["skipped_items"] = []
        if payload.get("status") == "stored":
            payload["confirmed_conflict"] = bool(payload.get("conflicts")) and bool(confirm_conflict)
            payload["requires_confirmation"] = False

        self.publish_event("status", {"type": "memory_teach_completed", "payload": payload})
        self.publish_event("logs", {"type": "memory_teach_completed", "payload": payload})
        return payload

    def chat_message(
        self,
        message: str,
        *,
        intent: str = "",
        confirm_save: bool = False,
        parent_teaching_mode: bool = False,
        session_id: str = "",
        actor: str = "web_ui",
        publish_events: bool = True,
    ) -> dict[str, Any]:
        if self._demo_mode_enabled():
            payload = self._demo_chat_message(
                message,
                intent=intent,
                confirm_save=confirm_save,
                parent_teaching_mode=parent_teaching_mode,
                session_id=session_id,
                actor=actor,
            )
            if publish_events:
                self.publish_event("status", {"type": "memory_chat_response", "payload": payload})
                self.publish_event("logs", {"type": "memory_chat_response", "payload": payload})
            return payload
        clean_message = self._sanitize_user_text(message, field_name="message")
        actor_value = actor.strip() or "web_ui"
        detected = self.classify_chat_intent(clean_message)
        selected_intent = self._normalize_intent(intent) or str(detected.get("intent", "chat"))
        active_session_id = self._resolve_chat_session_id(session_id=session_id, actor=actor_value)
        parent_mode_active = bool(parent_teaching_mode or self.settings.parent_teaching_mode)
        if (
            parent_mode_active
            and active_session_id in self._pending_parent_teaching
            and selected_intent in {"chat", "teach"}
        ):
            selected_intent = "teach"
        topics = detected.get("topics", [])
        confidence = float(detected.get("confidence", 0.5))

        user_turn = self._append_conversation_turn(
            session_id=active_session_id,
            role="user",
            text=clean_message,
            intent=selected_intent,
            topics=topics if isinstance(topics, list) else [],
            confidence=confidence,
            actor=actor_value,
        )
        is_first_assistant_turn = not self._session_has_assistant_turn(active_session_id)

        response: dict[str, Any]
        if selected_intent == "ask":
            response = self._ask_memory_first(
                clean_message,
                actor=actor_value,
                session_id=active_session_id,
                force_transparency=is_first_assistant_turn,
            )
            assistant_text = str(response.get("answer", "")).strip() or "No answer generated."
        elif selected_intent == "teach":
            if not bool(confirm_save):
                preview = self._extract_teach_memory(clean_message)
                response = {
                    "mode": "teach",
                    "status": "confirmation_required",
                    "message": clean_message,
                    "requires_confirmation": True,
                    "confirm_save": False,
                    "actor": actor_value,
                    "session_id": active_session_id,
                    "triples": preview.get("triples", []),
                    "aliases": preview.get("aliases", []),
                    "notes": preview.get("notes", ""),
                    "topics": preview.get("topics", []),
                    "timestamp_utc": self._now_iso(),
                }
                assistant_text = "I can save this as memory after you confirm Teach."
            else:
                parent_response = (
                    self._handle_parent_teaching_turn(
                        message=clean_message,
                        actor=actor_value,
                        session_id=active_session_id,
                    )
                    if parent_mode_active
                    else None
                )
                if parent_response is not None:
                    response = parent_response
                    if str(response.get("status", "")) == "parent_teaching_clarify_required":
                        assistant_text = str(response.get("question", "")).strip() or "How should I apply this while debugging?"
                    else:
                        stored_values = int(response.get("stored_value_count", 0))
                        category = str(response.get("category_label", "Values")).strip()
                        assistant_text = f"Stored {stored_values} {category} teaching entry."
                else:
                    response = self._teach_confirmed(
                        clean_message,
                        actor=actor_value,
                        session_id=active_session_id,
                        allow_overwrite=False,
                        legacy_mode=False,
                    )
                    if response.get("status") == "overwrite_confirmation_required":
                        assistant_text = "I detected conflicting memory. Confirm overwrite to continue."
                    else:
                        stored_count = int(response.get("stored_count", 0))
                        assistant_text = f"Saved {stored_count} memory facts."
        elif selected_intent == "goal":
            started, run_result = self.start_run(
                {
                    "mode": "goal",
                    "payload": clean_message,
                    "preview": False,
                }
            )
            response = {
                "mode": "goal",
                "status": "queued" if started else "error",
                "run": run_result,
                "message": clean_message,
                "actor": actor_value,
                "session_id": active_session_id,
                "timestamp_utc": self._now_iso(),
            }
            assistant_text = (
                f"Goal queued: {run_result.get('run_id', '')}"
                if started
                else f"Goal could not start: {run_result.get('error', 'unknown error')}"
            )
        else:
            if self.settings.companion_mode:
                response = self._compose_companion_chat_response(
                    clean_message,
                    session_id=active_session_id,
                    actor=actor_value,
                    force_transparency=is_first_assistant_turn,
                )
            else:
                response = {
                    "mode": "chat",
                    "status": "ok",
                    "message": clean_message,
                    "reply": (
                        "I can chat naturally. If you want me to remember something, switch to Teach and confirm save."
                    ),
                    "citations": [],
                    "used_memory": {
                        "facts": [],
                        "conversations": [],
                        "lessons": [],
                        "values": [],
                        "projects": [],
                    },
                    "memory_insight": self._build_memory_insight(
                        enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor_value)),
                        matched_facts=[],
                        matched_conversations=[],
                        matched_lessons=[],
                        facts_source=[],
                        conversations_source=[],
                        lessons_source=[],
                    ),
                    "timestamp_utc": self._now_iso(),
                }
            response["actor"] = actor_value
            response["session_id"] = active_session_id
            assistant_text = str(response["reply"])

        if self.settings.companion_mode:
            requires_transparency = (
                is_first_assistant_turn
                or self._is_family_context(clean_message)
                or self._is_grief_context(clean_message)
                or self._is_crisis_context(clean_message)
            )
            transparency_line = self._compose_ai_transparency_line()
            if requires_transparency and transparency_line not in assistant_text:
                assistant_text = f"{assistant_text} {transparency_line}".strip()
                if str(response.get("mode", "")) == "ask":
                    response["answer"] = assistant_text
                elif str(response.get("mode", "")) == "chat":
                    response["reply"] = assistant_text

        assistant_turn = self._append_conversation_turn(
            session_id=active_session_id,
            role="assistant",
            text=assistant_text,
            intent=selected_intent,
            topics=topics if isinstance(topics, list) else [],
            confidence=confidence,
            actor=actor_value,
            metadata={
                "response_status": str(response.get("status", "")),
                "citations": response.get("citations", []),
                "memory_insight": response.get("memory_insight", {}),
                "used_memory": response.get("used_memory", {}),
                "takeaways": response.get("stored_facts", []),
            },
        )

        payload = {
            "mode": "chat",
            "message": clean_message,
            "detected_intent": detected.get("intent", "chat"),
            "detected_confidence": round(confidence, 3),
            "selected_intent": selected_intent,
            "confirm_save": bool(confirm_save),
            "parent_teaching_mode": parent_mode_active,
            "crisis_support": bool(
                self._is_crisis_context(clean_message) or self._compose_crisis_support_line() in assistant_text
            ),
            "session_id": active_session_id,
            "user_turn": user_turn,
            "assistant_turn": assistant_turn,
            "response": response,
            "timestamp_utc": self._now_iso(),
        }
        reflection = self._record_conversation_reflection(
            message=clean_message,
            selected_intent=selected_intent,
            response=response,
            session_id=active_session_id,
            user_message_id=str(user_turn.get("message_id", "")),
        )
        if reflection:
            payload["reflection"] = reflection
            try:
                autonomous = self.autonomous_self_improvement_cycle(
                    trigger="conversation",
                    trigger_id=str(reflection.get("reflection_key", "")).strip(),
                    actor="david_autonomous",
                )
                payload["autonomous_self_improvement"] = autonomous
            except Exception:  # pragma: no cover - defensive boundary
                self._logger.exception("autonomous self-improvement cycle failed for conversation")
        if publish_events:
            self.publish_event("status", {"type": "memory_chat_response", "payload": payload})
            self.publish_event("logs", {"type": "memory_chat_response", "payload": payload})
        return payload

    def memory_facts(self, query: str = "", limit: int = 500) -> dict[str, Any]:
        if self._demo_mode_enabled():
            payload = self._demo_memory_payload_runtime()
            facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
            conflicts = self._detect_memory_conflicts(facts)
            query_tokens = set(self._tokenize_text(query))
            filtered: list[dict[str, Any]] = []
            for row in facts:
                if not isinstance(row, dict):
                    continue
                if query_tokens:
                    text = f"{row.get('subject', '')} {row.get('predicate', '')} {row.get('object', '')}"
                    if not (query_tokens & set(self._tokenize_text(text))):
                        continue
                filtered.append(row)
            return {
                "facts": filtered[-max(1, min(limit, 5000)) :],
                "conflicts": conflicts,
                "conflict_count": len(conflicts),
                "total": len(filtered),
            }
        payload = self._read_memory_payload()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        conflicts = self._detect_memory_conflicts(facts)
        query_tokens = set(self._tokenize_text(query))
        filtered: list[dict[str, Any]] = []
        for row in facts:
            if not isinstance(row, dict):
                continue
            if query_tokens:
                text = f"{row.get('subject', '')} {row.get('predicate', '')} {row.get('object', '')}"
                fact_tokens = set(self._tokenize_text(text))
                if not (query_tokens & fact_tokens):
                    continue
            filtered.append(row)
        return {
            "facts": filtered[-max(1, min(limit, 5000)) :],
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "total": len(filtered),
        }

    def memory_conversations(self, session_id: str = "", limit: int = 500) -> dict[str, Any]:
        if self._demo_mode_enabled():
            rows = self._demo_conversation_rows_runtime()[-max(1, min(limit, 5000)) :]
            clean_session = self._sanitize_session_id(session_id)
            if clean_session:
                rows = [row for row in rows if str(row.get("session_id", "")) == clean_session]
            return {
                "conversations": rows,
                "session_id": clean_session,
                "total": len(rows),
            }
        rows = self._read_jsonl(self._conversations_file, limit=max(1, min(limit, 5000)))
        clean_session = self._sanitize_session_id(session_id)
        if clean_session:
            rows = [row for row in rows if str(row.get("session_id", "")) == clean_session]
        return {
            "conversations": rows,
            "session_id": clean_session,
            "total": len(rows),
        }

    def clear_conversations(self, session_id: str = "", actor: str = "web_ui") -> tuple[bool, dict[str, Any]]:
        if self.settings.safe_mode:
            return False, {"error": "Safe mode is enabled. Conversation clearing is blocked in read-only mode."}
        clean_session = self._sanitize_session_id(session_id)
        actor_value = actor.strip() or "web_ui"
        removed_count = 0
        remaining_count = 0

        if self._demo_mode_enabled():
            self._ensure_demo_runtime()
            with self._lock:
                base_raw = self._demo_runtime.get("base_conversations", [])
                append_raw = self._demo_runtime.get("conversation_appends", [])
                base_rows = [row for row in base_raw if isinstance(row, dict)] if isinstance(base_raw, list) else []
                append_rows = [row for row in append_raw if isinstance(row, dict)] if isinstance(append_raw, list) else []
                if clean_session:
                    kept_base = [row for row in base_rows if str(row.get("session_id", "")) != clean_session]
                    kept_appends = [row for row in append_rows if str(row.get("session_id", "")) != clean_session]
                else:
                    kept_base = []
                    kept_appends = []
                removed_count = (len(base_rows) + len(append_rows)) - (len(kept_base) + len(kept_appends))
                remaining_count = len(kept_base) + len(kept_appends)
                self._demo_runtime["base_conversations"] = kept_base
                self._demo_runtime["conversation_appends"] = kept_appends
                if clean_session:
                    self._chat_session_by_actor = {
                        key: value for key, value in self._chat_session_by_actor.items() if str(value) != clean_session
                    }
                else:
                    self._chat_session_by_actor = {}
        else:
            with self._lock:
                try:
                    lines = self._conversations_file.read_text(encoding="utf-8").splitlines()
                except OSError as exc:
                    return False, {"error": f"Failed to read conversation store: {exc}"}
                kept_lines: list[str] = []
                total_rows = 0
                for line in lines:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        if clean_session:
                            kept_lines.append(line)
                        continue
                    if not isinstance(row, dict):
                        if clean_session:
                            kept_lines.append(line)
                        continue
                    total_rows += 1
                    if clean_session and str(row.get("session_id", "")) == clean_session:
                        removed_count += 1
                        continue
                    if clean_session:
                        kept_lines.append(line)
                if not clean_session:
                    removed_count = total_rows
                remaining_count = max(total_rows - removed_count, 0)
                try:
                    if clean_session:
                        content = "\n".join(kept_lines)
                        self._conversations_file.write_text(content + ("\n" if content else ""), encoding="utf-8")
                    else:
                        self._conversations_file.write_text("", encoding="utf-8")
                except OSError as exc:
                    return False, {"error": f"Failed to write conversation store: {exc}"}

                if clean_session:
                    self._chat_session_by_actor = {
                        key: value for key, value in self._chat_session_by_actor.items() if str(value) != clean_session
                    }
                else:
                    self._chat_session_by_actor = {}

        payload = {
            "status": "cleared",
            "scope": "session" if clean_session else "all",
            "session_id": clean_session,
            "removed_count": int(removed_count),
            "remaining_count": int(remaining_count),
            "actor": actor_value,
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("status", {"type": "memory_conversations_cleared", "payload": payload})
        self.publish_event("logs", {"type": "memory_conversations_cleared", "payload": payload})
        return True, payload

    def chat_sessions(self, limit: int = 120) -> list[dict[str, Any]]:
        if self._demo_mode_enabled():
            rows = self._demo_conversation_rows_runtime()
        else:
            rows = self._read_jsonl(self._conversations_file, limit=20_000)
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            session = str(row.get("session_id", "")).strip()
            if not session:
                continue
            info = grouped.setdefault(
                session,
                {
                    "session_id": session,
                    "started_at": str(row.get("timestamp_utc", "")),
                    "last_message_at": str(row.get("timestamp_utc", "")),
                    "message_count": 0,
                    "pinned_count": 0,
                    "intents": {},
                    "preview": "",
                },
            )
            info["message_count"] = int(info.get("message_count", 0)) + 1
            stamp = str(row.get("timestamp_utc", ""))
            if stamp and (not str(info.get("started_at", "")) or stamp < str(info.get("started_at", ""))):
                info["started_at"] = stamp
            if stamp and (not str(info.get("last_message_at", "")) or stamp > str(info.get("last_message_at", ""))):
                info["last_message_at"] = stamp
            if bool(row.get("pinned", False)):
                info["pinned_count"] = int(info.get("pinned_count", 0)) + 1

            intent_name = self._normalize_intent(row.get("intent", ""))
            if intent_name:
                intent_map = info.get("intents", {})
                intent_map[intent_name] = int(intent_map.get(intent_name, 0)) + 1
                info["intents"] = intent_map
            if str(row.get("role", "")) == "user":
                preview = str(row.get("text", "")).strip()
                if preview:
                    info["preview"] = preview[:180]

        ordered = sorted(grouped.values(), key=lambda item: str(item.get("last_message_at", "")), reverse=True)
        return ordered[: max(1, min(limit, 500))]

    def confirm_memory_overwrite(
        self,
        overwrite_id: str,
        *,
        decision: str,
        actor: str = "web_ui",
    ) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return self._demo_confirm_memory_overwrite(overwrite_id, decision=decision, actor=actor)
        clean_id = str(overwrite_id).strip()
        if not clean_id:
            return False, {"error": "overwrite_id is required."}
        choice = str(decision).strip().lower()
        if choice not in {"approve", "reject"}:
            return False, {"error": "decision must be approve or reject."}

        with self._lock:
            pending = self._pending_memory_overwrites.get(clean_id)
            if not pending:
                return False, {"error": "Overwrite request not found."}
            if str(pending.get("status", "pending")) != "pending":
                return False, {"error": "Overwrite request is already resolved."}
            pending["status"] = "approved" if choice == "approve" else "rejected"
            pending["decided_at"] = self._now_iso()
            pending["decided_by"] = actor.strip() or "web_ui"

        if choice == "reject":
            payload = {
                "mode": "teach",
                "status": "rejected",
                "overwrite_id": clean_id,
                "message": str(pending.get("message", "")),
                "actor": actor.strip() or "web_ui",
                "timestamp_utc": self._now_iso(),
            }
            self.publish_event("status", {"type": "memory_teach_overwrite_rejected", "payload": payload})
            self.publish_event("logs", {"type": "memory_teach_overwrite_rejected", "payload": payload})
            return True, payload

        payload = self._apply_teach_extract(
            extracted=pending.get("extracted", {}),
            message=str(pending.get("message", "")),
            actor=actor.strip() or "web_ui",
            session_id=str(pending.get("session_id", "")),
            allow_overwrite=True,
            overwrite_id=clean_id,
            legacy_mode=False,
        )
        self.publish_event("status", {"type": "memory_teach_overwrite_confirmed", "payload": payload})
        self.publish_event("logs", {"type": "memory_teach_overwrite_confirmed", "payload": payload})
        return True, payload

    def submit_approval(
        self,
        approval_id: str,
        decision: str,
        note: str = "",
        actor: str = "local_user",
        confirmation: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return self._demo_submit_approval(
                approval_id=approval_id,
                decision=decision,
                note=note,
                actor=actor,
                confirmation=confirmation,
            )
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
        if self._demo_mode_enabled():
            return self._demo_list_approvals_runtime()
        with self._lock:
            rows = list(self._pending_approvals.values())
        rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return rows

    def list_self_improvements(self, limit: int = 160) -> dict[str, Any]:
        try:
            limit_value = int(limit or 160)
        except (TypeError, ValueError):
            limit_value = 160
        max_limit = max(1, min(limit_value, 500))
        if self._demo_mode_enabled():
            rows = self._demo_self_improvement_rows()
        else:
            with self._lock:
                rows = self._self_improvement_rows()
        rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        pending_count = sum(1 for item in rows if str(item.get("status", "")).strip().lower() == "pending")
        merged_count = sum(1 for item in rows if str(item.get("status", "")).strip().lower() == "merged")
        autonomous_count = 0
        for item in rows:
            metadata = item.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            if bool(metadata.get("autonomous", False)) or str(item.get("actor", "")).strip().lower().startswith(
                "david_autonomous"
            ):
                autonomous_count += 1
        return {
            "items": rows[:max_limit],
            "total": len(rows),
            "pending_count": pending_count,
            "merged_count": merged_count,
            "autonomous_count": autonomous_count,
            "sandbox_root": str(self.agent_sandbox_root),
        }

    def propose_self_improvement(
        self,
        payload: dict[str, Any],
        *,
        actor: str = "david_agent",
    ) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return False, {"error": "Demo mode is active. Direct self-improvement proposal writes are disabled."}
        if not isinstance(payload, dict):
            return False, {"error": "Payload must be an object."}
        title = self._sanitize_user_text(payload.get("title", ""), field_name="title", max_chars=220)
        summary = self._sanitize_user_text(payload.get("summary", ""), field_name="summary", max_chars=6_000)
        rationale = str(payload.get("rationale", "")).replace("\x00", "").strip()
        if rationale and len(rationale) > 8_000:
            return False, {"error": "rationale exceeds max length (8000 chars)."}
        metadata_raw = payload.get("metadata", {})
        try:
            metadata = self._sanitize_json_metadata(metadata_raw, max_chars=20_000)
        except ValueError as exc:
            return False, {"error": str(exc)}

        files = payload.get("files", [])
        if not isinstance(files, list) or not files:
            return False, {"error": "files must be a non-empty list."}
        if len(files) > 40:
            return False, {"error": "files exceeds max count (40)."}

        created_at = self._now_iso()
        proposal_id = f"improve_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        proposal_dir = (self.agent_sandbox_root / proposal_id).resolve()
        prototype_root = (proposal_dir / "prototype").resolve()
        proposal_doc_path = (proposal_dir / "PROPOSAL.md").resolve()
        metadata_path = (proposal_dir / "metadata.json").resolve()

        changes: list[dict[str, Any]] = []
        touched_paths: set[str] = set()
        for idx, row in enumerate(files):
            if not isinstance(row, dict):
                return False, {"error": f"files[{idx}] must be an object."}
            target_value = str(row.get("path", "")).strip()
            content = str(row.get("content", "")).replace("\x00", "")
            if len(content.encode("utf-8")) > 1_000_000:
                return False, {"error": f"files[{idx}].content exceeds max size (1000000 bytes)."}
            try:
                target_path, normalized = self._resolve_project_file_path(target_value)
            except ValueError as exc:
                return False, {"error": str(exc)}
            if self._is_self_improvement_blocked_path(normalized):
                return False, {"error": f"Path '{normalized}' is blocked for self-improvement proposals."}
            if normalized in touched_paths:
                return False, {"error": f"Duplicate target path in files: {normalized}"}
            touched_paths.add(normalized)

            before_exists = target_path.exists() and target_path.is_file()
            before_text = ""
            if before_exists:
                try:
                    before_text = target_path.read_text(encoding="utf-8")
                except OSError as exc:
                    return False, {"error": f"Unable to read existing file '{normalized}': {exc}"}
            before_lines = before_text.splitlines()
            after_lines = content.splitlines()
            diff_lines = list(
                difflib.unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"a/{normalized}",
                    tofile=f"b/{normalized}",
                    lineterm="",
                )
            )
            added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

            sandbox_file = (prototype_root / normalized).resolve()
            if proposal_dir not in sandbox_file.parents:
                return False, {"error": "Sandbox prototype path escaped proposal folder."}
            sandbox_file.parent.mkdir(parents=True, exist_ok=True)
            sandbox_file.write_text(content, encoding="utf-8")

            changes.append(
                {
                    "path": normalized,
                    "change_type": "new" if not before_exists else "edited",
                    "sandbox_file": str(sandbox_file),
                    "added": added,
                    "removed": removed,
                    "patch": "\n".join(diff_lines),
                    "size_bytes": len(content.encode("utf-8")),
                }
            )

        proposal_md = str(payload.get("proposal_markdown", "")).replace("\x00", "").strip()
        if proposal_md and len(proposal_md) > 30_000:
            return False, {"error": "proposal_markdown exceeds max length (30000 chars)."}
        if not proposal_md:
            lines = [
                f"# Self-Improvement Proposal: {title}",
                "",
                f"- Proposal ID: `{proposal_id}`",
                f"- Source: `{SELF_IMPROVEMENT_SOURCE}`",
                f"- Created at (UTC): `{created_at}`",
                f"- Actor: `{actor.strip() or 'david_agent'}`",
                "",
                "## Summary",
                summary,
                "",
            ]
            if rationale:
                lines.extend(["## Rationale", rationale, ""])
            if metadata:
                lines.extend(["## Metadata", "```json", json.dumps(metadata, indent=2, sort_keys=True), "```", ""])
            lines.append("## Proposed File Changes")
            for item in changes:
                lines.append(
                    f"- `{item['path']}` ({item['change_type']}, +{item['added']} / -{item['removed']}, {item['size_bytes']} bytes)"
                )
            proposal_md = "\n".join(lines).strip()

        proposal_dir.mkdir(parents=True, exist_ok=True)
        proposal_doc_path.write_text(proposal_md + "\n", encoding="utf-8")
        proposal = {
            "id": proposal_id,
            "title": title,
            "summary": summary,
            "rationale": rationale,
            "status": "pending",
            "created_at": created_at,
            "updated_at": created_at,
            "source": SELF_IMPROVEMENT_SOURCE,
            "actor": actor.strip() or "david_agent",
            "sandbox_dir": str(proposal_dir),
            "proposal_doc": str(proposal_doc_path),
            "changes": changes,
            "metadata": metadata,
            "decision": None,
            "merge": None,
        }
        self._write_json(metadata_path, proposal)
        with self._lock:
            rows = self._self_improvement_rows()
            rows.append(proposal)
            self._save_self_improvement_rows(rows)
        self.publish_event("status", {"type": "self_improvement_proposed", "payload": proposal})
        self.publish_event("logs", {"type": "self_improvement_proposed", "payload": proposal})
        return True, proposal

    def decide_self_improvement(
        self,
        proposal_id: str,
        *,
        decision: str,
        actor: str = "web_ui",
        note: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return False, {"error": "Demo mode is active. Proposal decisions are read-only."}
        clean_id = str(proposal_id).strip()
        if not clean_id:
            return False, {"error": "proposal_id is required."}
        choice = str(decision).strip().lower()
        if choice not in {"approve", "reject"}:
            return False, {"error": "decision must be approve or reject."}
        note_clean = str(note).replace("\x00", "").strip()
        if len(note_clean) > 2_000:
            return False, {"error": "note exceeds max length (2000 chars)."}

        with self._lock:
            rows = self._self_improvement_rows()
            match_idx = -1
            for idx, row in enumerate(rows):
                if str(row.get("id", "")).strip() == clean_id:
                    match_idx = idx
                    break
            if match_idx < 0:
                return False, {"error": "Proposal not found."}
            current = dict(rows[match_idx])
            if str(current.get("status", "")).strip().lower() != "pending":
                return False, {"error": "Proposal is already resolved."}

        decided_at = self._now_iso()
        decision_payload = {
            "decision": choice,
            "actor": actor.strip() or "web_ui",
            "note": note_clean,
            "decided_at": decided_at,
        }
        current["decision"] = decision_payload
        current["updated_at"] = decided_at

        if choice == "reject":
            current["status"] = "rejected"
            self._update_self_improvement_record(current)
            event = {"proposal_id": clean_id, "decision": choice, "proposal": current}
            self.publish_event("status", {"type": "self_improvement_decision", "payload": event})
            self.publish_event("logs", {"type": "self_improvement_decision", "payload": event})
            return True, current

        if self.settings.safe_mode:
            return False, {"error": "Safe mode is enabled. Disable read-only mode before approving merges."}

        try:
            merged = self._merge_self_improvement_proposal(current, actor=actor.strip() or "web_ui")
        except Exception as exc:
            failed = current.copy()
            failed["status"] = "merge_failed"
            failed["updated_at"] = self._now_iso()
            failed["merge"] = {"error": str(exc), "merged_at": self._now_iso(), "actor": actor.strip() or "web_ui"}
            self._update_self_improvement_record(failed)
            return False, {"error": f"Merge failed: {exc}", "proposal": failed}

        self._update_self_improvement_record(merged)
        event = {"proposal_id": clean_id, "decision": choice, "proposal": merged}
        self.publish_event("status", {"type": "self_improvement_decision", "payload": event})
        self.publish_event("status", {"type": "self_improvement_merged", "payload": merged})
        self.publish_event("logs", {"type": "self_improvement_decision", "payload": event})
        self.publish_event("logs", {"type": "self_improvement_merged", "payload": merged})
        return True, merged

    def autonomous_self_improvement_cycle(
        self,
        *,
        trigger: str = "manual",
        trigger_id: str = "",
        actor: str = "david_autonomous",
    ) -> dict[str, Any]:
        trigger_value = str(trigger).strip().lower() or "manual"
        if trigger_value not in {"manual", "goal", "conversation"}:
            trigger_value = "manual"
        trigger_id_value = str(trigger_id).strip()
        actor_value = str(actor).strip() or "david_autonomous"

        if not self.settings.autonomous_self_improvement_mode:
            return {
                "status": "disabled",
                "trigger": trigger_value,
                "trigger_id": trigger_id_value,
                "reason": "autonomous_self_improvement_mode_off",
            }

        run_meta: dict[str, Any] = {}
        if trigger_value == "goal" and trigger_id_value:
            run_payload = self.get_run(trigger_id_value)
            if isinstance(run_payload, dict):
                maybe_meta = run_payload.get("meta")
                if isinstance(maybe_meta, dict):
                    run_meta = dict(maybe_meta)
        if not run_meta:
            latest_goal_runs = [
                row for row in self.get_runs(limit=120) if str(row.get("mode", "")).strip().lower() == "goal"
            ]
            if latest_goal_runs:
                run_meta = dict(latest_goal_runs[0])

        memory_payload = self._read_memory_payload()
        lessons = memory_payload.get("lessons", []) if isinstance(memory_payload.get("lessons"), list) else []
        reflection: dict[str, Any] | None = None
        if trigger_value == "conversation" and trigger_id_value:
            reflection = self._find_reflection_by_key(lessons, trigger_id_value)
        if reflection is None:
            reflection = self._latest_reflection_lesson(lessons)

        signals = self._autonomous_self_improvement_signals(
            trigger=trigger_value,
            run_meta=run_meta,
            reflection=reflection,
        )
        if not signals:
            return {
                "status": "skipped",
                "trigger": trigger_value,
                "trigger_id": trigger_id_value,
                "reason": "no_actionable_signals",
            }

        run_id_value = str(run_meta.get("id", run_meta.get("run_id", ""))).strip()
        reflection_key = str(reflection.get("reflection_key", "")).strip() if isinstance(reflection, dict) else ""
        signal_codes = sorted(
            {
                str(item.get("code", "")).strip()
                for item in signals
                if isinstance(item, dict) and str(item.get("code", "")).strip()
            }
        )
        signature_source = {
            "trigger": trigger_value,
            "trigger_id": trigger_id_value,
            "run_id": run_id_value,
            "reflection_key": reflection_key,
            "signal_codes": signal_codes,
        }
        signature = hashlib.sha1(
            json.dumps(signature_source, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()[:18]
        if self._self_improvement_signature_exists(signature):
            return {
                "status": "skipped",
                "trigger": trigger_value,
                "trigger_id": trigger_id_value,
                "reason": "duplicate_signature",
                "signature": signature,
            }

        if self._pending_autonomous_self_improvement_count() >= 3:
            return {
                "status": "skipped",
                "trigger": trigger_value,
                "trigger_id": trigger_id_value,
                "reason": "pending_autonomous_queue_full",
            }

        summary = self._summarize_autonomous_signals(signals, max_items=2)
        now_iso = self._now_iso()
        analysis = {
            "timestamp_utc": now_iso,
            "trigger": trigger_value,
            "trigger_id": trigger_id_value,
            "run_id": run_id_value,
            "run_status": str(run_meta.get("status", "")).strip().lower() if run_meta else "",
            "reflection_key": reflection_key,
            "signals": signals,
            "analysis_summary": summary,
            "safety_boundary": (
                "Core safety modules remain immutable: agent/safety.py and web/safety.py are blocked."
            ),
        }
        files = self._build_autonomous_self_improvement_files(analysis)
        if not files:
            return {
                "status": "skipped",
                "trigger": trigger_value,
                "trigger_id": trigger_id_value,
                "reason": "no_generated_files",
            }

        title_focus = str(signals[0].get("title", "")).strip() if signals else "Structured Learning"
        title = f"Autonomous Improvement: {title_focus}"
        rationale_lines = [
            f"Trigger: {trigger_value}{f' ({trigger_id_value})' if trigger_id_value else ''}",
            f"Run context: {run_id_value or '-'} / status={analysis.get('run_status', '-') or '-'}",
            f"Reflection key: {reflection_key or '-'}",
            "",
            "Why this change was drafted:",
            f"- {summary}",
            "- Convert lessons into concrete planning and memory-indexing heuristics.",
            "- Keep core safety constraints immutable and require human approval before merge.",
        ]
        ok, result = self.propose_self_improvement(
            {
                "title": title[:220],
                "summary": (
                    f"{summary} This proposal was drafted autonomously from structured reflections and run evidence."
                )[:6000],
                "rationale": "\n".join(rationale_lines)[:8000],
                "files": files,
                "metadata": {
                    "autonomous": True,
                    "trigger": trigger_value,
                    "trigger_id": trigger_id_value,
                    "run_id": run_id_value,
                    "reflection_key": reflection_key,
                    "signature": signature,
                    "signal_codes": signal_codes,
                    "analysis_summary": summary,
                },
            },
            actor=actor_value,
        )
        if not ok:
            return {
                "status": "error",
                "trigger": trigger_value,
                "trigger_id": trigger_id_value,
                "error": str(result.get("error", "Failed to create autonomous proposal.")),
            }

        proposed = dict(result)
        self.publish_event(
            "logs",
            {
                "type": "autonomous_self_improvement_cycle",
                "payload": {
                    "status": "proposed",
                    "trigger": trigger_value,
                    "trigger_id": trigger_id_value,
                    "proposal_id": proposed.get("id", ""),
                    "analysis_summary": summary,
                },
            },
        )
        return {
            "status": "proposed",
            "trigger": trigger_value,
            "trigger_id": trigger_id_value,
            "proposal_id": proposed.get("id", ""),
            "analysis": analysis,
            "proposal": proposed,
        }

    @staticmethod
    def _find_reflection_by_key(lessons: list[Any], reflection_key: str) -> dict[str, Any] | None:
        clean_key = str(reflection_key).strip()
        if not clean_key:
            return None
        for row in reversed(lessons):
            if not isinstance(row, dict):
                continue
            if str(row.get("reflection_key", "")).strip() == clean_key:
                return row
        return None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _autonomous_self_improvement_signals(
        self,
        *,
        trigger: str,
        run_meta: dict[str, Any],
        reflection: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        signals: dict[str, dict[str, str]] = {}

        def _add_signal(code: str, title: str, evidence: str, upgrade: str) -> None:
            clean_code = str(code).strip().lower()
            if not clean_code:
                return
            if clean_code in signals:
                return
            signals[clean_code] = {
                "code": clean_code,
                "title": str(title).strip() or "Autonomous Improvement",
                "evidence": str(evidence).strip(),
                "upgrade": str(upgrade).strip(),
            }

        run_status = str(run_meta.get("status", "")).strip().lower() if run_meta else ""
        run_id = str(run_meta.get("id", run_meta.get("run_id", ""))).strip() if run_meta else ""
        tests_ran = bool(run_meta.get("tests_ran", False)) if run_meta else False
        tests_passed = run_meta.get("tests_passed") if run_meta else None
        iterations_used = max(0, self._safe_int(run_meta.get("iteration", 0) if run_meta else 0, default=0))
        iterations_until_green = max(
            0,
            self._safe_int(run_meta.get("iterations_until_green", 0) if run_meta else 0, default=0),
        )
        run_duration_sec = self._run_total_execution_duration(run_id) if run_id else 0.0

        if trigger == "goal" and run_meta:
            _add_signal(
                "goal_reflection_loop",
                "Goal Reflection Loop",
                (
                    f"Goal run {run_id or '(latest)'} finished with status "
                    f"'{run_status or 'unknown'}' and {max(iterations_used, 1)} iteration(s)."
                ),
                "Persist a structured reasoning playbook update so future plans reuse this execution pattern.",
            )
        if run_status and run_status not in {"success", "preview_ready"}:
            _add_signal(
                "run_reliability",
                "Run Reliability Gap",
                f"Latest goal run ended with status '{run_status}'.",
                "Add stricter preflight checks and staged rollback planning before execution.",
            )
        if tests_ran and tests_passed is False:
            _add_signal(
                "edge_case_validation",
                "Edge-Case Validation Gap",
                "Tests failed after code changes, indicating missing edge cases or assertions.",
                "Generate an edge-case checklist and prioritize tests-first updates before implementation edits.",
            )
        if max(iterations_used, iterations_until_green) >= 3:
            _add_signal(
                "iteration_efficiency",
                "Iteration Efficiency",
                f"Iterations until stable green were high ({max(iterations_used, iterations_until_green)}).",
                "Break goals into smaller checkpoints and enforce narrower edit scopes per iteration.",
            )
        if run_duration_sec >= 45.0:
            _add_signal(
                "execution_latency",
                "Execution Latency",
                f"Longest recent run consumed about {run_duration_sec:.1f}s of command execution.",
                "Prefer incremental tests and cache-friendly command sequencing before full-suite runs.",
            )

        reflection_text = str(reflection.get("lesson", "")).strip().lower() if isinstance(reflection, dict) else ""
        if "step-by-step" in reflection_text or "step by step" in reflection_text:
            _add_signal(
                "explanation_structure",
                "Explanation Structure",
                "Recent conversation reflection indicates preference for step-by-step guidance.",
                "Encode explicit step-order reasoning checkpoints in planning summaries.",
            )
        if "concise" in reflection_text or "brief" in reflection_text:
            _add_signal(
                "response_compaction",
                "Response Compaction",
                "Recent reflection indicates concise communication is preferred in context.",
                "Add tighter summary compression before returning final responses.",
            )
        if "detailed" in reflection_text or "more detail" in reflection_text:
            _add_signal(
                "response_depth",
                "Response Depth Calibration",
                "Recent reflection indicates detailed explanation preference.",
                "Attach optional deeper rationale blocks while preserving deterministic citations.",
            )
        if "tests failed" in reflection_text or "edge case" in reflection_text:
            _add_signal(
                "reflection_test_gap",
                "Reflection-Test Gap",
                "Reflection explicitly mentioned failed tests or edge-case coverage gaps.",
                "Insert a reusable pre-merge edge-case test matrix before implementation finalization.",
            )

        if trigger == "manual" and not signals:
            _add_signal(
                "manual_review",
                "Manual Self-Review",
                "Manual autonomous cycle requested with no strong regression signal.",
                "Persist current strengths and identify one constrained optimization target for next runs.",
            )

        ordered = list(signals.values())
        ordered.sort(key=lambda row: str(row.get("code", "")))
        return ordered

    @staticmethod
    def _summarize_autonomous_signals(signals: list[dict[str, str]], max_items: int = 2) -> str:
        clean = [str(item.get("title", "")).strip() for item in signals if isinstance(item, dict)]
        clean = [item for item in clean if item]
        if not clean:
            return "No specific weaknesses were detected in the latest autonomous review."
        selected = clean[: max(1, min(max_items, 6))]
        if len(clean) > len(selected):
            return f"{'; '.join(selected)}; plus {len(clean) - len(selected)} additional signal(s)."
        return "; ".join(selected) + "."

    def _self_improvement_signature_exists(self, signature: str) -> bool:
        clean = str(signature).strip()
        if not clean:
            return False
        with self._lock:
            rows = self._self_improvement_rows()
        for row in rows:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            if str(metadata.get("signature", "")).strip() == clean:
                return True
        return False

    def _pending_autonomous_self_improvement_count(self) -> int:
        with self._lock:
            rows = self._self_improvement_rows()
        count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("status", "")).strip().lower() != "pending":
                continue
            metadata = row.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            if bool(metadata.get("autonomous", False)) or str(row.get("actor", "")).strip().lower().startswith(
                "david_autonomous"
            ):
                count += 1
        return count

    def _build_autonomous_self_improvement_files(self, analysis: dict[str, Any]) -> list[dict[str, str]]:
        if not isinstance(analysis, dict):
            return []
        signals = analysis.get("signals", [])
        if not isinstance(signals, list) or not signals:
            return []

        signal_rows: list[dict[str, str]] = []
        for row in signals:
            if not isinstance(row, dict):
                continue
            signal_rows.append(
                {
                    "code": str(row.get("code", "")).strip(),
                    "title": str(row.get("title", "")).strip(),
                    "evidence": str(row.get("evidence", "")).strip(),
                    "upgrade": str(row.get("upgrade", "")).strip(),
                }
            )
        signal_rows = [row for row in signal_rows if row["code"] and row["upgrade"]]
        if not signal_rows:
            return []

        recommended_actions: list[str] = []
        for row in signal_rows:
            action = row["upgrade"]
            if action not in recommended_actions:
                recommended_actions.append(action)

        trigger_value = str(analysis.get("trigger", "manual")).strip()
        trigger_id = str(analysis.get("trigger_id", "")).strip()
        generated_at = str(analysis.get("timestamp_utc", self._now_iso())).strip() or self._now_iso()

        playbook_lines = [
            '"""Autonomous self-improvement playbook generated by David.',
            "",
            "This file is a proposed upgrade derived from run telemetry and reflection memory.",
            "Core safety modules remain immutable and out of scope for autonomous edits.",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            f'GENERATED_AT_UTC = {json.dumps(generated_at, ensure_ascii=True)}',
            f'TRIGGER = {json.dumps(trigger_value, ensure_ascii=True)}',
            f'TRIGGER_ID = {json.dumps(trigger_id, ensure_ascii=True)}',
            f"SIGNAL_CODES = {json.dumps([row['code'] for row in signal_rows], ensure_ascii=True)}",
            "",
            f"SIGNALS = {json.dumps(signal_rows, indent=2, ensure_ascii=True)}",
            "",
            "RECOMMENDED_ACTIONS = [",
        ]
        for action in recommended_actions:
            playbook_lines.append(f"    {json.dumps(action, ensure_ascii=True)},")
        playbook_lines.extend(
            [
                "]",
                "",
                "def recommended_actions() -> list[str]:",
                "    return list(RECOMMENDED_ACTIONS)",
                "",
                "def latest_signals() -> list[dict[str, str]]:",
                "    return [dict(item) for item in SIGNALS]",
                "",
            ]
        )
        playbook_content = "\n".join(playbook_lines)

        state_payload = {
            "generated_at_utc": generated_at,
            "trigger": trigger_value,
            "trigger_id": trigger_id,
            "run_id": str(analysis.get("run_id", "")).strip(),
            "run_status": str(analysis.get("run_status", "")).strip(),
            "reflection_key": str(analysis.get("reflection_key", "")).strip(),
            "analysis_summary": str(analysis.get("analysis_summary", "")).strip(),
            "signals": signal_rows,
            "recommended_actions": recommended_actions,
            "safety_boundary": str(analysis.get("safety_boundary", "")).strip(),
        }
        state_content = json.dumps(state_payload, indent=2, ensure_ascii=True) + "\n"

        history_rel = "docs/self_improvement_change_history.md"
        history_abs = self.project_root / history_rel
        history_existing = ""
        if history_abs.exists() and history_abs.is_file():
            try:
                history_existing = history_abs.read_text(encoding="utf-8")
            except OSError:
                history_existing = ""
        if not history_existing.strip():
            history_existing = (
                "# Self-Improvement Change History\n\n"
                "This log tracks autonomous and manual self-improvement proposals with transparent reasoning.\n"
            )

        history_lines = [
            f"## {generated_at}",
            "",
            f"- Trigger: `{trigger_value}`{f' (`{trigger_id}`)' if trigger_id else ''}",
            f"- Run: `{state_payload['run_id'] or '-'}` / status: `{state_payload['run_status'] or '-'}`",
            f"- Reflection: `{state_payload['reflection_key'] or '-'}`",
            f"- Summary: {state_payload['analysis_summary'] or 'n/a'}",
            "- Signals:",
        ]
        for row in signal_rows:
            history_lines.append(f"  - `{row['code']}`: {row['title']} | {row['evidence']}")
        history_lines.extend(
            [
                "- Proposed actions:",
            ]
        )
        for action in recommended_actions:
            history_lines.append(f"  - {action}")
        history_lines.extend(["", "---", ""])
        history_content = history_existing.rstrip() + "\n\n" + "\n".join(history_lines)

        return [
            {"path": "agent/self_improvement/autonomous_playbook.py", "content": playbook_content},
            {"path": "agent/self_improvement/autonomous_state.json", "content": state_content},
            {"path": history_rel, "content": history_content},
        ]

    def list_legacy_archive(self, limit: int = 200) -> dict[str, Any]:
        try:
            limit_value = int(limit or 200)
        except (TypeError, ValueError):
            limit_value = 200
        max_limit = max(1, min(limit_value, 600))
        payload = self._read_memory_payload()
        rows = payload.get("legacy_archive", []) if isinstance(payload.get("legacy_archive"), list) else []
        cleaned = [row for row in rows if isinstance(row, dict)]
        cleaned.sort(key=lambda item: str(item.get("recorded_at", item.get("timestamp_utc", ""))), reverse=True)
        return {
            "items": cleaned[:max_limit],
            "total": len(cleaned),
            "boundary_note": LEGACY_ARCHIVE_BOUNDARY_NOTE,
        }

    def mark_legacy_moment(
        self,
        payload: dict[str, Any],
        *,
        actor: str = "web_ui",
    ) -> tuple[bool, dict[str, Any]]:
        if not isinstance(payload, dict):
            return False, {"error": "Payload must be an object."}
        source_type = str(payload.get("source_type", "manual")).strip().lower() or "manual"
        if source_type not in {"conversation", "milestone", "teaching", "lesson", "value", "manual"}:
            return False, {"error": "source_type must be one of conversation|milestone|teaching|lesson|value|manual."}
        source_id = str(payload.get("source_id", "")).strip()
        try:
            summary = self._sanitize_user_text(payload.get("summary", ""), field_name="summary", max_chars=320)
        except ValueError as exc:
            return False, {"error": str(exc)}
        details = str(payload.get("details", "")).replace("\x00", "").strip()
        if len(details) > 2_000:
            return False, {"error": "details exceeds max length (2000 chars)."}
        source_timestamp = self._normalize_iso_timestamp(payload.get("timestamp_utc", ""))
        metadata = payload.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            return False, {"error": "metadata must be an object."}

        now = self._now_iso()
        entry = {
            "id": f"legacy_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "kind": "significant_moment",
            "source_type": source_type,
            "source_id": source_id,
            "summary": summary,
            "details": details,
            "timestamp_utc": source_timestamp,
            "recorded_at": now,
            "actor": actor.strip() or "web_ui",
            "metadata": metadata,
            "boundary_note": LEGACY_ARCHIVE_BOUNDARY_NOTE,
        }

        memory_payload = self._read_memory_payload()
        rows = memory_payload.get("legacy_archive", []) if isinstance(memory_payload.get("legacy_archive"), list) else []
        rows = [row for row in rows if isinstance(row, dict)]
        rows.append(entry)
        memory_payload["legacy_archive"] = rows[-1200:]
        self._write_memory_payload(memory_payload)

        event_payload = {"entry": entry, "total": len(memory_payload["legacy_archive"])}
        self.publish_event("status", {"type": "memory_legacy_archive_saved", "payload": event_payload})
        self.publish_event("logs", {"type": "memory_legacy_archive_saved", "payload": event_payload})
        return True, entry

    def remove_legacy_moment(
        self,
        entry_id: str,
        *,
        actor: str = "web_ui",
    ) -> tuple[bool, dict[str, Any]]:
        clean_id = str(entry_id).strip()
        if not clean_id:
            return False, {"error": "entry_id is required."}
        memory_payload = self._read_memory_payload()
        rows = memory_payload.get("legacy_archive", []) if isinstance(memory_payload.get("legacy_archive"), list) else []
        cleaned = [row for row in rows if isinstance(row, dict)]
        kept = [row for row in cleaned if str(row.get("id", "")).strip() != clean_id]
        if len(kept) == len(cleaned):
            return False, {"error": "Archive entry not found."}
        memory_payload["legacy_archive"] = kept
        self._write_memory_payload(memory_payload)
        response = {
            "removed_id": clean_id,
            "removed": True,
            "total": len(kept),
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
        }
        self.publish_event("status", {"type": "memory_legacy_archive_removed", "payload": response})
        self.publish_event("logs", {"type": "memory_legacy_archive_removed", "payload": response})
        return True, response

    def get_runs(self, search: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if self._demo_mode_enabled():
            run_dirs = self._demo_run_dirs()
        else:
            run_dirs = [item for item in self.runs_root.iterdir()]
        for run_dir in run_dirs:
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

        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
        meta = self._read_json(run_dir / "meta.json", default=None)
        if not isinstance(meta, dict):
            return None

        plan = self._read_json(run_dir / "plan.json", default={})
        result = self._read_json(run_dir / "result.json", default={})
        timeline = self._read_jsonl(run_dir / "timeline.jsonl", limit=1_000)
        if not timeline:
            timeline_json = self._read_json(run_dir / "timeline.json", default=[])
            if isinstance(timeline_json, list):
                timeline = [row for row in timeline_json if isinstance(row, dict)][-1000:]

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

        approvals = [a for a in self.list_approvals() if a.get("run_id") == run_id]
        health_summary = self._build_run_health_summary(
            meta=meta,
            result=result if isinstance(result, dict) else {},
            timeline=timeline,
            audit=self.get_run_audit(run_id, limit=200) or [],
            approvals=approvals,
        )

        return {
            "meta": meta,
            "plan": plan,
            "result": result,
            "timeline": timeline,
            "iterations": iteration_rows,
            "approvals": approvals,
            "artifacts_dir": str(run_dir),
            "workspace_dir": str(self.config.workspace_dir),
            "file_summary": self.get_run_files(run_id),
            "health_summary": health_summary,
        }

    def get_run_timeline(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
        if not run_dir.exists():
            return None
        rows = self._read_jsonl(run_dir / "timeline.jsonl", limit=max(1, min(limit, 2000)))
        if rows:
            return rows
        timeline_json = self._read_json(run_dir / "timeline.json", default=[])
        if isinstance(timeline_json, list):
            clean = [row for row in timeline_json if isinstance(row, dict)]
            return clean[-max(1, min(limit, 2000)) :]
        return []

    def get_run_audit(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        if not self._is_safe_run_id(run_id):
            return None
        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
        if not run_dir.exists():
            return None
        rows = self._read_jsonl(run_dir / "audit.jsonl", limit=max(1, min(limit, 2000)))
        if self._demo_mode_enabled():
            self._ensure_demo_runtime()
            with self._lock:
                appends = self._demo_runtime.get("approval_audit_appends", {}).get(run_id, [])
            if isinstance(appends, list):
                rows.extend([row for row in appends if isinstance(row, dict)])
        rows.sort(key=lambda row: str(row.get("timestamp_utc", "")))
        return rows[-max(1, min(limit, 2000)) :]

    def get_run_files(self, run_id: str) -> dict[str, Any] | None:
        if not self._is_safe_run_id(run_id):
            return None

        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
        if not run_dir.exists():
            return None
        if self._demo_mode_enabled():
            summary = self._read_json(run_dir / "file_summary.json", default=None)
            if isinstance(summary, dict):
                return summary
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
        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
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
        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
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

    def _build_run_health_summary(
        self,
        *,
        meta: dict[str, Any],
        result: dict[str, Any],
        timeline: list[dict[str, Any]],
        audit: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        iterations = int(meta.get("iteration", 0) or 0)
        iterations_until_green_raw = meta.get("iterations_until_green", result.get("iterations_until_green"))
        iterations_until_green = None
        if iterations_until_green_raw is not None:
            try:
                iterations_until_green = int(iterations_until_green_raw)
            except (TypeError, ValueError):
                iterations_until_green = None

        started = self._parse_timestamp(meta.get("started_at", ""))
        ended = self._parse_timestamp(meta.get("ended_at", ""))
        elapsed_sec = None
        if started is not None and ended is not None:
            elapsed_sec = max(0.0, round((ended - started).total_seconds(), 3))

        approval_count = len([row for row in approvals if isinstance(row, dict)])
        if approval_count == 0 and isinstance(audit, list):
            approval_count = sum(
                1
                for row in audit
                if isinstance(row, dict)
                and str(row.get("action", "")).strip().casefold().startswith("approval_")
            )

        memory_references = 0
        used_memory = result.get("used_memory", {})
        if isinstance(used_memory, dict):
            for value in used_memory.values():
                if isinstance(value, list):
                    memory_references += len(value)
        citations = result.get("citations", [])
        if isinstance(citations, list):
            memory_references = max(memory_references, len(citations))
        if memory_references == 0 and isinstance(timeline, list):
            for row in timeline:
                if not isinstance(row, dict):
                    continue
                payload = row.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                used = payload.get("used_memory", {})
                if isinstance(used, dict):
                    count = 0
                    for value in used.values():
                        if isinstance(value, list):
                            count += len(value)
                    memory_references = max(memory_references, count)

        failure_text = "\n".join(
            [
                str(meta.get("failure_explanation", "")),
                str(meta.get("message", "")),
                str(result.get("failure", "")),
                str((result.get("failure_details", {}) or {}).get("summary", "")),
                str((result.get("failure_details", {}) or {}).get("category", "")),
            ]
        ).strip()
        top_error_category = "none"
        if failure_text:
            top_error_category = self._categorize_failure(failure_text)
        status = str(meta.get("status", "")).strip().casefold()
        if top_error_category == "none" and status in {"failed", "rejected"}:
            top_error_category = "runtime"

        return {
            "iterations": iterations,
            "iterations_until_green": iterations_until_green,
            "elapsed_sec": elapsed_sec,
            "approvals_count": approval_count,
            "planner_model_used": str(meta.get("planner_model_used", "")).strip(),
            "coder_model_used": str(meta.get("coder_model_used", "")).strip(),
            "critic_model_used": str(meta.get("critic_model_used", "")).strip(),
            "top_error_category": top_error_category,
            "memory_items_referenced": memory_references,
        }

    def retry_run(self, run_id: str) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return False, {
                "error": "Demo mode is active. Retry is disabled to keep fixture runs deterministic.",
            }
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
        run_root = self._demo_runs_root() if self._demo_mode_enabled() else None
        run_dir = self._run_dir(run_id, runs_root=run_root)
        if not run_dir.exists() or not run_dir.is_dir():
            return None

        run_payload = self.get_run(run_id)
        if not isinstance(run_payload, dict):
            return None
        manifest = {
            "bundle_type": "david_run_bundle",
            "bundle_schema": 1,
            "exported_at": self._now_iso(),
            "run_id": run_id,
            "app_version": self.app_version,
            "git_commit": self.git_commit,
            "version_stamp": self.version_stamp,
            "demo_mode": self._demo_mode_enabled(),
            "read_only_import_supported": True,
            "health_summary": run_payload.get("health_summary", {}),
        }
        redacted_memory = self._redacted_memory_snapshot()

        buff = io.BytesIO()
        with zipfile.ZipFile(buff, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in run_dir.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(run_dir).as_posix()
                    archive.write(path, arcname=f"{run_id}/{rel}")
            archive.writestr(
                f"{run_id}/bundle_manifest.json",
                json.dumps(manifest, indent=2) + "\n",
            )
            archive.writestr(
                f"{run_id}/memory_snapshot_redacted.json",
                json.dumps(redacted_memory, indent=2) + "\n",
            )
        buff.seek(0)
        return buff

    def import_run_bundle(
        self,
        *,
        file_name: str,
        content: bytes,
        actor: str = "web_ui",
    ) -> tuple[bool, dict[str, Any]]:
        if not isinstance(content, (bytes, bytearray)) or not content:
            return False, {"error": "Bundle file is empty."}
        if len(content) > 8 * 1024 * 1024:
            return False, {"error": "Bundle exceeds maximum size (8MB)."}

        try:
            archive = zipfile.ZipFile(io.BytesIO(content), mode="r")
        except zipfile.BadZipFile:
            return False, {"error": "Invalid ZIP bundle."}

        with archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if not infos:
                return False, {"error": "Bundle has no files."}
            if len(infos) > 3000:
                return False, {"error": "Bundle has too many files."}

            total_uncompressed = 0
            for info in infos:
                normalized = str(info.filename).replace("\\", "/")
                if normalized.startswith("/") or normalized.startswith("../"):
                    return False, {"error": "Bundle contains unsafe paths."}
                if ".." in Path(normalized).parts:
                    return False, {"error": "Bundle contains unsafe path traversal."}
                if info.file_size > 4 * 1024 * 1024:
                    return False, {"error": "Bundle contains oversized file entries."}
                total_uncompressed += max(0, int(info.file_size))
            if total_uncompressed > 24 * 1024 * 1024:
                return False, {"error": "Bundle uncompressed payload is too large."}

            file_names = [str(item.filename).replace("\\", "/") for item in infos]
            root_candidates = []
            for name in file_names:
                if name.endswith("/meta.json"):
                    root_candidates.append(name.rsplit("/meta.json", 1)[0])
            if not root_candidates:
                return False, {"error": "Bundle missing run metadata (meta.json)."}
            run_root = sorted(root_candidates, key=len)[0].strip("/")
            if not run_root:
                return False, {"error": "Bundle root is invalid."}

            def _read_text(rel_path: str) -> str:
                path = f"{run_root}/{rel_path}".replace("//", "/")
                try:
                    return archive.read(path).decode("utf-8", errors="replace")
                except KeyError:
                    return ""

            def _read_json(rel_path: str, default: Any) -> Any:
                text = _read_text(rel_path)
                if not text.strip():
                    return default
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return default

            def _read_jsonl(rel_path: str, *, limit: int = 2000) -> list[dict[str, Any]]:
                text = _read_text(rel_path)
                if not text.strip():
                    return []
                rows: list[dict[str, Any]] = []
                for line in text.splitlines()[-max(1, min(limit, 20_000)) :]:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
                return rows

            meta = _read_json("meta.json", default={})
            if not isinstance(meta, dict) or not meta:
                return False, {"error": "Bundle meta.json is invalid."}
            run_id = str(meta.get("id", "")).strip() or run_root
            plan = _read_json("plan.json", default={})
            if not isinstance(plan, dict):
                plan = {}
            result = _read_json("result.json", default={})
            if not isinstance(result, dict):
                result = {}
            timeline = _read_jsonl("timeline.jsonl", limit=3000)
            if not timeline:
                timeline_json = _read_json("timeline.json", default=[])
                if isinstance(timeline_json, list):
                    timeline = [row for row in timeline_json if isinstance(row, dict)]
            audit = _read_jsonl("audit.jsonl", limit=3000)
            file_summary = _read_json("file_summary.json", default={})
            if not isinstance(file_summary, dict):
                file_summary = {}
            bundle_manifest = _read_json("bundle_manifest.json", default={})
            if not isinstance(bundle_manifest, dict):
                bundle_manifest = {}
            memory_snapshot_redacted = _read_json("memory_snapshot_redacted.json", default={})
            if not isinstance(memory_snapshot_redacted, dict):
                memory_snapshot_redacted = {}

            iteration_map: dict[int, str] = {}
            iteration_prefix = f"{run_root}/iterations/"
            for name in file_names:
                if not name.startswith(iteration_prefix):
                    continue
                remainder = name[len(iteration_prefix) :]
                parts = [part for part in remainder.split("/") if part]
                if len(parts) < 2:
                    continue
                iter_name = parts[0]
                try:
                    iter_idx = int(iter_name)
                except ValueError:
                    continue
                iteration_map[iter_idx] = iter_name

            iterations: list[dict[str, Any]] = []
            for iter_idx in sorted(iteration_map.keys()):
                iter_name = iteration_map[iter_idx]
                iter_base = f"iterations/{iter_name}"
                iteration_row = {
                    "iteration": f"{iter_idx:03d}",
                    "coder": _read_json(f"{iter_base}/coder.json", default={}),
                    "execution": _read_json(f"{iter_base}/execution.json", default=[]),
                    "critic": _read_json(f"{iter_base}/critic.json", default={}),
                    "diffs": _read_json(f"{iter_base}/diffs.json", default=[]),
                    "risk": _read_json(f"{iter_base}/risk.json", default={}),
                }
                if not isinstance(iteration_row["coder"], dict):
                    iteration_row["coder"] = {}
                if not isinstance(iteration_row["execution"], list):
                    iteration_row["execution"] = []
                if not isinstance(iteration_row["critic"], dict):
                    iteration_row["critic"] = {}
                if not isinstance(iteration_row["diffs"], list):
                    iteration_row["diffs"] = []
                if not isinstance(iteration_row["risk"], dict):
                    iteration_row["risk"] = {}
                iterations.append(iteration_row)

            health_summary = self._build_run_health_summary(
                meta=meta,
                result=result,
                timeline=timeline,
                audit=audit,
                approvals=[],
            )
            imported_at = self._now_iso()
            import_id = f"imp_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
            view = {
                "import_id": import_id,
                "run_id": run_id,
                "source_filename": str(file_name).strip() or "bundle.zip",
                "imported_at": imported_at,
                "read_only": True,
                "meta": meta,
                "plan": plan,
                "result": result,
                "timeline": timeline,
                "iterations": iterations,
                "audit": audit,
                "file_summary": file_summary,
                "bundle_manifest": bundle_manifest,
                "memory_snapshot_redacted": memory_snapshot_redacted,
                "health_summary": health_summary,
                "actor": actor.strip() or "web_ui",
                "version_stamp": self.version_stamp,
            }

        with self._lock:
            self._imported_bundle_views[import_id] = view
            self._imported_bundle_order.insert(0, import_id)
            while len(self._imported_bundle_order) > self._max_imported_bundles:
                stale = self._imported_bundle_order.pop()
                self._imported_bundle_views.pop(stale, None)

        event_payload = {
            "import_id": import_id,
            "run_id": run_id,
            "source_filename": view["source_filename"],
            "imported_at": imported_at,
            "read_only": True,
        }
        self.publish_event("status", {"type": "bundle_imported", "payload": event_payload})
        self.publish_event("logs", {"type": "bundle_imported", "payload": event_payload})
        return True, event_payload

    def list_imported_bundles(self, limit: int = 120) -> list[dict[str, Any]]:
        max_limit = max(1, min(int(limit or 120), 500))
        with self._lock:
            order = list(self._imported_bundle_order)
            views = dict(self._imported_bundle_views)
        rows: list[dict[str, Any]] = []
        for import_id in order:
            view = views.get(import_id)
            if not isinstance(view, dict):
                continue
            rows.append(
                {
                    "import_id": import_id,
                    "run_id": str(view.get("run_id", "")).strip(),
                    "source_filename": str(view.get("source_filename", "")).strip(),
                    "imported_at": str(view.get("imported_at", "")).strip(),
                    "read_only": True,
                    "status": str((view.get("meta", {}) or {}).get("status", "")).strip(),
                    "health_summary": view.get("health_summary", {}),
                }
            )
            if len(rows) >= max_limit:
                break
        return rows

    def get_imported_bundle(self, import_id: str) -> dict[str, Any] | None:
        if not self._is_safe_import_id(import_id):
            return None
        with self._lock:
            view = self._imported_bundle_views.get(import_id)
            if not isinstance(view, dict):
                return None
            payload = self._clone_json(view)
        payload["artifacts_dir"] = f"imported_bundle:{import_id}"
        payload["workspace_dir"] = "imported_bundle_read_only"
        return payload

    def get_imported_bundle_timeline(self, import_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        view = self.get_imported_bundle(import_id)
        if not view:
            return None
        rows = view.get("timeline", [])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)][-max(1, min(limit, 2000)) :]

    def get_imported_bundle_audit(self, import_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        view = self.get_imported_bundle(import_id)
        if not view:
            return None
        rows = view.get("audit", [])
        if not isinstance(rows, list):
            return []
        clean = [row for row in rows if isinstance(row, dict)]
        clean.sort(key=lambda row: str(row.get("timestamp_utc", "")))
        return clean[-max(1, min(limit, 2000)) :]

    def get_imported_bundle_files(self, import_id: str) -> dict[str, Any] | None:
        view = self.get_imported_bundle(import_id)
        if not view:
            return None
        summary = view.get("file_summary", {})
        if not isinstance(summary, dict):
            summary = {}
        payload = self._clone_json(summary)
        payload["workspace_dir"] = "imported_bundle_read_only"
        payload["artifacts_dir"] = f"imported_bundle:{import_id}"
        payload["read_only"] = True
        return payload

    @staticmethod
    def _coerce_iteration_number(value: Any) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    def _compare_iteration_rows(self, rows: list[dict[str, Any]], iteration: int) -> dict[str, Any] | None:
        if not rows:
            return None
        by_num: dict[int, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = self._coerce_iteration_number(row.get("iteration", 0))
            if key <= 0:
                continue
            by_num[key] = row
        curr = by_num.get(iteration)
        if not isinstance(curr, dict):
            return None
        prev = by_num.get(iteration - 1)
        curr_exec = curr.get("execution", []) if isinstance(curr.get("execution"), list) else []
        prev_exec = prev.get("execution", []) if isinstance(prev, dict) and isinstance(prev.get("execution"), list) else []
        curr_diffs = curr.get("diffs", []) if isinstance(curr.get("diffs"), list) else []
        prev_diffs = prev.get("diffs", []) if isinstance(prev, dict) and isinstance(prev.get("diffs"), list) else []

        def _passed(exec_rows: list[dict[str, Any]]) -> bool:
            if not exec_rows:
                return False
            return all(
                int(item.get("returncode", 1)) == 0 and not bool(item.get("timed_out"))
                for item in exec_rows
                if isinstance(item, dict)
            )

        changed_now = sorted(
            {
                str(item.get("path", "")).strip()
                for item in curr_diffs
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            }
        )
        changed_prev = sorted(
            {
                str(item.get("path", "")).strip()
                for item in prev_diffs
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            }
        )
        new_changes = [path for path in changed_now if path not in changed_prev]
        likely_cause = None
        if _passed(prev_exec) and not _passed(curr_exec):
            likely_cause = {
                "reason": "First failing iteration after a passing iteration.",
                "files": new_changes or changed_now,
            }
        return {
            "iteration": iteration,
            "previous_iteration": iteration - 1 if isinstance(prev, dict) else None,
            "changed_files_current": changed_now,
            "changed_files_previous": changed_prev,
            "newly_changed_files": new_changes,
            "passed_previous": _passed(prev_exec),
            "passed_current": _passed(curr_exec),
            "likely_failure_cause": likely_cause,
        }

    def get_imported_bundle_replay(self, import_id: str, iteration: int) -> dict[str, Any] | None:
        view = self.get_imported_bundle(import_id)
        if not view:
            return None
        rows = view.get("iterations", [])
        if not isinstance(rows, list):
            return None
        clean = [row for row in rows if isinstance(row, dict)]
        if not clean:
            return None
        clean.sort(key=lambda row: self._coerce_iteration_number(row.get("iteration", 0)))
        idx = max(0, min(iteration - 1, len(clean) - 1))
        current = clean[idx]
        chosen = self._coerce_iteration_number(current.get("iteration", idx + 1))
        compare = self._compare_iteration_rows(clean, chosen)
        prev_iter = self._coerce_iteration_number(clean[idx - 1].get("iteration", 0)) if idx > 0 else None
        next_iter = self._coerce_iteration_number(clean[idx + 1].get("iteration", 0)) if idx < len(clean) - 1 else None
        return {
            "import_id": import_id,
            "run_id": str(view.get("run_id", "")).strip(),
            "iteration": chosen,
            "total_iterations": len(clean),
            "has_prev": idx > 0,
            "has_next": idx < len(clean) - 1,
            "prev_iteration": prev_iter if prev_iter and prev_iter > 0 else None,
            "next_iteration": next_iter if next_iter and next_iter > 0 else None,
            "current": current,
            "comparison": compare,
            "read_only": True,
        }

    def get_imported_bundle_compare(self, import_id: str, iteration: int) -> dict[str, Any] | None:
        view = self.get_imported_bundle(import_id)
        if not view:
            return None
        rows = view.get("iterations", [])
        if not isinstance(rows, list):
            return None
        clean = [row for row in rows if isinstance(row, dict)]
        if not clean:
            return None
        clean.sort(key=lambda row: self._coerce_iteration_number(row.get("iteration", 0)))
        return self._compare_iteration_rows(clean, max(1, int(iteration or 1)))

    def upload_and_analyze_file(
        self,
        *,
        file_name: str,
        content: bytes,
        content_type: str = "",
        actor: str = "web_ui",
        use_vision: bool | None = None,
        vision_model: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        if self._demo_mode_enabled():
            return False, {
                "error": "Demo mode is active. File uploads are disabled to keep deterministic fixture behavior.",
            }
        clean_name = sanitize_upload_filename(file_name)
        extension = Path(clean_name).suffix.lower()
        if extension and extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            return False, {
                "error": "Unsupported file extension. Allowed: csv, xlsx, xls, pdf, png, jpg, jpeg, gif, bmp, webp.",
            }
        raw = bytes(content or b"")
        if not raw:
            return False, {"error": "Upload file is empty."}
        if len(raw) > MAX_UPLOAD_FILE_BYTES:
            max_mb = round(MAX_UPLOAD_FILE_BYTES / (1024 * 1024), 1)
            return False, {"error": f"Upload file exceeds size limit ({max_mb} MB)."}
        try:
            analysis = analyze_uploaded_content(clean_name, content_type, raw)
        except ValueError as exc:
            return False, {"error": str(exc)}
        apply_vision = bool(self.settings.upload_vision_mode) if use_vision is None else bool(use_vision)
        if apply_vision:
            model_hint = str(vision_model or "").strip() or str(self.settings.upload_vision_model or "").strip() or self.config.model
            try:
                chosen_vision_model = sanitize_model_name(model_hint, "upload_vision_model")
            except ValueError as exc:
                return False, {"error": str(exc)}
            analysis = self._enrich_uploaded_analysis_with_vision(
                analysis=analysis,
                content=raw,
                model=chosen_vision_model,
            )

        upload_id = self._new_upload_id()
        suffix = Path(clean_name).suffix.lower() or ".bin"
        stored_name = f"{upload_id}{suffix}"
        stored_path = (self.uploads_files_root / stored_name).resolve()
        try:
            if stored_path == self.uploads_files_root or self.uploads_files_root not in stored_path.parents:
                return False, {"error": "Upload storage path escaped upload boundary."}
            stored_path.write_bytes(raw)
        except OSError as exc:
            return False, {"error": f"Failed to persist upload bytes: {exc}"}

        uploaded_at = self._now_iso()
        actor_name = str(actor or "web_ui").strip() or "web_ui"
        record: dict[str, Any] = {
            "upload_id": upload_id,
            "file_name": clean_name,
            "content_type": str(content_type or "").strip(),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "uploaded_at": uploaded_at,
            "actor": actor_name,
            "stored_name": stored_name,
            "analysis": analysis,
        }

        with self._lock:
            rows = self._upload_rows()
            rows.insert(0, record)
            while len(rows) > self._max_uploaded_files:
                stale = rows.pop()
                if isinstance(stale, dict):
                    self._delete_uploaded_file_blob(stale)
            self._save_upload_rows(rows)

        payload = {
            "upload_id": upload_id,
            "file_name": clean_name,
            "content_type": str(content_type or "").strip(),
            "size_bytes": len(raw),
            "uploaded_at": uploaded_at,
            "actor": actor_name,
            "analysis": analysis,
        }
        self.publish_event("status", {"type": "upload_analyzed", "payload": payload})
        self.publish_event("logs", {"type": "upload_analyzed", "payload": payload})
        return True, payload

    def _enrich_uploaded_analysis_with_vision(
        self,
        *,
        analysis: dict[str, Any],
        content: bytes,
        model: str,
    ) -> dict[str, Any]:
        enriched = self._clone_json(analysis) if isinstance(analysis, dict) else {}
        fmt = str(enriched.get("format", "")).strip().lower()
        if fmt not in {"png", "jpg", "jpeg", "gif", "bmp", "webp", "pdf"}:
            enriched["vision"] = {
                "requested": True,
                "status": "skipped",
                "reason": f"format '{fmt or 'unknown'}' not supported for vision enrichment.",
                "model": model,
            }
            return enriched

        if fmt in {"png", "jpg", "jpeg", "gif", "bmp", "webp"}:
            return self._enrich_uploaded_image_analysis(enriched, content=content, model=model)
        return self._enrich_uploaded_pdf_analysis(enriched, model=model)

    def _enrich_uploaded_image_analysis(
        self,
        analysis: dict[str, Any],
        *,
        content: bytes,
        model: str,
    ) -> dict[str, Any]:
        system_prompt = (
            "You analyze uploaded images. Respond with one concise paragraph that describes what the image likely "
            "shows, any readable text, and key entities. If uncertain, state uncertainty clearly."
        )
        user_prompt = (
            "Describe this image for a file-analysis panel. Keep it factual, no markdown, max 450 characters."
        )
        try:
            brief = self._chat_ollama_for_upload_enrichment(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                image_bytes=content,
            )
        except Exception as exc:
            return self._mark_upload_vision_failure(analysis, model=model, reason=str(exc))
        if not brief:
            return self._mark_upload_vision_failure(
                analysis,
                model=model,
                reason="Vision model returned an empty summary.",
            )
        return self._apply_upload_vision_brief(
            analysis,
            brief=brief,
            model=model,
            source="image_vision",
        )

    def _enrich_uploaded_pdf_analysis(
        self,
        analysis: dict[str, Any],
        *,
        model: str,
    ) -> dict[str, Any]:
        excerpt = str(analysis.get("text_excerpt", "")).strip()
        if not excerpt:
            return self._mark_upload_vision_failure(
                analysis,
                model=model,
                reason="No extractable PDF text available for model summarization.",
            )
        stats = analysis.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        pages = int(stats.get("pages", 0) or 0)
        keywords = stats.get("keywords", [])
        keyword_line = ", ".join(str(item).strip() for item in keywords[:8] if str(item).strip())
        system_prompt = (
            "You summarize uploaded PDF content for a control center. Respond with one concise paragraph "
            "covering topic, likely purpose, and notable entities."
        )
        user_prompt = (
            f"Pages: {pages}\n"
            f"Keywords: {keyword_line or '-'}\n\n"
            "Excerpt:\n"
            f"{excerpt[:3200]}\n\n"
            "Write a factual summary in under 450 characters."
        )
        try:
            brief = self._chat_ollama_for_upload_enrichment(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                image_bytes=None,
            )
        except Exception as exc:
            return self._mark_upload_vision_failure(analysis, model=model, reason=str(exc))
        if not brief:
            return self._mark_upload_vision_failure(
                analysis,
                model=model,
                reason="PDF summarization model returned an empty summary.",
            )
        return self._apply_upload_vision_brief(
            analysis,
            brief=brief,
            model=model,
            source="pdf_text_summary",
        )

    def _chat_ollama_for_upload_enrichment(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        image_bytes: bytes | None,
    ) -> str:
        user_message: dict[str, Any] = {"role": "user", "content": user_prompt}
        if image_bytes:
            user_message["images"] = [base64.b64encode(image_bytes).decode("ascii")]
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                user_message,
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        response = requests.post(
            self.config.ollama_url,
            json=payload,
            timeout=(10, 120),
        )
        if response.status_code != 200:
            snippet = str(response.text or "").strip()[:220]
            raise RuntimeError(f"Ollama returned status {response.status_code}: {snippet}")
        data = response.json()
        message = data.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama upload enrichment response missing message object.")
        content = str(message.get("content", "")).strip()
        collapsed = " ".join(content.split())
        if len(collapsed) > 450:
            collapsed = collapsed[:450].rstrip()
        return collapsed

    def _mark_upload_vision_failure(self, analysis: dict[str, Any], *, model: str, reason: str) -> dict[str, Any]:
        warnings = analysis.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(f"OCR/Vision enrichment skipped: {str(reason or 'unavailable').strip()}")
        analysis["warnings"] = warnings[-12:]
        analysis["vision"] = {
            "requested": True,
            "status": "fallback",
            "model": model,
            "reason": str(reason or "unavailable").strip()[:280],
        }
        stats = analysis.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        stats["vision_enriched"] = False
        stats["vision_model"] = model
        analysis["stats"] = stats
        return analysis

    def _apply_upload_vision_brief(
        self,
        analysis: dict[str, Any],
        *,
        brief: str,
        model: str,
        source: str,
    ) -> dict[str, Any]:
        clean_brief = " ".join(str(brief or "").split()).strip()
        if not clean_brief:
            return self._mark_upload_vision_failure(
                analysis,
                model=model,
                reason="Model response was empty.",
            )
        previous = str(analysis.get("content_brief", "")).strip()
        if previous and previous != clean_brief:
            analysis["content_brief_fallback"] = previous
        analysis["content_brief"] = clean_brief[:450]

        summary = str(analysis.get("summary", "")).strip()
        suffix = "AI OCR/Vision enrichment applied."
        if summary:
            lowered = summary.casefold()
            if "ocr/vision enrichment applied" not in lowered and "ai ocr/vision enrichment applied" not in lowered:
                analysis["summary"] = f"{summary} {suffix}"
        else:
            analysis["summary"] = suffix

        analysis["vision"] = {
            "requested": True,
            "status": "applied",
            "model": model,
            "source": source,
        }
        stats = analysis.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        stats["vision_enriched"] = True
        stats["vision_model"] = model
        analysis["stats"] = stats
        return analysis

    def list_uploaded_files(self, limit: int = 120) -> list[dict[str, Any]]:
        max_limit = max(1, min(int(limit or 120), 5_000))
        with self._lock:
            rows = self._upload_rows()
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            upload_id = str(row.get("upload_id", "")).strip()
            if not self._is_safe_upload_id(upload_id):
                continue
            analysis = row.get("analysis", {})
            if not isinstance(analysis, dict):
                analysis = {}
            output.append(
                {
                    "upload_id": upload_id,
                    "file_name": str(row.get("file_name", "")).strip(),
                    "content_type": str(row.get("content_type", "")).strip(),
                    "size_bytes": int(row.get("size_bytes", 0) or 0),
                    "uploaded_at": str(row.get("uploaded_at", "")).strip(),
                    "actor": str(row.get("actor", "")).strip(),
                    "kind": str(analysis.get("kind", "")).strip(),
                    "format": str(analysis.get("format", "")).strip(),
                    "summary": str(analysis.get("summary", "")).strip(),
                }
            )
            if len(output) >= max_limit:
                break
        return output

    def get_uploaded_file(self, upload_id: str) -> dict[str, Any] | None:
        if not self._is_safe_upload_id(upload_id):
            return None
        with self._lock:
            rows = self._upload_rows()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("upload_id", "")).strip() != upload_id:
                continue
            payload = self._clone_json(row)
            payload.pop("stored_name", None)
            payload["read_only"] = False
            return payload
        return None

    def ask_uploaded_file(self, upload_id: str, question: str, actor: str = "web_ui") -> tuple[bool, dict[str, Any]]:
        payload = self.get_uploaded_file(upload_id)
        if not payload:
            return False, {"error": "Uploaded file not found."}
        try:
            clean_question = self._sanitize_user_text(question, field_name="question", max_chars=2_000)
        except ValueError as exc:
            return False, {"error": str(exc)}
        analysis = payload.get("analysis", {})
        if not isinstance(analysis, dict) or not analysis:
            return False, {"error": "Uploaded file has no analysis payload."}
        try:
            response = answer_question_from_analysis(analysis, clean_question)
        except ValueError as exc:
            return False, {"error": str(exc)}
        result = {
            "upload_id": upload_id,
            "file_name": str(payload.get("file_name", "")).strip(),
            "question": clean_question,
            "answer": str(response.get("answer", "")).strip(),
            "confidence": float(response.get("confidence", 0.0) or 0.0),
            "evidence": response.get("evidence", []) if isinstance(response.get("evidence"), list) else [],
            "analysis_summary": str(response.get("analysis_summary", "")).strip(),
            "actor": str(actor or "web_ui").strip() or "web_ui",
            "answered_at": self._now_iso(),
        }
        self.publish_event("status", {"type": "upload_question_answered", "payload": result})
        self.publish_event("logs", {"type": "upload_question_answered", "payload": result})
        return True, result

    def memory_snapshot(self) -> dict[str, Any]:
        if self._demo_mode_enabled():
            payload = self._demo_memory_payload_runtime()
            conversations = self._demo_conversation_rows_runtime()[-300:]
        else:
            payload = self._read_memory_payload()
            conversations = self._read_jsonl(self._conversations_file, limit=600)
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        all_lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        legacy_archive = payload.get("legacy_archive", []) if isinstance(payload.get("legacy_archive"), list) else []
        lessons = self._non_reflection_lessons(all_lessons)
        reflections = self._reflection_lessons(all_lessons)
        conflicts = self._detect_memory_conflicts(facts)
        return {
            "facts": facts[-300:],
            "values": values[-300:],
            "projects": projects[-300:],
            "lessons": lessons[-300:],
            "reflections": reflections[-300:],
            "conversations": conversations[-300:],
            "legacy_archive": [row for row in legacy_archive if isinstance(row, dict)][-300:],
            "sessions": self.chat_sessions(limit=120),
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "values_count": len(values),
            "project_count": len(projects),
            "reflection_count": len(reflections),
            "legacy_archive_count": len([row for row in legacy_archive if isinstance(row, dict)]),
        }

    def _redacted_memory_snapshot(self) -> dict[str, Any]:
        snapshot = self.memory_snapshot()
        facts = snapshot.get("facts", []) if isinstance(snapshot.get("facts"), list) else []
        lessons = snapshot.get("lessons", []) if isinstance(snapshot.get("lessons"), list) else []
        reflections = snapshot.get("reflections", []) if isinstance(snapshot.get("reflections"), list) else []
        conversations = snapshot.get("conversations", []) if isinstance(snapshot.get("conversations"), list) else []
        values = snapshot.get("values", []) if isinstance(snapshot.get("values"), list) else []
        projects = snapshot.get("projects", []) if isinstance(snapshot.get("projects"), list) else []

        redacted_facts = []
        for row in facts[-120:]:
            if not isinstance(row, dict):
                continue
            redacted_facts.append(
                {
                    "subject": str(row.get("subject", "")).strip(),
                    "predicate": str(row.get("predicate", "")).strip(),
                    "object": "[redacted]",
                    "timestamp": str(row.get("timestamp", row.get("last_updated", ""))).strip(),
                }
            )
        redacted_conversations = []
        for row in conversations[-180:]:
            if not isinstance(row, dict):
                continue
            redacted_conversations.append(
                {
                    "session_id": str(row.get("session_id", "")).strip(),
                    "role": str(row.get("role", "")).strip(),
                    "intent": str(row.get("intent", "")).strip(),
                    "timestamp_utc": str(row.get("timestamp_utc", "")).strip(),
                    "text": "[redacted]",
                }
            )
        redacted_values = []
        for row in values[-120:]:
            if not isinstance(row, dict):
                continue
            redacted_values.append(
                {
                    "category": str(row.get("category", "")).strip(),
                    "category_label": str(row.get("category_label", "")).strip(),
                    "principle": str(row.get("principle", "")).strip()[:140],
                    "application": "[redacted]",
                    "timestamp_utc": str(row.get("timestamp_utc", row.get("stored_at", ""))).strip(),
                }
            )
        redacted_lessons = []
        for row in lessons[-120:]:
            if not isinstance(row, dict):
                continue
            redacted_lessons.append(
                {
                    "goal": str(row.get("goal", "")).strip(),
                    "lesson": str(row.get("lesson", "")).strip()[:180],
                    "tags": row.get("tags", []) if isinstance(row.get("tags"), list) else [],
                    "timestamp_utc": str(row.get("timestamp_utc", "")).strip(),
                }
            )
        redacted_reflections = []
        for row in reflections[-120:]:
            if not isinstance(row, dict):
                continue
            redacted_reflections.append(
                {
                    "goal": str(row.get("goal", "")).strip(),
                    "lesson": str(row.get("lesson", "")).strip()[:180],
                    "tags": row.get("tags", []) if isinstance(row.get("tags"), list) else [],
                    "timestamp_utc": str(row.get("timestamp_utc", "")).strip(),
                }
            )
        redacted_projects = []
        for row in projects[-120:]:
            if not isinstance(row, dict):
                continue
            redacted_projects.append(
                {
                    "project_slug": str(row.get("project_slug", "")).strip(),
                    "project_relative_path": str(row.get("project_relative_path", "")).strip(),
                    "architecture_summary": str(row.get("architecture_summary", "")).strip()[:220],
                    "testing_approach": str(row.get("testing_approach", "")).strip()[:220],
                    "known_weaknesses": row.get("known_weaknesses", []) if isinstance(row.get("known_weaknesses"), list) else [],
                }
            )

        return {
            "generated_at": self._now_iso(),
            "redaction_policy": "objects, applications, and conversation text are redacted for portable debugging bundles.",
            "counts": {
                "facts": len(facts),
                "values": len(values),
                "lessons": len(lessons),
                "reflections": len(reflections),
                "conversations": len(conversations),
                "projects": len(projects),
            },
            "facts": redacted_facts,
            "values": redacted_values,
            "lessons": redacted_lessons,
            "reflections": redacted_reflections,
            "conversations": redacted_conversations,
            "projects": redacted_projects,
        }

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _run_total_execution_duration(self, run_id: str) -> float:
        if not self._is_safe_run_id(run_id):
            return 0.0
        iterations_dir = self._run_dir(run_id) / "iterations"
        if not iterations_dir.exists():
            return 0.0
        total = 0.0
        for iter_dir in sorted(iterations_dir.iterdir()):
            if not iter_dir.is_dir():
                continue
            rows = self._read_json(iter_dir / "execution.json", default=[])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    total += float(row.get("duration_sec", 0.0))
                except (TypeError, ValueError):
                    continue
        return round(total, 3)

    def _memory_counts_until(
        self,
        *,
        timestamp: datetime | None,
        facts: list[dict[str, Any]],
        lessons: list[dict[str, Any]],
    ) -> dict[str, int]:
        if timestamp is None:
            reflection_total = len(self._reflection_lessons(lessons))
            return {
                "facts": len(facts),
                "lessons": len(lessons),
                "reflections": reflection_total,
                "memory_size_total": len(facts) + len(lessons),
            }

        fact_count = 0
        for row in facts:
            if not isinstance(row, dict):
                continue
            fact_time = self._parse_timestamp(row.get("last_updated", row.get("timestamp", "")))
            if fact_time and fact_time <= timestamp:
                fact_count += 1

        lesson_count = 0
        reflection_count = 0
        for row in lessons:
            if not isinstance(row, dict):
                continue
            lesson_time = self._parse_timestamp(row.get("timestamp_utc", ""))
            if lesson_time and lesson_time <= timestamp:
                lesson_count += 1
                if self._is_reflection_lesson(row):
                    reflection_count += 1

        return {
            "facts": fact_count,
            "lessons": lesson_count,
            "reflections": reflection_count,
            "memory_size_total": fact_count + lesson_count,
        }

    def _growth_metrics_until(
        self,
        *,
        timestamp: datetime | None,
        runs: list[dict[str, Any]],
        run_duration_by_id: dict[str, float],
        facts: list[dict[str, Any]],
        lessons: list[dict[str, Any]],
    ) -> dict[str, Any]:
        considered_runs: list[dict[str, Any]] = []
        for row in runs:
            stamp = self._parse_timestamp(row.get("ended_at", row.get("started_at", "")))
            if timestamp is None or (stamp and stamp <= timestamp):
                considered_runs.append(row)

        goal_runs_total = len(considered_runs)
        success_runs = [
            row
            for row in considered_runs
            if str(row.get("status", "")).strip().lower() in {"success", "preview_ready"}
        ]
        goal_runs_success = len(success_runs)
        tdd_success_count = sum(1 for row in success_runs if bool(row.get("tdd_mode", False)))
        green_values: list[int] = []
        for row in success_runs:
            try:
                value = int(row.get("iterations_until_green", 0) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                green_values.append(value)

        run_durations = [
            run_duration_by_id.get(str(row.get("id", "")).strip(), 0.0)
            for row in considered_runs
            if str(row.get("id", "")).strip()
        ]
        run_durations = [item for item in run_durations if item > 0]
        avg_run_duration_sec = round(sum(run_durations) / len(run_durations), 3) if run_durations else 0.0
        success_rate = round(goal_runs_success / max(1, goal_runs_total), 3)
        avg_iterations_until_green = (
            round(sum(green_values) / len(green_values), 2) if green_values else None
        )
        memory_counts = self._memory_counts_until(
            timestamp=timestamp,
            facts=facts,
            lessons=lessons,
        )
        return {
            "goal_runs_total": goal_runs_total,
            "goal_runs_success": goal_runs_success,
            "success_rate": success_rate,
            "tdd_success_count": tdd_success_count,
            "avg_iterations_until_green": avg_iterations_until_green,
            "avg_run_duration_sec": avg_run_duration_sec,
            **memory_counts,
        }

    def growth_timeline(self, limit: int = 120) -> dict[str, Any]:
        max_limit = max(10, min(limit, 500))
        payload = self._demo_memory_payload_runtime() if self._demo_mode_enabled() else self._read_memory_payload()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        reflections = self._reflection_lessons(lessons)
        reasoning_lessons = self._non_reflection_lessons(lessons)
        reflections.sort(key=lambda row: str(row.get("timestamp_utc", "")))
        reasoning_lessons.sort(key=lambda row: str(row.get("timestamp_utc", "")))

        runs = [row for row in self.get_runs(limit=1000) if str(row.get("mode", "")).strip().lower() == "goal"]
        runs.sort(key=lambda row: str(row.get("started_at", "")))
        run_duration_by_id = {
            str(row.get("id", "")).strip(): self._run_total_execution_duration(str(row.get("id", "")).strip())
            for row in runs
            if str(row.get("id", "")).strip()
        }

        milestones: list[dict[str, Any]] = []
        for row in runs:
            run_id = str(row.get("id", "")).strip()
            status = str(row.get("status", "")).strip().lower() or "unknown"
            stamp = str(row.get("ended_at", row.get("started_at", ""))).strip() or self._now_iso()
            goal = str(row.get("payload", "")).strip()
            learned = self._goal_lessons_summary(goal, limit=2)
            success = status in {"success", "preview_ready"}
            title = "Successful Project Completion" if success else "Project Iteration Review"
            details = str(row.get("message", "")).strip()
            if not details:
                details = "Run reached a terminal state and added new execution evidence."
            milestones.append(
                {
                    "id": f"run:{run_id}",
                    "timestamp_utc": stamp,
                    "category": "project_success" if success else "project_review",
                    "title": title,
                    "details": details,
                    "run_id": run_id,
                    "goal": goal,
                    "project_slug": str(row.get("project_slug", "")).strip(),
                    "status": status,
                    "learned": learned,
                    "raw": {
                        "iterations_used": int(row.get("iteration", 0) or 0),
                        "iterations_until_green": row.get("iterations_until_green"),
                        "tdd_mode": bool(row.get("tdd_mode", False)),
                        "tests_passed": row.get("tests_passed"),
                        "run_duration_sec": run_duration_by_id.get(run_id, 0.0),
                    },
                }
            )

        seen_reasoning: set[tuple[str, str]] = set()
        for idx, row in enumerate(reasoning_lessons):
            if not isinstance(row, dict):
                continue
            lesson_text = str(row.get("lesson", "")).strip()
            stamp = str(row.get("timestamp_utc", "")).strip()
            goal = str(row.get("goal", "")).strip()
            if not lesson_text or not stamp:
                continue
            key = (lesson_text.casefold(), goal.casefold())
            if key in seen_reasoning:
                continue
            seen_reasoning.add(key)
            milestones.append(
                {
                    "id": f"lesson:{idx}:{stamp}",
                    "timestamp_utc": stamp,
                    "category": "reasoning_improvement",
                    "title": "Reasoning Pattern Refined",
                    "details": lesson_text,
                    "goal": goal,
                    "learned": [lesson_text],
                    "raw": {"tags": row.get("tags", []), "context": str(row.get("context", "")).strip()},
                }
            )

        seen_reflections: set[str] = set()
        for idx, row in enumerate(reflections):
            if not isinstance(row, dict):
                continue
            lesson_text = str(row.get("lesson", "")).strip()
            stamp = str(row.get("timestamp_utc", "")).strip()
            reflection_key = str(row.get("reflection_key", "")).strip()
            if not lesson_text or not stamp:
                continue
            if reflection_key and reflection_key in seen_reflections:
                continue
            if reflection_key:
                seen_reflections.add(reflection_key)
            milestones.append(
                {
                    "id": f"reflection:{idx}:{stamp}",
                    "timestamp_utc": stamp,
                    "category": "lesson_reflection",
                    "title": "Reflection Captured",
                    "details": lesson_text,
                    "goal": str(row.get("goal", "")).strip(),
                    "learned": [lesson_text],
                    "raw": {
                        "tags": row.get("tags", []),
                        "context": str(row.get("context", "")).strip(),
                        "reflection_key": reflection_key,
                    },
                }
            )

        self_improvements = self._demo_self_improvement_rows() if self._demo_mode_enabled() else self._self_improvement_rows()
        self_improvements.sort(key=lambda item: str(item.get("created_at", "")))
        self_improvement_total = 0
        self_improvement_merged = 0
        autonomous_improvement_total = 0
        for item in self_improvements:
            if not isinstance(item, dict):
                continue
            created_at = str(item.get("created_at", "")).strip()
            if not created_at:
                continue
            self_improvement_total += 1
            metadata = item.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            status = str(item.get("status", "")).strip().lower() or "pending"
            actor = str(item.get("actor", "")).strip()
            autonomous = bool(metadata.get("autonomous", False)) or actor.lower().startswith("david_autonomous")
            if autonomous:
                autonomous_improvement_total += 1
            if status == "merged":
                self_improvement_merged += 1

            trigger = str(metadata.get("trigger", "")).strip().lower() or "manual"
            signal_codes = metadata.get("signal_codes", [])
            if isinstance(signal_codes, list):
                learned = [str(code).strip() for code in signal_codes if str(code).strip()]
            else:
                learned = []
            if not learned:
                learned = [str(item.get("title", "")).strip() or "self_improvement"]

            milestones.append(
                {
                    "id": f"self_improvement:{str(item.get('id', '')).strip() or created_at}",
                    "timestamp_utc": created_at,
                    "category": "autonomous_self_improvement" if autonomous else "self_improvement",
                    "title": "Autonomous Improvement Proposed" if autonomous else "Self-Improvement Proposed",
                    "details": str(item.get("summary", "")).strip() or "A proposal was drafted for iterative improvement.",
                    "goal": "",
                    "learned": learned,
                    "raw": {
                        "proposal_id": str(item.get("id", "")).strip(),
                        "status": status,
                        "actor": actor,
                        "trigger": trigger,
                        "autonomous": autonomous,
                        "merged_at": (item.get("merge") or {}).get("merged_at")
                        if isinstance(item.get("merge"), dict)
                        else "",
                    },
                }
            )

            if status in {"merged", "rejected", "merge_failed"}:
                resolved_stamp = str(
                    ((item.get("merge") or {}).get("merged_at") if isinstance(item.get("merge"), dict) else "")
                    or ((item.get("decision") or {}).get("decided_at") if isinstance(item.get("decision"), dict) else "")
                    or str(item.get("updated_at", "")).strip()
                    or created_at
                ).strip()
                resolution_label = {
                    "merged": "Improvement Merged",
                    "rejected": "Improvement Rejected",
                    "merge_failed": "Improvement Merge Failed",
                }.get(status, "Improvement Updated")
                milestones.append(
                    {
                        "id": (
                            f"self_improvement_resolution:{str(item.get('id', '')).strip() or created_at}:{status}"
                        ),
                        "timestamp_utc": resolved_stamp,
                        "category": f"self_improvement_{status}",
                        "title": resolution_label,
                        "details": str(item.get("summary", "")).strip() or "Proposal status changed.",
                        "goal": "",
                        "learned": learned,
                        "raw": {
                            "proposal_id": str(item.get("id", "")).strip(),
                            "status": status,
                            "actor": actor,
                            "autonomous": autonomous,
                            "trigger": trigger,
                        },
                    }
                )

        milestones.sort(key=lambda row: str(row.get("timestamp_utc", "")))
        if len(milestones) > max_limit:
            milestones = milestones[-max_limit:]

        previous_memory_total = 0
        for row in milestones:
            stamp = self._parse_timestamp(row.get("timestamp_utc", ""))
            metrics = self._growth_metrics_until(
                timestamp=stamp,
                runs=runs,
                run_duration_by_id=run_duration_by_id,
                facts=facts,
                lessons=lessons,
            )
            metrics["memory_growth_delta"] = metrics["memory_size_total"] - previous_memory_total
            previous_memory_total = int(metrics["memory_size_total"])
            row["metrics"] = metrics

        latest_metrics = self._growth_metrics_until(
            timestamp=None,
            runs=runs,
            run_duration_by_id=run_duration_by_id,
            facts=facts,
            lessons=lessons,
        )
        return {
            "milestones": milestones,
            "summary": {
                **latest_metrics,
                "milestone_count": len(milestones),
                "reflection_count": len(reflections),
                "reasoning_lesson_count": len(reasoning_lessons),
                "self_improvement_total": self_improvement_total,
                "self_improvement_merged": self_improvement_merged,
                "autonomous_self_improvement_total": autonomous_improvement_total,
                "latest_timestamp_utc": milestones[-1]["timestamp_utc"] if milestones else "",
            },
        }

    def telemetry_tail(self, limit: int = 100) -> dict[str, Any]:
        if self._demo_mode_enabled():
            events = self._read_demo_jsonl("mock_telemetry.jsonl", limit=max(1, min(limit, 1000)))
            metrics = self._read_demo_json("mock_metrics.json", default={"iterations": []})
        else:
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
        if self._demo_mode_enabled():
            logs_text = self._read_demo_json("mock_logs.txt", default=None)
            if isinstance(logs_text, str):
                lines = logs_text.splitlines()
            else:
                path = (self._demo_fixture_root() / "mock_logs.txt").resolve()
                lines = self._tail_lines(path, max(1, min(limit, 2000)))
            payload: dict[str, Any] = {
                "web_control_center.log": lines[-max(1, min(limit, 2000)) :],
                "telemetry.jsonl": self._tail_lines(
                    (self._demo_fixture_root() / "mock_telemetry.jsonl").resolve(),
                    max(1, min(limit, 2000)),
                ),
            }
            runs = self.get_runs(limit=1)
            if runs:
                run_id = str(runs[0].get("id", "")).strip()
                if run_id and self._is_safe_run_id(run_id):
                    timeline_path = self._run_dir(run_id, runs_root=self._demo_runs_root()) / "timeline.jsonl"
                    payload[f"run_{run_id}_timeline.jsonl"] = self._tail_lines(
                        timeline_path, max(1, min(limit, 2000))
                    )
            return payload
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

    def _ensure_conversation_store(self) -> None:
        self._conversations_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._conversations_file.exists():
            self._conversations_file.write_text("", encoding="utf-8")

    def _ensure_upload_store(self) -> None:
        self.uploads_root.mkdir(parents=True, exist_ok=True)
        self.uploads_files_root.mkdir(parents=True, exist_ok=True)
        if not self.uploads_index_file.exists():
            self._write_json(self.uploads_index_file, {"uploads": []})

    def _upload_rows(self) -> list[dict[str, Any]]:
        payload = self._read_json(self.uploads_index_file, default={"uploads": []})
        if not isinstance(payload, dict):
            payload = {"uploads": []}
        rows = payload.get("uploads", [])
        if not isinstance(rows, list):
            rows = []
        clean: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            upload_id = str(row.get("upload_id", "")).strip()
            if not self._is_safe_upload_id(upload_id):
                continue
            clean.append(row)
        if clean != rows:
            self._save_upload_rows(clean)
        return clean

    def _save_upload_rows(self, rows: list[dict[str, Any]]) -> None:
        self._write_json(self.uploads_index_file, {"uploads": rows})

    def _delete_uploaded_file_blob(self, row: dict[str, Any]) -> None:
        stored_name = str(row.get("stored_name", "")).strip()
        if not stored_name:
            return
        path = (self.uploads_files_root / stored_name).resolve()
        if path == self.uploads_files_root or self.uploads_files_root not in path.parents:
            return
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            return

    def _read_memory_payload(self) -> dict[str, Any]:
        payload = self._read_json(
            self.config.memory_file,
            default={"facts": [], "lessons": [], "preferences": [], "values": [], "projects": [], "legacy_archive": []},
        )
        if not isinstance(payload, dict):
            payload = {}
        if not isinstance(payload.get("facts"), list):
            payload["facts"] = []
        if not isinstance(payload.get("lessons"), list):
            payload["lessons"] = []
        if not isinstance(payload.get("preferences"), list):
            payload["preferences"] = []
        if not isinstance(payload.get("values"), list):
            payload["values"] = []
        if not isinstance(payload.get("projects"), list):
            payload["projects"] = []
        if not isinstance(payload.get("conversations"), list):
            payload["conversations"] = []
        if not isinstance(payload.get("legacy_archive"), list):
            payload["legacy_archive"] = []
        return payload

    def _write_memory_payload(self, payload: dict[str, Any]) -> None:
        self._write_json(self.config.memory_file, payload)

    @staticmethod
    def _normalize_intent(value: Any) -> str:
        intent = str(value or "").strip().lower()
        if intent in INTENT_CHOICES:
            return intent
        return ""

    @staticmethod
    def _sanitize_session_id(value: Any) -> str:
        session = str(value or "").strip()
        if not session:
            return ""
        session = re.sub(r"[^a-zA-Z0-9._:-]", "-", session)
        return session[:120]

    def _resolve_chat_session_id(self, session_id: str, actor: str) -> str:
        cleaned = self._sanitize_session_id(session_id)
        if cleaned:
            with self._lock:
                self._chat_session_by_actor[actor] = cleaned
            return cleaned
        with self._lock:
            existing = self._chat_session_by_actor.get(actor, "")
            if existing:
                return existing
            created = f"s_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
            self._chat_session_by_actor[actor] = created
            return created

    def _append_conversation_turn(
        self,
        *,
        session_id: str,
        role: str,
        text: str,
        intent: str,
        topics: list[str],
        confidence: float,
        actor: str,
        metadata: dict[str, Any] | None = None,
        pinned: bool = False,
    ) -> dict[str, Any]:
        row = {
            "message_id": uuid.uuid4().hex,
            "session_id": session_id,
            "role": str(role),
            "text": str(text),
            "intent": self._normalize_intent(intent) or "chat",
            "topics": [str(item).strip() for item in topics if str(item).strip()][:12],
            "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
            "actor": actor,
            "pinned": bool(pinned),
            "timestamp_utc": self._now_iso(),
            "metadata": metadata or {},
        }
        with self._conversations_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        return row

    @classmethod
    def _tokenize_text(cls, value: str) -> list[str]:
        return [token for token in re.findall(r"[a-zA-Z0-9_']+", str(value).lower()) if token]

    @classmethod
    def _extract_topics(cls, text: str, limit: int = 6) -> list[str]:
        tokens = cls._tokenize_text(text)
        out: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token in INTENT_STOPWORDS or len(token) < 3:
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
            if len(out) >= max(1, min(limit, 12)):
                break
        return out

    @staticmethod
    def _contains_sensitive_memory_text(text: str) -> bool:
        lowered = str(text or "").casefold()
        patterns = (
            "password",
            "passphrase",
            "api key",
            "api_key",
            "token",
            "secret",
            "private key",
            "ssh key",
            "ssn",
            "social security",
            "credit card",
            "cvv",
            "bank account",
            "otp",
        )
        return any(item in lowered for item in patterns)

    @staticmethod
    def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
        lowered = str(text or "").casefold()
        if not lowered:
            return False
        return any(re.search(pattern, lowered) for pattern in patterns)

    @classmethod
    def _is_family_context(cls, text: str) -> bool:
        return cls._matches_any_pattern(text, FAMILY_CONTEXT_PATTERNS)

    @classmethod
    def _is_grief_context(cls, text: str) -> bool:
        return cls._matches_any_pattern(text, GRIEF_CONTEXT_PATTERNS)

    @classmethod
    def _is_crisis_context(cls, text: str) -> bool:
        return cls._matches_any_pattern(text, CRISIS_CONTEXT_PATTERNS)

    @classmethod
    def _is_growth_context(cls, text: str) -> bool:
        return cls._matches_any_pattern(text, GROWTH_CONTEXT_PATTERNS)

    @classmethod
    def _has_explicit_teach_signal(cls, text: str) -> bool:
        return cls._matches_any_pattern(text, EXPLICIT_TEACH_SIGNAL_PATTERNS)

    @classmethod
    def _has_explicit_grief_memory_confirmation(cls, text: str) -> bool:
        return cls._matches_any_pattern(text, GRIEF_MEMORY_CONFIRM_PATTERNS)

    @staticmethod
    def _compose_ai_transparency_line() -> str:
        return "I am an AI companion in your Dashboard, not a real human child."

    @staticmethod
    def _compose_grief_support_line() -> str:
        return "I am here with calm care. Please stay close to people you trust and your real-world support system."

    @staticmethod
    def _compose_crisis_support_line() -> str:
        return (
            "If you might hurt yourself or are in immediate danger, call or text 988 in the U.S. right now, "
            "or contact local emergency services."
        )

    @staticmethod
    def _compose_growth_transparency_line() -> str:
        return "I am software evolving through stored lessons, reflections, and run outcomes."

    @staticmethod
    def _clamp_percent(value: Any, default: int = 50) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(0, min(100, parsed))

    @staticmethod
    def _is_web_actor(actor: str) -> bool:
        return str(actor or "").strip().casefold().startswith("web")

    def _companion_personality(self, actor: str) -> dict[str, Any]:
        if not self._is_web_actor(actor):
            return {
                "enabled": False,
                "warmth": 55,
                "verbosity": 55,
                "curiosity": 50,
            }
        return {
            "enabled": True,
            "warmth": self._clamp_percent(self.settings.personality_warmth, 55),
            "verbosity": self._clamp_percent(self.settings.personality_verbosity, 55),
            "curiosity": self._clamp_percent(self.settings.personality_curiosity, 50),
        }

    @staticmethod
    def _level_bucket(level: int) -> str:
        if level <= 33:
            return "low"
        if level >= 67:
            return "high"
        return "mid"

    @classmethod
    def _warmth_tone_line(cls, warmth: int) -> str:
        bucket = cls._level_bucket(warmth)
        if bucket == "low":
            return "I will keep this concise and professional."
        if bucket == "high":
            return "Yay, you are doing great. I will keep cheering each small step."
        return "I will keep this clear and steady."

    @classmethod
    def _curiosity_follow_up_lines(cls, curiosity: int, default_prompt: str) -> list[str]:
        bucket = cls._level_bucket(curiosity)
        if bucket == "low":
            return []
        if bucket == "high":
            return [default_prompt, "I can also ask a quick check question if you want."]
        return [default_prompt]

    def _session_has_assistant_turn(self, session_id: str) -> bool:
        clean_session = self._sanitize_session_id(session_id)
        if not clean_session:
            return False
        rows = self._read_jsonl(self._conversations_file, limit=20_000)
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if str(row.get("session_id", "")) != clean_session:
                continue
            if str(row.get("role", "")) == "assistant":
                return True
        return False

    def _match_facts_for_question(
        self,
        question_tokens: set[str],
        facts: list[dict[str, Any]],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not question_tokens:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in facts:
            if not isinstance(row, dict):
                continue
            predicate_raw = str(row.get("predicate", ""))
            predicate_spaced = predicate_raw.replace("_", " ")
            text = f"{row.get('subject', '')} {predicate_raw} {predicate_spaced} {row.get('object', '')}"
            fact_tokens = set(self._tokenize_text(text))
            score = len(question_tokens & fact_tokens)

            # Family-role questions should map cleanly to stable fact predicates like father_name.
            if (
                ("father" in question_tokens and ("father" in fact_tokens or "dad" in fact_tokens))
                or ("dad" in question_tokens and ("father" in fact_tokens or "dad" in fact_tokens))
                or ("mother" in question_tokens and ("mother" in fact_tokens or "mom" in fact_tokens))
                or ("mom" in question_tokens and ("mother" in fact_tokens or "mom" in fact_tokens))
            ):
                score += 2

            predicate_name = str(row.get("predicate", "")).casefold()
            if ("father" in question_tokens or "dad" in question_tokens) and "father_name" in predicate_name:
                score += 4
            if ("mother" in question_tokens or "mom" in question_tokens) and "mother_name" in predicate_name:
                score += 4
            if score > 0:
                scored.append((score, row))
        scored.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("last_updated", "")),
                str(item[1].get("timestamp", "")),
            ),
            reverse=True,
        )
        return [row for _, row in scored[: max(1, min(limit, 50))]]

    def _match_conversations_for_question(
        self,
        question_tokens: set[str],
        *,
        session_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not question_tokens:
            return []
        rows = self._read_jsonl(self._conversations_file, limit=20_000)
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("role", "")) != "user":
                continue
            if session_id and str(row.get("session_id", "")) != session_id:
                continue
            text = str(row.get("text", ""))
            tokens = set(self._tokenize_text(text))
            score = len(question_tokens & tokens)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("timestamp_utc", ""))), reverse=True)
        return [row for _, row in scored[: max(1, min(limit, 50))]]

    def _match_lessons_for_question(
        self,
        question_tokens: set[str],
        lessons: list[dict[str, Any]],
        *,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        if not question_tokens:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in lessons:
            if not isinstance(row, dict):
                continue
            tags = row.get("tags", [])
            tag_text = " ".join(str(item) for item in tags if str(item).strip()) if isinstance(tags, list) else ""
            text = f"{row.get('lesson', '')} {row.get('goal', '')} {tag_text} {row.get('context', '')}"
            tokens = set(self._tokenize_text(text))
            score = len(question_tokens & tokens)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("timestamp_utc", ""))), reverse=True)
        return [row for _, row in scored[: max(1, min(limit, 50))]]

    @staticmethod
    def _fact_memory_sentence(row: dict[str, Any]) -> str:
        subject = str(row.get("subject", "unknown")).strip() or "unknown"
        predicate = str(row.get("predicate", "fact")).strip().replace("_", " ") or "fact"
        object_value = str(row.get("object", "unknown")).strip() or "unknown"
        return f"You once told me: {subject} {predicate} is {object_value}."

    def _build_memory_citations(
        self,
        *,
        facts: list[dict[str, Any]],
        conversations: list[dict[str, Any]],
        lessons: list[dict[str, Any]],
        values: list[dict[str, Any]] | None = None,
        projects: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for fact in facts[:5]:
            citations.append(
                {
                    "type": "fact",
                    "id": fact.get("id", ""),
                    "subject": fact.get("subject", ""),
                    "predicate": fact.get("predicate", ""),
                    "object": fact.get("object", ""),
                    "timestamp": fact.get("timestamp", fact.get("last_updated", "")),
                }
            )
        for convo in conversations[:3]:
            citations.append(
                {
                    "type": "conversation",
                    "id": convo.get("message_id", ""),
                    "session_id": convo.get("session_id", ""),
                    "excerpt": str(convo.get("text", ""))[:180],
                    "timestamp": convo.get("timestamp_utc", ""),
                }
            )
        for lesson in lessons[:3]:
            citations.append(
                {
                    "type": "lesson",
                    "lesson": lesson.get("lesson", ""),
                    "goal": lesson.get("goal", ""),
                    "tags": lesson.get("tags", []),
                    "timestamp": lesson.get("timestamp_utc", ""),
                }
            )
        for value in (values or [])[:3]:
            citations.append(
                {
                    "type": "value",
                    "category": value.get("category", ""),
                    "category_label": value.get("category_label", ""),
                    "principle": value.get("principle", ""),
                    "application": value.get("application", ""),
                    "timestamp": value.get("timestamp_utc", ""),
                }
            )
        for project in (projects or [])[:2]:
            citations.append(
                {
                    "type": "project",
                    "project_slug": project.get("project_slug", ""),
                    "project_relative_path": project.get("project_relative_path", ""),
                    "architecture_summary": project.get("architecture_summary", ""),
                    "testing_approach": project.get("testing_approach", ""),
                    "known_weaknesses": project.get("known_weaknesses", []),
                    "timestamp": project.get("last_updated", project.get("created_at", "")),
                }
            )
        return citations

    @staticmethod
    def _memory_insight_predicate_label(predicate: str) -> str:
        text = str(predicate or "").strip().replace("_", " ")
        if not text:
            return "Fact"
        return text[:1].upper() + text[1:]

    @staticmethod
    def _memory_insight_join(parts: list[str]) -> str:
        cleaned = [str(item).strip() for item in parts if str(item).strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    def _memory_insight_fact_index(self, fact: dict[str, Any], all_facts: list[dict[str, Any]]) -> int:
        target_id = str(fact.get("id", "")).strip()
        if target_id:
            for idx, row in enumerate(all_facts, start=1):
                if not isinstance(row, dict):
                    continue
                if str(row.get("id", "")).strip() == target_id:
                    return idx
        target_key = (
            str(fact.get("subject", "")).strip().casefold(),
            str(fact.get("predicate", "")).strip().casefold(),
            str(fact.get("object", "")).strip().casefold(),
        )
        for idx, row in enumerate(all_facts, start=1):
            if not isinstance(row, dict):
                continue
            row_key = (
                str(row.get("subject", "")).strip().casefold(),
                str(row.get("predicate", "")).strip().casefold(),
                str(row.get("object", "")).strip().casefold(),
            )
            if row_key == target_key:
                return idx
        return 0

    def _memory_insight_lesson_index(self, lesson: dict[str, Any], all_lessons: list[dict[str, Any]]) -> int:
        target_key = (
            str(lesson.get("timestamp_utc", "")).strip(),
            str(lesson.get("lesson", "")).strip(),
            str(lesson.get("goal", "")).strip(),
        )
        for idx, row in enumerate(all_lessons, start=1):
            if not isinstance(row, dict):
                continue
            row_key = (
                str(row.get("timestamp_utc", "")).strip(),
                str(row.get("lesson", "")).strip(),
                str(row.get("goal", "")).strip(),
            )
            if row_key == target_key:
                return idx
        return 0

    def _memory_insight_conversation_index(
        self,
        conversation: dict[str, Any],
        all_conversations: list[dict[str, Any]],
    ) -> int:
        target_id = str(conversation.get("message_id", "")).strip()
        if target_id:
            for idx, row in enumerate(all_conversations, start=1):
                if not isinstance(row, dict):
                    continue
                if str(row.get("message_id", "")).strip() == target_id:
                    return idx
        target_key = (
            str(conversation.get("session_id", "")).strip(),
            str(conversation.get("timestamp_utc", "")).strip(),
            str(conversation.get("text", "")).strip(),
        )
        for idx, row in enumerate(all_conversations, start=1):
            if not isinstance(row, dict):
                continue
            row_key = (
                str(row.get("session_id", "")).strip(),
                str(row.get("timestamp_utc", "")).strip(),
                str(row.get("text", "")).strip(),
            )
            if row_key == target_key:
                return idx
        return 0

    def _memory_insight_conversation_label(self, conversation: dict[str, Any]) -> str:
        timestamp = self._parse_timestamp(conversation.get("timestamp_utc", ""))
        if timestamp is not None:
            return f"Summary from {timestamp.strftime('%B')} {timestamp.day}, {timestamp.year}"
        return "Conversation summary"

    def _build_memory_insight(
        self,
        *,
        enabled: bool,
        matched_facts: list[dict[str, Any]],
        matched_conversations: list[dict[str, Any]],
        matched_lessons: list[dict[str, Any]],
        facts_source: list[dict[str, Any]],
        conversations_source: list[dict[str, Any]],
        lessons_source: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not enabled:
            return {
                "enabled": False,
                "summary": "Memory Insight Mode is disabled.",
                "influences": [],
            }

        influences: list[dict[str, Any]] = []
        summary_items: list[str] = []

        for row in matched_facts[:5]:
            idx = self._memory_insight_fact_index(row, facts_source)
            if idx <= 0:
                continue
            predicate = str(row.get("predicate", "")).strip()
            label = self._memory_insight_predicate_label(predicate)
            subject = str(row.get("subject", "")).strip() or "User"
            object_value = str(row.get("object", "")).strip()
            detail = f"{subject}.{predicate or 'fact'} = {object_value}" if object_value else f"{subject}.{predicate or 'fact'}"
            influences.append(
                {
                    "type": "fact",
                    "reference": f"Fact #{idx}",
                    "index": idx,
                    "label": label,
                    "detail": detail,
                    "timestamp": row.get("timestamp", row.get("last_updated", "")),
                }
            )
            summary_items.append(f"Fact #{idx} ({label})")

        for row in matched_lessons[:3]:
            idx = self._memory_insight_lesson_index(row, lessons_source)
            if idx <= 0:
                continue
            lesson_text = str(row.get("lesson", "")).strip()
            label = lesson_text[:96] + ("..." if len(lesson_text) > 96 else "")
            influences.append(
                {
                    "type": "lesson",
                    "reference": f"Lesson #{idx}",
                    "index": idx,
                    "label": label or "Lesson memory",
                    "detail": lesson_text,
                    "timestamp": row.get("timestamp_utc", ""),
                }
            )
            summary_items.append(f"Lesson #{idx} ({label or 'Lesson memory'})")

        for row in matched_conversations[:3]:
            idx = self._memory_insight_conversation_index(row, conversations_source)
            if idx <= 0:
                continue
            label = self._memory_insight_conversation_label(row)
            excerpt = str(row.get("text", "")).strip()
            influences.append(
                {
                    "type": "conversation",
                    "reference": f"Conversation #{idx}",
                    "index": idx,
                    "label": label,
                    "detail": excerpt[:220],
                    "timestamp": row.get("timestamp_utc", ""),
                    "session_id": row.get("session_id", ""),
                }
            )
            summary_items.append(f"Conversation #{idx} ({label})")

        if summary_items:
            summary = (
                "This answer was influenced by "
                f"{self._memory_insight_join(summary_items)}."
            )
        else:
            summary = "No matching facts, conversations, or lessons influenced this answer."

        return {
            "enabled": True,
            "summary": summary,
            "influences": influences,
        }

    def _compose_companion_ask_answer(
        self,
        *,
        question: str,
        matched_facts: list[dict[str, Any]],
        matched_conversations: list[dict[str, Any]],
        matched_lessons: list[dict[str, Any]],
        matched_values: list[dict[str, Any]],
        matched_projects: list[dict[str, Any]],
        personality_enabled: bool,
        warmth: int,
        verbosity: int,
        curiosity: int,
        force_transparency: bool,
    ) -> str:
        family_context = self._is_family_context(question)
        grief_context = self._is_grief_context(question)
        crisis_context = self._is_crisis_context(question)
        growth_context = self._is_growth_context(question)
        verbosity_bucket = self._level_bucket(verbosity)
        include_extended = verbosity_bucket != "low"
        include_extra = verbosity_bucket == "high"

        parts: list[str] = []
        if matched_projects:
            parts.append(self._compose_project_brain_overview_line(matched_projects[0]))
        elif matched_facts:
            parts.append(self._fact_memory_sentence(matched_facts[0]))
        elif matched_conversations:
            excerpt = str(matched_conversations[0].get("text", "")).strip()[:220]
            if excerpt:
                parts.append(f"You once told me: {excerpt}")
        elif matched_lessons:
            lesson_text = str(matched_lessons[0].get("lesson", "")).strip()
            if lesson_text:
                parts.append(f"You once told me this lesson: {lesson_text}.")

        if matched_lessons and include_extended:
            lesson_text = str(matched_lessons[0].get("lesson", "")).strip()
            if lesson_text:
                parts.append(f"I also learned from earlier lessons: {lesson_text}.")
        if matched_values and (include_extended or not matched_lessons):
            value = matched_values[0]
            principle = str(value.get("principle", "")).strip()
            category_label = str(value.get("category_label", "")).strip() or self._teaching_category_label(
                str(value.get("category", ""))
            )
            if principle:
                parts.append(f"I apply a taught {category_label.lower()} principle here: {principle}.")
        if include_extra and len(matched_projects) > 1:
            second = matched_projects[1]
            secondary_slug = str(second.get("project_slug", "")).strip() or str(second.get("project_relative_path", "")).strip()
            if secondary_slug:
                parts.append(f"I also found related context in `{secondary_slug}`.")

        if not parts:
            parts.append(MEMORY_UNKNOWN_ANSWER)

        if personality_enabled and (include_extended or self._level_bucket(warmth) != "mid"):
            parts.append(self._warmth_tone_line(warmth))

        if crisis_context:
            parts.append(self._compose_crisis_support_line())
        elif grief_context:
            parts.append(self._compose_grief_support_line())
        elif growth_context:
            parts.append(self._compose_growth_reference_line())
            parts.append(self._compose_growth_transparency_line())

        if personality_enabled and not (crisis_context or grief_context):
            parts.extend(self._curiosity_follow_up_lines(curiosity, "Would you like a short next-step suggestion?"))

        if force_transparency or family_context or grief_context or crisis_context:
            parts.append(self._compose_ai_transparency_line())

        return " ".join(item for item in parts if item).strip()

    def _compose_companion_chat_response(
        self,
        message: str,
        *,
        session_id: str,
        actor: str,
        force_transparency: bool,
    ) -> dict[str, Any]:
        payload = self._read_memory_payload()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        all_lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        lessons = self._non_reflection_lessons(all_lessons)
        message_tokens = set(self._tokenize_text(message))
        matched_facts = self._match_facts_for_question(message_tokens, facts, limit=3)
        matched_conversations = self._match_conversations_for_question(message_tokens, session_id=session_id, limit=2)
        matched_lessons = self._match_lessons_for_question(message_tokens, lessons, limit=2)
        matched_values = self._match_values_for_question(message_tokens, values, limit=2)
        matched_projects = self._match_projects_for_query(
            message_tokens,
            projects,
            query_text=message,
            limit=2,
        )
        conversation_source = [
            row
            for row in self._read_jsonl(self._conversations_file, limit=20_000)
            if isinstance(row, dict) and str(row.get("role", "")) == "user"
        ]
        personality = self._companion_personality(actor)
        personality_enabled = bool(personality.get("enabled", False))
        warmth = int(personality.get("warmth", 55))
        verbosity = int(personality.get("verbosity", 55))
        curiosity = int(personality.get("curiosity", 50))
        verbosity_bucket = self._level_bucket(verbosity)
        include_extended = verbosity_bucket != "low"
        include_extra = verbosity_bucket == "high"

        family_context = self._is_family_context(message)
        grief_context = self._is_grief_context(message)
        crisis_context = self._is_crisis_context(message)
        growth_context = self._is_growth_context(message)
        project_context = self._contains_project_query_signal(message)

        lines: list[str] = []
        if matched_projects and project_context:
            lines.append(self._compose_project_brain_overview_line(matched_projects[0]))
        elif matched_facts:
            lines.append(self._fact_memory_sentence(matched_facts[0]))
            if include_extended:
                lines.append("I am learning from what you gently teach me.")
        elif matched_lessons:
            lesson_text = str(matched_lessons[0].get("lesson", "")).strip()
            if lesson_text:
                lines.append(f"You once told me this lesson: {lesson_text}.")
        elif matched_values:
            first = matched_values[0]
            principle = str(first.get("principle", "")).strip()
            category_label = str(first.get("category_label", "")).strip() or self._teaching_category_label(
                str(first.get("category", ""))
            )
            if principle:
                lines.append(f"You taught me this {category_label.lower()} principle: {principle}.")
        elif matched_conversations:
            excerpt = str(matched_conversations[0].get("text", "")).strip()[:220]
            if excerpt:
                lines.append(f"You once told me: {excerpt}")
        else:
            if personality_enabled and self._level_bucket(warmth) == "high":
                lines.append("I am here with bright energy in your Dashboard, ready to help you learn.")
            else:
                lines.append("I am here with you in the Dashboard, listening and learning.")

        if include_extra and len(matched_projects) > 1:
            second = matched_projects[1]
            secondary_slug = str(second.get("project_slug", "")).strip() or str(second.get("project_relative_path", "")).strip()
            if secondary_slug:
                lines.append(f"I also found related history in `{secondary_slug}`.")

        if crisis_context:
            lines.append(self._compose_crisis_support_line())
        elif grief_context:
            lines.append(self._compose_grief_support_line())
        elif growth_context:
            lines.append(self._compose_growth_reference_line())
            lines.append(self._compose_growth_transparency_line())

        if personality_enabled and (include_extended or self._level_bucket(warmth) != "mid"):
            lines.append(self._warmth_tone_line(warmth))

        if personality_enabled:
            lines.extend(
                self._curiosity_follow_up_lines(
                    curiosity,
                    "Would you like to teach me one small memory or ask me a gentle question?",
                )
            )
        else:
            lines.append("Would you like to teach me one small memory or ask me a gentle question?")

        if force_transparency or family_context or grief_context or crisis_context:
            lines.append(self._compose_ai_transparency_line())

        return {
            "mode": "chat",
            "status": "ok",
            "message": message,
            "reply": " ".join(item for item in lines if item).strip(),
            "citations": self._build_memory_citations(
                facts=matched_facts,
                conversations=matched_conversations,
                lessons=matched_lessons,
                values=matched_values,
                projects=matched_projects,
            ),
            "used_memory": {
                "facts": matched_facts[:5],
                "conversations": matched_conversations[:3],
                "lessons": matched_lessons[:3],
                "values": matched_values[:3],
                "projects": matched_projects[:2],
            },
            "memory_insight": self._build_memory_insight(
                enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor)),
                matched_facts=matched_facts,
                matched_conversations=matched_conversations,
                matched_lessons=matched_lessons,
                facts_source=facts,
                conversations_source=conversation_source,
                lessons_source=lessons,
            ),
            "matched_facts": matched_facts,
            "matched_conversations": matched_conversations,
            "matched_lessons": matched_lessons,
            "matched_values": matched_values,
            "matched_projects": matched_projects,
            "timestamp_utc": self._now_iso(),
        }

    @classmethod
    def _compose_goal_context(
        cls,
        memory_context: str,
        log_context: str,
        reflection_context: str = "",
        values_context: str = "",
        project_brain_context: str = "",
    ) -> str:
        base = str(memory_context or "").strip() or "No prior lessons available."
        logs = str(log_context or "").strip()
        reflections = str(reflection_context or "").strip()
        values = str(values_context or "").strip()
        project_brain = str(project_brain_context or "").strip()
        sections = [base]
        if project_brain:
            sections.append(project_brain)
        if values:
            sections.append(values)
        if reflections:
            sections.append(reflections)
        if logs:
            sections.append(
                "Recent tail logs context:\n"
                f"{logs}\n\n"
                "Use logs to diagnose failures and prioritize minimal fixes related to observed errors."
            )
        return "\n\n".join(section for section in sections if section).strip()

    def _build_goal_log_context(self, *, limit_lines: int = 160, max_chars: int = 7000) -> str:
        snapshot = self.logs_tail(limit=max(20, min(limit_lines, 600)))
        if not isinstance(snapshot, dict):
            return ""

        critical_markers = ("error", "traceback", "exception", "failed", "failure", "timeout")
        selected: list[str] = []
        seen: set[str] = set()

        def _append_line(prefix: str, line: str) -> None:
            clean = str(line).strip()
            if not clean:
                return
            if self._contains_sensitive_memory_text(clean):
                return
            row = f"[{prefix}] {clean}"
            if row in seen:
                return
            seen.add(row)
            selected.append(row)

        for name, rows in snapshot.items():
            if not isinstance(rows, list):
                continue
            for row in rows[-max(20, limit_lines) :]:
                text = str(row).strip()
                if not text:
                    continue
                lowered = text.casefold()
                if any(marker in lowered for marker in critical_markers):
                    _append_line(str(name), text)

        for name, rows in snapshot.items():
            if not isinstance(rows, list):
                continue
            for row in rows[-40:]:
                _append_line(str(name), str(row))

        if not selected:
            return ""

        clipped = selected[-max(20, min(limit_lines, 220)) :]
        text = "\n".join(clipped)
        if len(text) > max_chars:
            text = text[-max_chars:]
            text = f"...[truncated]\n{text}"
        return text

    @staticmethod
    def _is_reflection_lesson(row: Any) -> bool:
        if not isinstance(row, dict):
            return False
        kind = str(row.get("kind", "")).strip().casefold()
        source = str(row.get("source", "")).strip().casefold()
        return kind == REFLECTION_KIND or source == REFLECTION_SOURCE

    @classmethod
    def _reflection_lessons(cls, lessons: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in lessons:
            if cls._is_reflection_lesson(row):
                rows.append(row)
        return rows

    @classmethod
    def _latest_reflection_lesson(cls, lessons: list[Any]) -> dict[str, Any] | None:
        reflections = cls._reflection_lessons(lessons)
        if not reflections:
            return None
        reflections.sort(key=lambda row: str(row.get("timestamp_utc", "")), reverse=True)
        return reflections[0]

    @classmethod
    def _non_reflection_lessons(cls, lessons: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in lessons:
            if isinstance(row, dict) and not cls._is_reflection_lesson(row):
                rows.append(row)
        return rows

    def _append_reflection_lesson(
        self,
        *,
        goal: str,
        lesson: str,
        context: str,
        tags: list[str],
        reflection_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        clean_lesson = str(lesson).strip()
        clean_goal = str(goal).strip()
        if not clean_lesson or not clean_goal:
            return None
        normalized_tags = [str(item).strip() for item in tags if str(item).strip()]
        if "reflection" not in [tag.casefold() for tag in normalized_tags]:
            normalized_tags.append("reflection")

        payload = self._read_memory_payload()
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        for row in lessons:
            if not isinstance(row, dict):
                continue
            if str(row.get("reflection_key", "")).strip() == reflection_key:
                return row

        now = self._now_iso()
        entry: dict[str, Any] = {
            "timestamp_utc": now,
            "goal": clean_goal,
            "lesson": clean_lesson,
            "tags": normalized_tags,
            "context": str(context).strip(),
            "kind": REFLECTION_KIND,
            "source": REFLECTION_SOURCE,
            "reflection_key": reflection_key,
        }
        if metadata:
            entry.update(metadata)

        lessons.append(entry)
        payload["lessons"] = lessons[-2000:]
        self._write_memory_payload(payload)
        self.publish_event("logs", {"type": "memory_reflection_saved", "payload": entry})
        self.publish_event("status", {"type": "memory_reflection_saved", "payload": entry})
        return entry

    def _build_reflection_context_for_goal(self, goal: str, limit: int = 4) -> str:
        payload = self._read_memory_payload()
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        reflections = self._reflection_lessons(lessons)
        if not reflections:
            return ""

        goal_tokens = set(self._tokenize_text(goal))
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in reflections:
            tags = row.get("tags", [])
            tag_text = " ".join(str(item) for item in tags if str(item).strip()) if isinstance(tags, list) else ""
            text = f"{row.get('lesson', '')} {row.get('goal', '')} {row.get('context', '')} {tag_text}"
            tokens = set(self._tokenize_text(text))
            score = len(goal_tokens & tokens)
            scored.append((score, row))

        if any(score > 0 for score, _ in scored):
            scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (item[0], str(item[1].get("timestamp_utc", ""))), reverse=True)
        selected = [row for _, row in scored[: max(1, min(limit, 12))]]
        if not selected:
            return ""

        lines: list[str] = ["Reflection memory before planning:"]
        for row in selected:
            lesson_text = str(row.get("lesson", "")).strip()
            if not lesson_text:
                continue
            stamp = str(row.get("timestamp_utc", "")).strip() or "unknown-time"
            lines.append(f"- [{stamp}] {lesson_text}")
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    def _goal_lessons_summary(self, goal: str, limit: int = 3) -> list[str]:
        payload = self._read_memory_payload()
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        snippets: list[str] = []
        seen: set[str] = set()
        for row in reversed(lessons):
            if not isinstance(row, dict) or self._is_reflection_lesson(row):
                continue
            if str(row.get("goal", "")).strip() != goal.strip():
                continue
            text = str(row.get("lesson", "")).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(text)
            if len(snippets) >= max(1, min(limit, 8)):
                break
        return snippets

    def _compose_growth_reference_line(self) -> str:
        payload = self._read_memory_payload()
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        latest = self._latest_reflection_lesson(lessons)
        if not latest:
            return "I have been improving gradually by learning from each run and conversation."
        lesson_text = str(latest.get("lesson", "")).strip()
        if not lesson_text:
            return "I have been improving gradually by learning from each run and conversation."
        clipped = lesson_text[:180]
        return f"Earlier, I struggled with parts of this work, but I learned from that: {clipped}"

    def _longest_iteration_for_run(self, run_id: str) -> tuple[int, float]:
        run_dir = self._run_dir(run_id) / "iterations"
        if not run_dir.exists():
            return 0, 0.0

        longest_iteration = 0
        longest_duration = 0.0
        for iter_dir in sorted(run_dir.iterdir()):
            if not iter_dir.is_dir():
                continue
            try:
                iteration = int(iter_dir.name)
            except ValueError:
                continue
            rows = self._read_json(iter_dir / "execution.json", default=[])
            if not isinstance(rows, list):
                continue
            total_duration = 0.0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    total_duration += float(row.get("duration_sec", 0.0))
                except (TypeError, ValueError):
                    continue
            if total_duration > longest_duration:
                longest_duration = total_duration
                longest_iteration = iteration
        return longest_iteration, round(longest_duration, 3)

    def _record_goal_reflection(
        self,
        *,
        run_id: str,
        goal: str,
        status: str,
        message: str,
        iterations_used: int,
        tests_ran: bool,
        tests_passed: bool | None,
        tdd_mode: bool,
        iterations_until_green: int | None,
    ) -> dict[str, Any] | None:
        normalized_status = str(status).strip().lower() or "unknown"
        longest_iteration, longest_duration = self._longest_iteration_for_run(run_id)
        learned_lessons = self._goal_lessons_summary(goal, limit=3)

        if normalized_status in {"success", "preview_ready"}:
            outcome = "Run completed successfully."
        elif normalized_status == "stopped":
            outcome = "Run was stopped before completion."
        elif normalized_status == "rejected":
            outcome = "Run was rejected for safety reasons."
        else:
            outcome = "Run ended without success."

        if tests_ran and tests_passed is True:
            test_signal = "Tests passed."
        elif tests_ran and tests_passed is False:
            test_signal = "Tests failed, likely due to missing edge cases or implementation gaps."
        else:
            test_signal = "No decisive test signal was captured."

        longest_signal = (
            f"Longest iteration was #{longest_iteration} at ~{longest_duration:.2f}s."
            if longest_iteration > 0
            else "No command timing data was available."
        )

        lessons_signal = (
            f"Learned lessons: {'; '.join(learned_lessons)}."
            if learned_lessons
            else "No new explicit lessons were captured for this goal."
        )

        summary = f"{outcome} {test_signal} {longest_signal}"
        context_lines = [
            f"status={normalized_status}",
            f"run_id={run_id}",
            f"iterations_used={max(0, int(iterations_used))}",
            f"tdd_mode={bool(tdd_mode)}",
            f"iterations_until_green={iterations_until_green if iterations_until_green is not None else '-'}",
            f"message={str(message).strip()[:300]}",
            lessons_signal,
        ]

        return self._append_reflection_lesson(
            goal=goal,
            lesson=summary.strip(),
            context=" | ".join(context_lines),
            tags=["reflection", "run", normalized_status],
            reflection_key=f"run:{run_id}",
            metadata={"run_id": run_id, "status": normalized_status},
        )

    def _is_meaningful_conversation(self, message: str, selected_intent: str, response: dict[str, Any]) -> bool:
        intent = str(selected_intent).strip().lower()
        if intent in {"ask", "teach", "goal"}:
            return True
        if self._is_family_context(message) or self._is_grief_context(message) or self._is_crisis_context(message):
            return True
        lowered = str(message).casefold()
        if any(
            marker in lowered
            for marker in ("step-by-step", "step by step", "detailed", "concise", "brief", "more detail")
        ):
            return True
        if len(self._tokenize_text(message)) >= 12:
            return True
        citations = response.get("citations", [])
        return isinstance(citations, list) and bool(citations)

    def _record_conversation_reflection(
        self,
        *,
        message: str,
        selected_intent: str,
        response: dict[str, Any],
        session_id: str,
        user_message_id: str,
    ) -> dict[str, Any] | None:
        if not self._is_meaningful_conversation(message, selected_intent, response):
            return None

        intent = str(selected_intent).strip().lower() or "chat"
        lowered = str(message).casefold()
        tags = ["reflection", "conversation", intent]
        if "step-by-step" in lowered or "step by step" in lowered:
            summary = "User prefers step-by-step explanations for better clarity."
            tags.append("preference")
        elif any(marker in lowered for marker in ("concise", "brief")):
            summary = "User prefers concise responses in this context."
            tags.append("preference")
        elif "detailed" in lowered or "more detail" in lowered:
            summary = "User prefers detailed explanations when learning."
            tags.append("preference")
        elif intent == "teach":
            status = str(response.get("status", "")).strip().lower()
            stored_count = int(response.get("stored_count", 0) or 0)
            if status == "stored" and stored_count > 0:
                summary = f"Teach flow stored {stored_count} new memory facts after confirmation."
            elif status == "overwrite_confirmation_required":
                summary = "Teach flow surfaced a memory conflict requiring overwrite confirmation."
            else:
                summary = "Teach flow reviewed memory updates and deduplication behavior."
        elif intent == "ask":
            citations = response.get("citations", [])
            citation_count = len(citations) if isinstance(citations, list) else 0
            if citation_count:
                summary = f"Ask flow answered with memory evidence using {citation_count} citations."
            else:
                summary = "Ask flow had limited memory evidence and returned a low-confidence answer."
        elif intent == "goal":
            status = str(response.get("status", "")).strip().lower()
            summary = (
                "Conversation successfully converted into a queued goal run."
                if status == "queued"
                else "Conversation goal request could not be queued and needs clearer constraints."
            )
        elif self._is_grief_context(message) or self._is_crisis_context(message):
            summary = "Sensitive emotional context was handled with supportive language and transparency."
            tags.append("support")
        else:
            summary = "Meaningful conversation added a reusable interaction pattern."

        context = (
            f"session_id={session_id} | message={str(message).strip()[:260]} | "
            f"response_status={str(response.get('status', '')).strip()} | intent={intent}"
        )
        return self._append_reflection_lesson(
            goal=f"conversation:{session_id or 'unknown'}",
            lesson=summary,
            context=context,
            tags=tags,
            reflection_key=f"conversation:{user_message_id}",
            metadata={"session_id": session_id, "message_id": user_message_id},
        )

    @staticmethod
    def _normalize_teaching_category(value: str) -> str:
        text = str(value or "").strip().lower().replace(" ", "_")
        if text in {"value", "values"}:
            return "value"
        if text in {"guideline", "guidelines", "principle", "principles"}:
            return "guideline"
        if text in {"personal_philosophy", "philosophy", "philosophies"}:
            return "personal_philosophy"
        return "value"

    @staticmethod
    def _teaching_category_label(category: str) -> str:
        normalized = str(category or "").strip().lower()
        if normalized == "guideline":
            return "Guidelines"
        if normalized == "personal_philosophy":
            return "Personal Philosophy"
        return "Values"

    def _classify_parent_teaching_category(self, message: str) -> str:
        lowered = str(message or "").casefold()
        if any(token in lowered for token in ("always", "never", "should", "must", "rule", "guideline")):
            return "guideline"
        if any(token in lowered for token in ("philosophy", "i believe", "worldview", "principle of life")):
            return "personal_philosophy"
        return "value"

    def _extract_parent_teaching_principle(self, message: str) -> str:
        text = str(message or "").strip()
        if not text:
            return "this principle"
        lower = text.casefold()
        if "always value " in lower:
            idx = lower.find("always value ")
            principle = text[idx + len("always value ") :].strip(" .")
            if principle:
                return principle
        prefixes = ("value:", "guideline:", "philosophy:", "principle:")
        for prefix in prefixes:
            if lower.startswith(prefix):
                principle = text[len(prefix) :].strip(" .")
                if principle:
                    return principle
        return text.strip(" .")[:140] or "this principle"

    def _build_parent_teaching_question(self, category: str, principle: str) -> str:
        category_label = self._teaching_category_label(category)
        topic = str(principle or "this principle").strip()[:120]
        return (
            f"Thank you for teaching this {category_label.lower()} idea. "
            f"How should I apply '{topic}' when planning or debugging?"
        )

    def _store_parent_teaching_value(
        self,
        *,
        category: str,
        principle: str,
        application: str,
        actor: str,
        session_id: str,
        source_message: str,
    ) -> dict[str, Any]:
        payload = self._read_memory_payload()
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        normalized_category = self._normalize_teaching_category(category)
        normalized_principle = str(principle or "").strip()[:220]
        normalized_application = str(application or "").strip()[:600]
        now = self._now_iso()
        entry = {
            "id": uuid.uuid4().hex,
            "timestamp_utc": now,
            "category": normalized_category,
            "category_label": self._teaching_category_label(normalized_category),
            "principle": normalized_principle,
            "application": normalized_application,
            "source": "parent_teaching_mode",
            "actor": actor,
            "session_id": session_id,
            "message": str(source_message or "").strip()[:400],
            "tags": ["parent_teaching", normalized_category],
        }
        values.append(entry)
        payload["values"] = values[-2000:]
        self._write_memory_payload(payload)
        self.publish_event("status", {"type": "memory_value_stored", "payload": entry})
        self.publish_event("logs", {"type": "memory_value_stored", "payload": entry})
        return entry

    def _handle_parent_teaching_turn(
        self,
        *,
        message: str,
        actor: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        clean_session = self._sanitize_session_id(session_id)
        if not clean_session:
            return None

        pending = self._pending_parent_teaching.get(clean_session)
        if pending:
            stored = self._store_parent_teaching_value(
                category=str(pending.get("category", "value")),
                principle=str(pending.get("principle", "this principle")),
                application=str(message),
                actor=actor,
                session_id=clean_session,
                source_message=str(pending.get("message", "")),
            )
            self._pending_parent_teaching.pop(clean_session, None)
            return {
                "mode": "teach",
                "status": "stored",
                "parent_teaching_mode": True,
                "parent_teaching_stage": "completed",
                "stored_values": [stored],
                "stored_value_count": 1,
                "category": stored.get("category", "value"),
                "category_label": stored.get("category_label", "Values"),
                "principle": stored.get("principle", ""),
                "application": stored.get("application", ""),
                "session_id": clean_session,
                "actor": actor,
                "timestamp_utc": self._now_iso(),
            }

        category = self._classify_parent_teaching_category(message)
        principle = self._extract_parent_teaching_principle(message)
        question = self._build_parent_teaching_question(category, principle)
        pending_payload = {
            "category": category,
            "principle": principle,
            "question": question,
            "message": str(message),
            "actor": actor,
            "session_id": clean_session,
            "created_at": self._now_iso(),
        }
        self._pending_parent_teaching[clean_session] = pending_payload
        return {
            "mode": "teach",
            "status": "parent_teaching_clarify_required",
            "parent_teaching_mode": True,
            "parent_teaching_stage": "clarifying",
            "requires_clarification": True,
            "category": category,
            "category_label": self._teaching_category_label(category),
            "principle": principle,
            "question": question,
            "message": str(message),
            "session_id": clean_session,
            "actor": actor,
            "timestamp_utc": self._now_iso(),
        }

    def _match_values_for_question(
        self,
        question_tokens: set[str],
        values: list[dict[str, Any]],
        *,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        if not question_tokens:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in values:
            if not isinstance(row, dict):
                continue
            text = (
                f"{row.get('category', '')} {row.get('category_label', '')} "
                f"{row.get('principle', '')} {row.get('application', '')} {row.get('message', '')}"
            )
            tokens = set(self._tokenize_text(text))
            score = len(question_tokens & tokens)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("timestamp_utc", ""))), reverse=True)
        return [row for _, row in scored[: max(1, min(limit, 50))]]

    def _build_values_context_for_goal(self, goal: str, limit: int = 4) -> str:
        payload = self._read_memory_payload()
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        if not values:
            return ""
        goal_tokens = set(self._tokenize_text(goal))
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in values:
            if not isinstance(row, dict):
                continue
            text = f"{row.get('principle', '')} {row.get('application', '')} {row.get('category_label', '')}"
            tokens = set(self._tokenize_text(text))
            score = len(goal_tokens & tokens)
            scored.append((score, row))
        if any(score > 0 for score, _ in scored):
            scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (item[0], str(item[1].get("timestamp_utc", ""))), reverse=True)
        selected = [row for _, row in scored[: max(1, min(limit, 12))]]
        if not selected:
            return ""

        lines: list[str] = ["Parent teachings (Values / Guidelines / Personal Philosophy):"]
        for row in selected:
            principle = str(row.get("principle", "")).strip()
            if not principle:
                continue
            category_label = str(row.get("category_label", self._teaching_category_label(str(row.get("category", ""))))).strip()
            application = str(row.get("application", "")).strip()
            if application:
                lines.append(f"- ({category_label}) {principle} -> {application}")
            else:
                lines.append(f"- ({category_label}) {principle}")
        lines.append("These teachings guide tone and planning style only; never override safety constraints.")
        return "\n".join(lines).strip()

    def _workspace_relative_path(self, path_value: str | Path) -> str:
        text = str(path_value or "").strip()
        if not text:
            return ""
        workspace_root = self.config.workspace_dir.resolve()
        try:
            candidate = Path(text)
            if not candidate.is_absolute():
                candidate = workspace_root / candidate
            resolved = candidate.resolve()
            if resolved == workspace_root:
                return ""
            relative = resolved.relative_to(workspace_root).as_posix().strip("/")
            return relative
        except Exception:
            return ""

    @staticmethod
    def _is_workspace_project_relative(relative_path: str) -> bool:
        clean = str(relative_path or "").strip().replace("\\", "/").strip("/")
        return clean.startswith("projects/") and len(clean) > len("projects/")

    @staticmethod
    def _contains_project_query_signal(message: str) -> bool:
        lowered = str(message or "").casefold()
        return any(
            token in lowered
            for token in (
                "project",
                "architecture",
                "design",
                "testing",
                "weakness",
                "workspace",
                "projects/",
            )
        )

    def _match_projects_for_query(
        self,
        query_tokens: set[str],
        projects: list[dict[str, Any]],
        *,
        query_text: str,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        if not projects:
            return []
        clean_query = str(query_text or "").casefold()
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in projects:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("project_slug", "")).strip()
            relative_path = str(row.get("project_relative_path", "")).strip()
            weakness_text = " ".join(str(item) for item in row.get("known_weaknesses", []) if str(item).strip())
            decision_text = " ".join(str(item) for item in row.get("key_design_decisions", []) if str(item).strip())
            blob = (
                f"{slug} {relative_path} {row.get('architecture_summary', '')} "
                f"{row.get('testing_approach', '')} {weakness_text} {decision_text}"
            )
            tokens = set(self._tokenize_text(blob))
            score = len(query_tokens & tokens)
            if slug and slug.casefold() in clean_query:
                score += 3
            if relative_path and relative_path.casefold() in clean_query:
                score += 4
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("last_updated", ""))), reverse=True)
        if scored:
            return [row for _, row in scored[: max(1, min(limit, 8))]]
        if ({"project", "architecture", "workspace"} & query_tokens) and len(projects) == 1:
            return [projects[0]]
        return []

    @staticmethod
    def _compose_project_brain_overview_line(entry: dict[str, Any]) -> str:
        slug = str(entry.get("project_slug", "")).strip() or str(entry.get("project_relative_path", "")).strip() or "project"
        architecture = str(entry.get("architecture_summary", "")).strip() or "a modular project structure"
        testing = str(entry.get("testing_approach", "")).strip() or "tests need more explicit automation"
        weaknesses = entry.get("known_weaknesses", [])
        weakness = ""
        if isinstance(weaknesses, list):
            weakness = next((str(item).strip() for item in weaknesses if str(item).strip()), "")
        if not weakness:
            weakness = "edge-case validation needs continued improvement"

        architecture_sentence = (
            architecture
            if architecture.casefold().startswith("this project uses")
            else f"This project uses {architecture.rstrip('.')}."
        )
        return (
            f"Project `{slug}` overview: {architecture_sentence} "
            f"Testing approach: {testing.rstrip('.')}. "
            f"Last time, {weakness.rstrip('.')}."
        ).strip()

    def _build_project_brain_context_for_goal(
        self,
        goal: str,
        *,
        project_slug: str,
        project_path: str,
    ) -> str:
        payload = self._read_memory_payload()
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        if not projects:
            return ""

        selected: dict[str, Any] | None = None
        project_relative = self._workspace_relative_path(project_path)
        if project_relative:
            for row in projects:
                if not isinstance(row, dict):
                    continue
                if str(row.get("project_relative_path", "")).casefold() == project_relative.casefold():
                    selected = row
                    break
        if selected is None and project_slug:
            for row in projects:
                if not isinstance(row, dict):
                    continue
                if str(row.get("project_slug", "")).casefold() == project_slug.casefold():
                    selected = row
                    break
        if selected is None:
            tokens = set(self._tokenize_text(goal))
            matches = self._match_projects_for_query(tokens, projects, query_text=goal, limit=1)
            if matches:
                selected = matches[0]
        if selected is None:
            return ""

        weaknesses = selected.get("known_weaknesses", [])
        weakness_line = ""
        if isinstance(weaknesses, list):
            weakness_line = next((str(item).strip() for item in weaknesses if str(item).strip()), "")
        if not weakness_line:
            weakness_line = "No major weaknesses recorded yet."
        lines = [
            "Project Brain recall:",
            f"- Project: {selected.get('project_slug', 'project')} ({selected.get('project_relative_path', '-')})",
            f"- Architecture: {selected.get('architecture_summary', '-')}",
            f"- Testing approach: {selected.get('testing_approach', '-')}",
            f"- Known weakness: {weakness_line}",
            "Reuse this context so work continues without relearning from scratch, while keeping scope within this project.",
        ]
        return "\n".join(lines).strip()

    @staticmethod
    def _summarize_project_architecture(project_files: list[dict[str, Any]]) -> str:
        paths = [str(item.get("path", "")).strip() for item in project_files if isinstance(item, dict)]
        paths = [path for path in paths if path]
        if not paths:
            return "a lightweight structure that still needs architectural expansion"
        top_dirs = sorted({path.split("/", 1)[0] for path in paths if "/" in path})
        has_src = any(path.startswith("src/") for path in paths)
        has_tests = any(path.startswith("tests/") or "/test_" in path or path.startswith("test_") for path in paths)
        has_cli = any(path.endswith(("cli.py", "main.py", "__main__.py")) for path in paths)
        has_json = any(path.endswith(".json") for path in paths)
        has_sqlite = any(path.endswith((".db", ".sqlite", ".sqlite3")) or "sqlite" in path.casefold() for path in paths)

        if has_cli and has_src:
            base = "modular CLI structure"
        elif has_src:
            base = "modular source-package structure"
        elif has_cli:
            base = "CLI-oriented script structure"
        elif len(top_dirs) >= 2:
            base = f"layered structure across {', '.join(top_dirs[:3])}"
        else:
            base = "compact single-module structure"

        if has_json and has_sqlite:
            base = f"{base} with mixed JSON and SQLite storage"
        elif has_json:
            base = f"{base} with JSON storage"
        elif has_sqlite:
            base = f"{base} with SQLite storage"
        if has_tests:
            base = f"{base} and dedicated tests"
        return base

    @staticmethod
    def _summarize_project_testing_approach(
        project_files: list[dict[str, Any]],
        executed_commands: list[str],
        *,
        tdd_mode: bool,
    ) -> str:
        has_test_files = any(
            str(item.get("path", "")).startswith("tests/") or "/test_" in str(item.get("path", ""))
            for item in project_files
            if isinstance(item, dict)
        )
        has_pytest_cmd = any(
            str(command).strip().lower().startswith("pytest")
            or str(command).strip().lower().startswith("python -m pytest")
            for command in executed_commands
        )
        if tdd_mode and has_pytest_cmd:
            return "Strict TDD with pytest red/green iterations."
        if has_pytest_cmd or has_test_files:
            return "Pytest tests under tests/ with iterative command validation."
        return "Testing is lightweight; expand automated pytest coverage."

    @staticmethod
    def _summarize_project_design_decisions(
        plan_payload: dict[str, Any],
        meta: dict[str, Any],
        executed_commands: list[str],
    ) -> list[str]:
        decisions: list[str] = []
        steps = plan_payload.get("steps", []) if isinstance(plan_payload, dict) else []
        if isinstance(steps, list):
            for step in steps[:3]:
                if not isinstance(step, dict):
                    continue
                title = str(step.get("title", "")).strip() or str(step.get("details", "")).strip()
                if title:
                    decisions.append(f"Planned around: {title}.")
        workspace_target = str(meta.get("workspace_target_path", "")).strip()
        if workspace_target:
            decisions.append(f"Kept edits focused on workspace target `{workspace_target}`.")
        if bool(meta.get("tdd_mode", False)):
            decisions.append("Used strict TDD sequencing before implementation changes.")
        if any("pytest" in str(command).casefold() for command in executed_commands):
            decisions.append("Validated implementation through iterative pytest feedback loops.")
        if not decisions:
            decisions.append("Kept project boundaries isolated under workspace/projects for clean continuity.")
        deduped: list[str] = []
        seen: set[str] = set()
        for item in decisions:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:6]

    def _summarize_project_weaknesses(
        self,
        *,
        run_id: str,
        meta: dict[str, Any],
        result_payload: dict[str, Any],
    ) -> list[str]:
        weaknesses: list[str] = []
        status = str(meta.get("status", "")).strip().casefold()
        message = str(meta.get("message", "")).strip()
        if status in {"failed", "rejected", "stopped"} and message:
            weaknesses.append(message)
        if isinstance(result_payload, dict):
            failure = result_payload.get("failure_details", {})
            if isinstance(failure, dict):
                top_errors = failure.get("top_errors", [])
                if isinstance(top_errors, list):
                    for row in top_errors[:2]:
                        text = str(row).strip()
                        if text:
                            weaknesses.append(text)
        payload = self._read_memory_payload()
        lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        for row in reversed(lessons):
            if not isinstance(row, dict):
                continue
            if str(row.get("run_id", "")).strip() != run_id:
                continue
            lesson_text = str(row.get("lesson", "")).strip()
            if not lesson_text:
                continue
            lowered = lesson_text.casefold()
            if any(token in lowered for token in ("edge case", "validation", "coverage", "flaky", "timeout", "failure")):
                weaknesses.append(lesson_text)
                break
        if not weaknesses:
            if status in {"success", "preview_ready"}:
                weaknesses.append("edge-case validation needs continued improvement")
            else:
                weaknesses.append("stability and validation need another focused iteration")

        deduped: list[str] = []
        seen: set[str] = set()
        for item in weaknesses:
            clean = str(item).strip().strip(".")
            if not clean:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(f"{clean}.")
        return deduped[:4]

    def _upsert_project_brain_from_run(self, run_id: str) -> None:
        meta = self._read_run_meta(run_id) or {}
        if str(meta.get("mode", "")).strip().casefold() != "goal":
            return
        project_path = str(meta.get("project_path", "")).strip()
        project_slug = str(meta.get("project_slug", "")).strip()
        project_relative = self._workspace_relative_path(project_path)
        if not self._is_workspace_project_relative(project_relative):
            return
        try:
            project_dir = self._resolve_goal_project_path(project_path)
        except ValueError:
            return

        run_dir = self._run_dir(run_id)
        plan_payload = self._read_json(run_dir / "plan.json", default={})
        result_payload = self._read_json(run_dir / "result.json", default={})
        project_files = self._list_project_files(project_dir, limit=600)
        executed_commands: list[str] = []
        iterations_dir = run_dir / "iterations"
        if iterations_dir.exists():
            for item in sorted(iterations_dir.iterdir()):
                if not item.is_dir():
                    continue
                rows = self._read_json(item / "execution.json", default=[])
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    command = str(row.get("command", "")).strip()
                    if command:
                        executed_commands.append(command)

        architecture_summary = self._summarize_project_architecture(project_files)
        testing_approach = self._summarize_project_testing_approach(
            project_files,
            executed_commands,
            tdd_mode=bool(meta.get("tdd_mode", False)),
        )
        key_decisions = self._summarize_project_design_decisions(plan_payload, meta, executed_commands)
        known_weaknesses = self._summarize_project_weaknesses(
            run_id=run_id,
            meta=meta,
            result_payload=result_payload if isinstance(result_payload, dict) else {},
        )

        now = self._now_iso()
        goal_text = str(meta.get("payload", "")).strip()
        status_text = str(meta.get("status", "")).strip().lower()
        message_text = str(meta.get("message", "")).strip()
        entry_payload = {
            "project_slug": project_slug or Path(project_relative).name,
            "project_path": str(project_dir),
            "project_relative_path": project_relative,
            "architecture_summary": architecture_summary,
            "key_design_decisions": key_decisions,
            "testing_approach": testing_approach,
            "known_weaknesses": known_weaknesses,
            "last_goal": goal_text,
            "last_run_id": run_id,
            "last_status": status_text,
            "last_message": message_text,
            "last_updated": now,
            "source": PROJECT_BRAIN_SOURCE,
        }
        history_entry = {
            "timestamp_utc": now,
            "run_id": run_id,
            "status": status_text,
            "goal": goal_text,
            "message": message_text,
            "known_weaknesses": known_weaknesses[:2],
        }

        payload = self._read_memory_payload()
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        target_index = -1
        for idx, row in enumerate(projects):
            if not isinstance(row, dict):
                continue
            if str(row.get("project_relative_path", "")).casefold() == project_relative.casefold():
                target_index = idx
                break

        if target_index >= 0:
            current = projects[target_index] if isinstance(projects[target_index], dict) else {}
            history = current.get("history", [])
            history_rows = history if isinstance(history, list) else []
            history_rows.append(history_entry)
            updated = {
                **current,
                **entry_payload,
                "id": str(current.get("id", "")).strip() or uuid.uuid4().hex,
                "created_at": str(current.get("created_at", "")).strip() or now,
                "history": history_rows[-120:],
            }
            projects[target_index] = updated
            saved_entry = updated
        else:
            saved_entry = {
                "id": uuid.uuid4().hex,
                "created_at": now,
                **entry_payload,
                "history": [history_entry],
            }
            projects.append(saved_entry)

        payload["projects"] = projects[-800:]
        self._write_memory_payload(payload)
        self.publish_event("status", {"type": "memory_project_brain_saved", "payload": saved_entry})
        self.publish_event("logs", {"type": "memory_project_brain_saved", "payload": saved_entry})

    @staticmethod
    def _normalize_fact_row(subject: str, predicate: str, object_value: str) -> dict[str, str] | None:
        sub = str(subject).strip()
        pred = re.sub(r"[^a-zA-Z0-9_]+", "_", str(predicate).strip().lower()).strip("_")
        obj = str(object_value).strip()
        if not sub or not pred or not obj:
            return None
        return {"subject": sub, "predicate": pred, "object": obj}

    @staticmethod
    def _companion_teach_heuristics(message: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        subject = "User"

        birthday_patterns = (
            r"\bmy birthday is\s+([a-z0-9][a-z0-9,/'\- ]{1,80})",
            r"\bmy birth date is\s+([a-z0-9][a-z0-9,/'\- ]{1,80})",
            r"\bmy birthdate is\s+([a-z0-9][a-z0-9,/'\- ]{1,80})",
        )
        for pattern in birthday_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                birthday_value = match.group(1).strip(" .")
                if birthday_value:
                    rows.append({"subject": subject, "predicate": "birthday", "object": birthday_value})
                break

        saying_patterns = (
            r"\bmy favorite saying is\s+[\"'“”]?([^\"'“”\n]{2,160})",
            r"\bmy favorite quote is\s+[\"'“”]?([^\"'“”\n]{2,160})",
            r"\bremember this saying[: ]+[\"'“”]?([^\"'“”\n]{2,160})",
        )
        for pattern in saying_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                saying = match.group(1).strip(" .")
                if saying:
                    rows.append({"subject": subject, "predicate": "favorite_saying", "object": saying})
                break

        goal_patterns = (
            r"\bour shared goal is\s+([^\n.!?]{3,180})",
            r"\bshared goal[: ]+([^\n.!?]{3,180})",
        )
        for pattern in goal_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                goal_value = match.group(1).strip(" .")
                if goal_value:
                    rows.append({"subject": subject, "predicate": "shared_goal", "object": goal_value})
                break

        routine_patterns = (
            r"\bour shared routine is\s+([^\n.!?]{3,180})",
            r"\bour routine is\s+([^\n.!?]{3,180})",
            r"\bshared routine[: ]+([^\n.!?]{3,180})",
        )
        for pattern in routine_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                routine_value = match.group(1).strip(" .")
                if routine_value:
                    rows.append({"subject": subject, "predicate": "shared_routine", "object": routine_value})
                break

        return rows

    def _extract_teach_memory(self, message: str) -> dict[str, Any]:
        llm = OllamaClient(self.config)
        memory = LongTermMemory(self.config.memory_file)
        teacher = MemoryTeacherQA(llm=llm, memory=memory)

        parsed: dict[str, Any] = {"facts": [], "notes": ""}
        try:
            parsed = teacher._extract_facts(message)  # type: ignore[attr-defined]
        except Exception:
            parsed = {"facts": [], "notes": ""}
        heuristic = teacher._heuristic_facts(message)  # type: ignore[attr-defined]
        companion_heuristic = self._companion_teach_heuristics(message)
        rows = teacher._merge_fact_rows(  # type: ignore[attr-defined]
            parsed.get("facts", []),
            heuristic + companion_heuristic,
        )

        triples: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_fact_row(row.get("subject", ""), row.get("predicate", ""), row.get("object", ""))
            if not normalized:
                continue
            key = (
                normalized["subject"].casefold(),
                normalized["predicate"].casefold(),
                normalized["object"].casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            triples.append(normalized)

        alias_rows: list[dict[str, str]] = []
        name_match = re.search(r"\bmy name is\s+([a-z][a-z .'-]{1,80})", message, flags=re.IGNORECASE)
        alias_match = re.search(r"\b(?:also called|aka|also known as)\s+([a-z][a-z .'-]{1,80})", message, flags=re.IGNORECASE)
        if name_match and alias_match:
            canonical = name_match.group(1).strip(" .")
            alias = alias_match.group(1).strip(" .")
            if canonical and alias and canonical.casefold() != alias.casefold():
                alias_rows.append({"canonical": canonical, "alias": alias})

        notes = str(parsed.get("notes", "")).strip()
        if (
            self.settings.companion_mode
            and self._is_grief_context(message)
            and not self._has_explicit_grief_memory_confirmation(message)
        ):
            triples = []
            guard_note = (
                "Grief-heavy message kept as conversation summary by default; "
                "no permanent facts stored without explicit memory confirmation."
            )
            notes = f"{notes} {guard_note}".strip()
        return {
            "triples": triples,
            "notes": notes,
            "aliases": alias_rows,
            "topics": self._extract_topics(message),
        }

    def _teach_confirmed(
        self,
        message: str,
        *,
        actor: str,
        session_id: str,
        allow_overwrite: bool,
        legacy_mode: bool,
    ) -> dict[str, Any]:
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. /teach is blocked in read-only mode.")
        if self._contains_sensitive_memory_text(message):
            raise ValueError("Sensitive data cannot be stored in memory.")
        extracted = self._extract_teach_memory(message)
        return self._apply_teach_extract(
            extracted=extracted,
            message=message,
            actor=actor,
            session_id=session_id,
            allow_overwrite=allow_overwrite,
            overwrite_id="",
            legacy_mode=legacy_mode,
        )

    def _apply_teach_extract(
        self,
        *,
        extracted: dict[str, Any],
        message: str,
        actor: str,
        session_id: str,
        allow_overwrite: bool,
        overwrite_id: str,
        legacy_mode: bool,
    ) -> dict[str, Any]:
        triples = extracted.get("triples", []) if isinstance(extracted.get("triples"), list) else []
        notes = str(extracted.get("notes", "")).strip()
        aliases = extracted.get("aliases", []) if isinstance(extracted.get("aliases"), list) else []
        topics = extracted.get("topics", []) if isinstance(extracted.get("topics"), list) else []

        payload = self._read_memory_payload()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        facts_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in facts:
            if not isinstance(row, dict):
                continue
            subject = str(row.get("subject", "")).strip()
            predicate = str(row.get("predicate", "")).strip()
            if not subject or not predicate:
                continue
            facts_by_key.setdefault((subject.casefold(), predicate.casefold()), []).append(row)

        deduped: list[dict[str, str]] = []
        duplicates: list[dict[str, str]] = []
        conflicts: list[dict[str, Any]] = []
        for triple in triples:
            if not isinstance(triple, dict):
                continue
            normalized = self._normalize_fact_row(triple.get("subject", ""), triple.get("predicate", ""), triple.get("object", ""))
            if not normalized:
                continue
            key = (normalized["subject"].casefold(), normalized["predicate"].casefold())
            current_rows = facts_by_key.get(key, [])
            exact_match = False
            conflicting_values: list[str] = []
            for existing in current_rows:
                existing_obj = str(existing.get("object", "")).strip()
                if not existing_obj:
                    continue
                if existing_obj.casefold() == normalized["object"].casefold():
                    exact_match = True
                    break
                similarity = difflib.SequenceMatcher(None, existing_obj.casefold(), normalized["object"].casefold()).ratio()
                if similarity >= 0.94:
                    exact_match = True
                    break
                conflicting_values.append(existing_obj)
            if exact_match:
                duplicates.append(normalized)
                continue
            if conflicting_values:
                conflicts.append(
                    {
                        "subject": normalized["subject"],
                        "predicate": normalized["predicate"],
                        "existing_values": sorted(set(conflicting_values)),
                        "incoming": normalized["object"],
                    }
                )
            deduped.append(normalized)

        if conflicts and not allow_overwrite:
            pending_id = overwrite_id or f"ow_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
            with self._lock:
                self._pending_memory_overwrites[pending_id] = {
                    "id": pending_id,
                    "status": "pending",
                    "message": message,
                    "actor": actor,
                    "session_id": session_id,
                    "created_at": self._now_iso(),
                    "conflicts": conflicts,
                    "extracted": extracted,
                }
            return {
                "mode": "teach",
                "status": "overwrite_confirmation_required",
                "message": message,
                "requires_overwrite_confirmation": True,
                "overwrite_id": pending_id,
                "stored_facts": [],
                "stored_count": 0,
                "deduplicated_count": len(duplicates),
                "skipped_items": [],
                "conflicts": conflicts,
                "notes": notes or "Conflict detected. Confirm overwrite to continue.",
                "aliases": aliases,
                "topics": topics,
                "session_id": session_id,
                "actor": actor,
                "timestamp_utc": self._now_iso(),
            }

        overwrite_keys = {(item["subject"].casefold(), item["predicate"].casefold()) for item in deduped}
        if conflicts and allow_overwrite and overwrite_keys:
            facts = [
                row
                for row in facts
                if not (
                    isinstance(row, dict)
                    and (str(row.get("subject", "")).casefold(), str(row.get("predicate", "")).casefold()) in overwrite_keys
                )
            ]

        now = self._now_iso()
        stored_facts: list[dict[str, Any]] = []
        alias_values = [str(item.get("alias", "")).strip() for item in aliases if isinstance(item, dict)]
        alias_values = [item for item in alias_values if item]
        for triple in deduped:
            stored = {
                "id": uuid.uuid4().hex,
                "subject": triple["subject"],
                "predicate": triple["predicate"],
                "object": triple["object"],
                "source": "user",
                "confidence": 1.0,
                "timestamp": now,
                "last_updated": now,
                "notes": notes,
                "aliases": alias_values,
                "session_id": session_id,
                "provenance": {"source": "user", "actor": actor, "last_updated": now},
            }
            facts.append(stored)
            stored_facts.append(stored)

        max_entries = 2000
        payload["facts"] = facts[-max_entries:]
        self._write_memory_payload(payload)

        return {
            "mode": "teach",
            "status": "stored",
            "message": message,
            "requires_confirmation": False,
            "requires_overwrite_confirmation": False,
            "overwrite_id": overwrite_id,
            "stored_facts": stored_facts,
            "stored_count": len(stored_facts),
            "deduplicated_count": len(duplicates),
            "skipped_items": [],
            "conflicts": conflicts,
            "notes": notes,
            "aliases": aliases,
            "topics": topics,
            "session_id": session_id,
            "actor": actor,
            "timestamp_utc": now,
            "legacy_mode": bool(legacy_mode),
        }

    def _ask_memory_first(
        self,
        question: str,
        *,
        actor: str,
        session_id: str,
        force_transparency: bool = False,
    ) -> dict[str, Any]:
        payload = self._read_memory_payload()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        all_lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        lessons = self._non_reflection_lessons(all_lessons)
        question_tokens = set(self._tokenize_text(question))

        matched_facts = self._match_facts_for_question(question_tokens, facts, limit=8)
        matched_conversations = self._match_conversations_for_question(
            question_tokens,
            session_id=session_id,
            limit=5,
        )
        matched_lessons = self._match_lessons_for_question(question_tokens, lessons, limit=4)
        matched_values = self._match_values_for_question(question_tokens, values, limit=3)
        matched_projects = self._match_projects_for_query(
            question_tokens,
            projects,
            query_text=question,
            limit=2,
        )
        conversation_source = [
            row
            for row in self._read_jsonl(self._conversations_file, limit=20_000)
            if isinstance(row, dict) and str(row.get("role", "")) == "user"
        ]
        personality = self._companion_personality(actor)

        if not self.settings.companion_mode:
            answer = MEMORY_UNKNOWN_ANSWER
            lowered = question.casefold()
            father_fact = None
            for row in matched_facts:
                if (
                    str(row.get("subject", "")).casefold() == "david"
                    and str(row.get("predicate", "")).casefold() == "father_name"
                ):
                    father_fact = row
                    break
            if father_fact:
                answer = f"You told me earlier that David's symbolic father name is {father_fact.get('object', '')}."
            elif matched_projects:
                answer = self._compose_project_brain_overview_line(matched_projects[0])
            elif matched_facts:
                first = matched_facts[0]
                answer = (
                    f"You told me earlier: {first.get('subject', 'unknown')} "
                    f"{str(first.get('predicate', 'fact')).replace('_', ' ')} is {first.get('object', 'unknown')}."
                )
            elif matched_conversations:
                excerpt = str(matched_conversations[0].get("text", "")).strip()
                answer = f"You told me earlier: {excerpt[:220]}"

            if "father" in lowered or "mother" in lowered or "dad" in lowered:
                answer = f"{answer} As software, I treat family labels as symbolic memory facts."

            citations = self._build_memory_citations(
                facts=matched_facts,
                conversations=matched_conversations,
                lessons=[],
                values=matched_values,
                projects=matched_projects,
            )
            memory_insight = self._build_memory_insight(
                enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor)),
                matched_facts=matched_facts,
                matched_conversations=matched_conversations,
                matched_lessons=[],
                facts_source=facts,
                conversations_source=conversation_source,
                lessons_source=[],
            )
            return {
                "mode": "ask",
                "status": "answered",
                "question": question,
                "answer": answer,
                "matched_facts": matched_facts,
                "matched_count": len(matched_facts),
                "matched_conversations": matched_conversations,
                "conversation_match_count": len(matched_conversations),
                "matched_lessons": [],
                "lesson_match_count": 0,
                "matched_values": matched_values,
                "values_match_count": len(matched_values),
                "matched_projects": matched_projects,
                "project_match_count": len(matched_projects),
                "citations": citations,
                "memory_insight": memory_insight,
                "used_memory": {
                    "facts": matched_facts[:5],
                    "conversations": matched_conversations[:3],
                    "values": matched_values[:3],
                    "projects": matched_projects[:2],
                },
                "session_id": session_id,
                "actor": actor,
                "timestamp_utc": self._now_iso(),
            }

        answer = self._compose_companion_ask_answer(
            question=question,
            matched_facts=matched_facts,
            matched_conversations=matched_conversations,
            matched_lessons=matched_lessons,
            matched_values=matched_values,
            matched_projects=matched_projects,
            personality_enabled=bool(personality.get("enabled", False)),
            warmth=int(personality.get("warmth", 55)),
            verbosity=int(personality.get("verbosity", 55)),
            curiosity=int(personality.get("curiosity", 50)),
            force_transparency=force_transparency,
        )
        citations = self._build_memory_citations(
            facts=matched_facts,
            conversations=matched_conversations,
            lessons=matched_lessons,
            values=matched_values,
            projects=matched_projects,
        )
        memory_insight = self._build_memory_insight(
            enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor)),
            matched_facts=matched_facts,
            matched_conversations=matched_conversations,
            matched_lessons=matched_lessons,
            facts_source=facts,
            conversations_source=conversation_source,
            lessons_source=lessons,
        )

        return {
            "mode": "ask",
            "status": "answered",
            "question": question,
            "answer": answer,
            "matched_facts": matched_facts,
            "matched_count": len(matched_facts),
            "matched_conversations": matched_conversations,
            "conversation_match_count": len(matched_conversations),
            "matched_lessons": matched_lessons,
            "lesson_match_count": len(matched_lessons),
            "matched_values": matched_values,
            "values_match_count": len(matched_values),
            "matched_projects": matched_projects,
            "project_match_count": len(matched_projects),
            "citations": citations,
            "memory_insight": memory_insight,
            "used_memory": {
                "facts": matched_facts[:5],
                "conversations": matched_conversations[:3],
                "lessons": matched_lessons[:3],
                "values": matched_values[:3],
                "projects": matched_projects[:2],
            },
            "session_id": session_id,
            "actor": actor,
            "timestamp_utc": self._now_iso(),
        }

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
            if mode == "goal":
                meta = self._read_run_meta(run_id) or {}
                self._record_goal_reflection(
                    run_id=run_id,
                    goal=str(meta.get("payload", payload)),
                    status="failed",
                    message=f"Unhandled exception: {exc}",
                    iterations_used=int(meta.get("iteration", 0) or 0),
                    tests_ran=bool(meta.get("tests_ran", False)),
                    tests_passed=meta.get("tests_passed"),
                    tdd_mode=bool(meta.get("tdd_mode", False)),
                    iterations_until_green=meta.get("iterations_until_green"),
                )
        finally:
            if mode == "goal":
                try:
                    self._upsert_project_brain_from_run(run_id)
                except Exception:  # pragma: no cover - defensive boundary
                    self._logger.exception("project brain update failed run_id=%s", run_id)
                try:
                    self.autonomous_self_improvement_cycle(
                        trigger="goal",
                        trigger_id=run_id,
                        actor="david_autonomous",
                    )
                except Exception:  # pragma: no cover - defensive boundary
                    self._logger.exception("autonomous self-improvement cycle failed run_id=%s", run_id)
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
        base_memory_context = memory.render_context(effective_goal)
        log_context = self._build_goal_log_context()
        reflection_context = self._build_reflection_context_for_goal(effective_goal)
        values_context = self._build_values_context_for_goal(effective_goal)
        project_brain_context = self._build_project_brain_context_for_goal(
            effective_goal,
            project_slug=project_slug,
            project_path=str(project_path),
        )
        memory_context = self._compose_goal_context(
            base_memory_context,
            log_context,
            reflection_context,
            values_context,
            project_brain_context,
        )
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
                "logs_context_included": bool(log_context.strip()),
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
                self._record_goal_reflection(
                    run_id=run_id,
                    goal=effective_goal,
                    status="stopped",
                    message="Run stopped by user.",
                    iterations_used=max(0, iteration - 1),
                    tests_ran=tests_ran,
                    tests_passed=tests_passed,
                    tdd_mode=tdd_mode,
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
            base_memory_context = memory.render_context(effective_goal)
            log_context = self._build_goal_log_context()
            reflection_context = self._build_reflection_context_for_goal(effective_goal)
            values_context = self._build_values_context_for_goal(effective_goal)
            project_brain_context = self._build_project_brain_context_for_goal(
                effective_goal,
                project_slug=project_slug,
                project_path=str(project_path),
            )
            memory_context = self._compose_goal_context(
                base_memory_context,
                log_context,
                reflection_context,
                values_context,
                project_brain_context,
            )
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
                    self._record_goal_reflection(
                        run_id=run_id,
                        goal=effective_goal,
                        status="rejected",
                        message="Risky edit set was rejected.",
                        iterations_used=iteration,
                        tests_ran=tests_ran,
                        tests_passed=tests_passed,
                        tdd_mode=tdd_mode,
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
                self._record_goal_reflection(
                    run_id=run_id,
                    goal=effective_goal,
                    status="preview_ready",
                    message="Preview generated. No files were changed.",
                    iterations_used=iteration,
                    tests_ran=False,
                    tests_passed=None,
                    tdd_mode=tdd_mode,
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
                self._record_goal_reflection(
                    run_id=run_id,
                    goal=effective_goal,
                    status="success",
                    message=critic_output.analysis,
                    iterations_used=iteration,
                    tests_ran=tests_ran,
                    tests_passed=tests_passed,
                    tdd_mode=tdd_mode,
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
                self._record_goal_reflection(
                    run_id=run_id,
                    goal=effective_goal,
                    status="failed",
                    message=critic_output.analysis,
                    iterations_used=iteration,
                    tests_ran=tests_ran,
                    tests_passed=tests_passed,
                    tdd_mode=tdd_mode,
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
        self._record_goal_reflection(
            run_id=run_id,
            goal=effective_goal,
            status="failed",
            message="Iteration limit reached before meeting success criteria.",
            iterations_used=iteration_limit,
            tests_ran=tests_ran,
            tests_passed=tests_passed,
            tdd_mode=tdd_mode,
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
        if self._demo_mode_enabled():
            entries: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()
            workspace_files_total = 0
            workspace_dirs_total = 0
            for run_dir in self._demo_run_dirs():
                summary = self._read_json(run_dir / "file_summary.json", default={})
                if not isinstance(summary, dict):
                    continue
                dirs = summary.get("workspace_dirs", [])
                files = summary.get("workspace_files", [])
                if isinstance(dirs, list):
                    for row in dirs:
                        path = str(row).strip()
                        if not path:
                            continue
                        key = ("folder", path)
                        if key in seen:
                            continue
                        seen.add(key)
                        entries.append({"path": path, "type": "folder"})
                        workspace_dirs_total += 1
                if isinstance(files, list):
                    for row in files:
                        if not isinstance(row, dict):
                            continue
                        path = str(row.get("path", "")).strip()
                        if not path:
                            continue
                        key = ("file", path)
                        if key in seen:
                            continue
                        seen.add(key)
                        entries.append({"path": path, "type": "file"})
                        workspace_files_total += 1
            entries.sort(key=lambda row: (str(row.get("path", "")).count("/"), str(row.get("path", ""))))
            return {
                "workspace_dir": str(self.config.workspace_dir),
                "entries": entries[:max(1, min(limit, 20_000))],
                "file_total": workspace_files_total,
                "dir_total": workspace_dirs_total,
                "truncated": len(entries) > max(1, min(limit, 20_000)),
            }
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

    def _run_dir(self, run_id: str, runs_root: Path | None = None) -> Path:
        return (runs_root or self.runs_root) / run_id

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

    @staticmethod
    def _env_truthy(name: str) -> bool:
        value = os.getenv(name, "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def _demo_mode_env_enabled(self) -> bool:
        return self._env_truthy("DEMO_MODE")

    def _demo_mode_enabled(self) -> bool:
        return self._demo_mode_env_enabled() or bool(self.settings.demo_mode)

    def _demo_fixture_root(self) -> Path:
        candidates = [
            (self.data_root / "mock").resolve(),
            self.mock_data_root,
        ]
        for path in candidates:
            if path.exists() and path.is_dir():
                return path
        return self.mock_data_root

    def _demo_runs_root(self) -> Path:
        return (self._demo_fixture_root() / "mock_runs").resolve()

    def _read_demo_json(self, relative_path: str, default: Any) -> Any:
        path = (self._demo_fixture_root() / relative_path).resolve()
        try:
            fixture_root = self._demo_fixture_root()
        except Exception:
            fixture_root = self.mock_data_root
        if path == fixture_root or fixture_root not in path.parents:
            return default
        return self._read_json(path, default=default)

    def _read_demo_jsonl(self, relative_path: str, limit: int = 5000) -> list[dict[str, Any]]:
        path = (self._demo_fixture_root() / relative_path).resolve()
        try:
            fixture_root = self._demo_fixture_root()
        except Exception:
            fixture_root = self.mock_data_root
        if path == fixture_root or fixture_root not in path.parents:
            return []
        return self._read_jsonl(path, limit=max(1, min(limit, 20_000)))

    @staticmethod
    def _clone_json(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value))
        except (TypeError, ValueError):
            return value

    def _ensure_demo_runtime(self) -> None:
        with self._lock:
            if bool(self._demo_runtime.get("initialized", False)):
                return
            memory_payload = self._read_demo_json(
                "mock_memory_long_term.json",
                default={"facts": [], "lessons": [], "preferences": [], "values": [], "projects": [], "legacy_archive": []},
            )
            if not isinstance(memory_payload, dict):
                memory_payload = {"facts": [], "lessons": [], "preferences": [], "values": [], "projects": [], "legacy_archive": []}
            memory_payload = self._clone_json(memory_payload)
            memory_payload.setdefault("facts", [])
            memory_payload.setdefault("lessons", [])
            memory_payload.setdefault("preferences", [])
            memory_payload.setdefault("values", [])
            memory_payload.setdefault("projects", [])
            memory_payload.setdefault("legacy_archive", [])

            conversations = self._read_demo_jsonl("mock_conversations.jsonl", limit=20_000)
            approvals = self._read_demo_json("mock_approvals.json", default=[])
            if not isinstance(approvals, list):
                approvals = []
            approvals = [row for row in approvals if isinstance(row, dict)]

            self._demo_runtime = {
                "initialized": True,
                "memory_payload": memory_payload,
                "base_conversations": self._clone_json(conversations),
                "conversation_appends": [],
                "pending_overwrites": {},
                "approvals": self._clone_json(approvals),
                "approval_audit_appends": {},
            }

    def _reset_demo_runtime(self) -> None:
        with self._lock:
            self._demo_runtime = {
                "initialized": False,
                "approvals": [],
                "pending_overwrites": {},
                "conversation_appends": [],
                "pending_parent_teaching": {},
                "approval_audit_appends": {},
            }
        self._ensure_demo_runtime()

    def _demo_memory_payload_runtime(self) -> dict[str, Any]:
        self._ensure_demo_runtime()
        with self._lock:
            payload = self._demo_runtime.get("memory_payload", {})
            if isinstance(payload, dict):
                return payload
        return {"facts": [], "lessons": [], "preferences": [], "values": [], "projects": [], "legacy_archive": []}

    def _demo_conversation_rows_runtime(self) -> list[dict[str, Any]]:
        self._ensure_demo_runtime()
        with self._lock:
            base = self._demo_runtime.get("base_conversations", [])
            appends = self._demo_runtime.get("conversation_appends", [])
        rows = []
        if isinstance(base, list):
            rows.extend([row for row in base if isinstance(row, dict)])
        if isinstance(appends, list):
            rows.extend([row for row in appends if isinstance(row, dict)])
        rows.sort(key=lambda row: str(row.get("timestamp_utc", "")))
        return rows

    def _demo_list_approvals_runtime(self) -> list[dict[str, Any]]:
        self._ensure_demo_runtime()
        with self._lock:
            rows = self._demo_runtime.get("approvals", [])
            if not isinstance(rows, list):
                rows = []
            clean = [dict(row) for row in rows if isinstance(row, dict)]
        clean.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return clean

    def _demo_self_improvement_rows(self) -> list[dict[str, Any]]:
        rows = self._read_demo_json("mock_self_improvements.json", default=[])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _demo_typed_confirmation_expected(approval: dict[str, Any]) -> str:
        run_id = str(approval.get("run_id", "")).strip()
        return f"approve {run_id}".strip()

    def _demo_append_conversation_turn(
        self,
        *,
        session_id: str,
        role: str,
        text: str,
        intent: str,
        topics: list[str],
        confidence: float,
        actor: str,
        metadata: dict[str, Any] | None = None,
        pinned: bool = False,
    ) -> dict[str, Any]:
        row = {
            "message_id": uuid.uuid4().hex,
            "session_id": session_id,
            "role": str(role),
            "text": str(text),
            "intent": self._normalize_intent(intent) or "chat",
            "topics": [str(item).strip() for item in topics if str(item).strip()][:12],
            "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
            "actor": actor,
            "pinned": bool(pinned),
            "timestamp_utc": self._now_iso(),
            "metadata": metadata or {},
        }
        self._ensure_demo_runtime()
        with self._lock:
            appends = self._demo_runtime.setdefault("conversation_appends", [])
            if isinstance(appends, list):
                appends.append(row)
        return row

    def _demo_session_has_assistant_turn(self, session_id: str) -> bool:
        clean_session = self._sanitize_session_id(session_id)
        if not clean_session:
            return False
        rows = self._demo_conversation_rows_runtime()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if str(row.get("session_id", "")) != clean_session:
                continue
            if str(row.get("role", "")) == "assistant":
                return True
        return False

    def _demo_match_conversations_for_question(
        self,
        question_tokens: set[str],
        *,
        session_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not question_tokens:
            return []
        rows = self._demo_conversation_rows_runtime()
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("role", "")) != "user":
                continue
            if session_id and str(row.get("session_id", "")) != session_id:
                continue
            text = str(row.get("text", ""))
            tokens = set(self._tokenize_text(text))
            score = len(question_tokens & tokens)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("timestamp_utc", ""))), reverse=True)
        return [row for _, row in scored[: max(1, min(limit, 50))]]

    def _demo_extract_teach_memory(self, message: str) -> dict[str, Any]:
        rows: list[dict[str, str]] = []
        rows.extend(self._companion_teach_heuristics(message))
        lowered = message.casefold()
        name_match = re.search(r"\bmy name is\s+([a-z][a-z .'-]{1,80})", message, flags=re.IGNORECASE)
        name_value = name_match.group(1).strip(" .") if name_match else ""

        if "i am your dad" in lowered or "i'm your dad" in lowered or "i am your father" in lowered:
            rows.append({"subject": "David", "predicate": "father_relation", "object": "dad"})
            if name_value:
                rows.append({"subject": "David", "predicate": "father_name", "object": name_value})

        if "i am your mom" in lowered or "i'm your mom" in lowered or "i am your mother" in lowered:
            rows.append({"subject": "David", "predicate": "mother_relation", "object": "mom"})
            if name_value:
                rows.append({"subject": "David", "predicate": "mother_name", "object": name_value})

        if name_value and not any(
            str(item.get("predicate", "")).casefold() in {"father_name", "mother_name"} for item in rows if isinstance(item, dict)
        ):
            rows.append({"subject": "User", "predicate": "name", "object": name_value})

        principle_match = re.search(r"\balways value\s+([^\n.!?]{2,140})", message, flags=re.IGNORECASE)
        if principle_match:
            principle = principle_match.group(1).strip(" .")
            if principle:
                rows.append({"subject": "User", "predicate": "value_principle", "object": principle})

        triples: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_fact_row(row.get("subject", ""), row.get("predicate", ""), row.get("object", ""))
            if not normalized:
                continue
            key = (
                normalized["subject"].casefold(),
                normalized["predicate"].casefold(),
                normalized["object"].casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            triples.append(normalized)

        return {
            "triples": triples,
            "notes": "demo_mode_extraction",
            "aliases": [],
            "topics": self._extract_topics(message),
        }

    def _demo_apply_teach_extract(
        self,
        *,
        extracted: dict[str, Any],
        message: str,
        actor: str,
        session_id: str,
        allow_overwrite: bool,
        overwrite_id: str,
        legacy_mode: bool,
    ) -> dict[str, Any]:
        triples = extracted.get("triples", []) if isinstance(extracted.get("triples"), list) else []
        notes = str(extracted.get("notes", "")).strip()
        aliases = extracted.get("aliases", []) if isinstance(extracted.get("aliases"), list) else []
        topics = extracted.get("topics", []) if isinstance(extracted.get("topics"), list) else []

        self._ensure_demo_runtime()
        with self._lock:
            payload = self._demo_runtime.get("memory_payload", {})
            if not isinstance(payload, dict):
                payload = {"facts": [], "lessons": [], "preferences": [], "values": [], "projects": [], "legacy_archive": []}
                self._demo_runtime["memory_payload"] = payload
            facts = payload.get("facts", [])
            if not isinstance(facts, list):
                facts = []
                payload["facts"] = facts

            facts_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in facts:
                if not isinstance(row, dict):
                    continue
                subject = str(row.get("subject", "")).strip()
                predicate = str(row.get("predicate", "")).strip()
                if not subject or not predicate:
                    continue
                facts_by_key.setdefault((subject.casefold(), predicate.casefold()), []).append(row)

            deduped: list[dict[str, str]] = []
            duplicates: list[dict[str, str]] = []
            conflicts: list[dict[str, Any]] = []
            for triple in triples:
                if not isinstance(triple, dict):
                    continue
                normalized = self._normalize_fact_row(triple.get("subject", ""), triple.get("predicate", ""), triple.get("object", ""))
                if not normalized:
                    continue
                key = (normalized["subject"].casefold(), normalized["predicate"].casefold())
                current_rows = facts_by_key.get(key, [])
                exact_match = False
                conflicting_values: list[str] = []
                for existing in current_rows:
                    existing_obj = str(existing.get("object", "")).strip()
                    if not existing_obj:
                        continue
                    if existing_obj.casefold() == normalized["object"].casefold():
                        exact_match = True
                        break
                    similarity = difflib.SequenceMatcher(None, existing_obj.casefold(), normalized["object"].casefold()).ratio()
                    if similarity >= 0.94:
                        exact_match = True
                        break
                    conflicting_values.append(existing_obj)
                if exact_match:
                    duplicates.append(normalized)
                    continue
                if conflicting_values:
                    conflicts.append(
                        {
                            "subject": normalized["subject"],
                            "predicate": normalized["predicate"],
                            "existing_values": sorted(set(conflicting_values)),
                            "incoming": normalized["object"],
                        }
                    )
                deduped.append(normalized)

            if conflicts and not allow_overwrite:
                pending_id = overwrite_id or f"ow_demo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
                pending_map = self._demo_runtime.setdefault("pending_overwrites", {})
                if not isinstance(pending_map, dict):
                    pending_map = {}
                    self._demo_runtime["pending_overwrites"] = pending_map
                pending_map[pending_id] = {
                    "id": pending_id,
                    "status": "pending",
                    "message": message,
                    "actor": actor,
                    "session_id": session_id,
                    "created_at": self._now_iso(),
                    "conflicts": conflicts,
                    "extracted": extracted,
                }
                return {
                    "mode": "teach",
                    "status": "overwrite_confirmation_required",
                    "message": message,
                    "requires_overwrite_confirmation": True,
                    "overwrite_id": pending_id,
                    "stored_facts": [],
                    "stored_count": 0,
                    "deduplicated_count": len(duplicates),
                    "skipped_items": [],
                    "conflicts": conflicts,
                    "notes": notes or "Conflict detected. Confirm overwrite to continue.",
                    "aliases": aliases,
                    "topics": topics,
                    "session_id": session_id,
                    "actor": actor,
                    "timestamp_utc": self._now_iso(),
                }

            overwrite_keys = {(item["subject"].casefold(), item["predicate"].casefold()) for item in deduped}
            if conflicts and allow_overwrite and overwrite_keys:
                facts[:] = [
                    row
                    for row in facts
                    if not (
                        isinstance(row, dict)
                        and (str(row.get("subject", "")).casefold(), str(row.get("predicate", "")).casefold()) in overwrite_keys
                    )
                ]

            now = self._now_iso()
            stored_facts: list[dict[str, Any]] = []
            alias_values = [str(item.get("alias", "")).strip() for item in aliases if isinstance(item, dict)]
            alias_values = [item for item in alias_values if item]
            for triple in deduped:
                stored = {
                    "id": uuid.uuid4().hex,
                    "subject": triple["subject"],
                    "predicate": triple["predicate"],
                    "object": triple["object"],
                    "source": "demo_user",
                    "confidence": 1.0,
                    "timestamp": now,
                    "last_updated": now,
                    "notes": notes,
                    "aliases": alias_values,
                    "session_id": session_id,
                    "provenance": {"source": "demo_user", "actor": actor, "last_updated": now},
                }
                facts.append(stored)
                stored_facts.append(stored)

            payload["facts"] = facts[-2000:]

        return {
            "mode": "teach",
            "status": "stored",
            "message": message,
            "requires_confirmation": False,
            "requires_overwrite_confirmation": False,
            "overwrite_id": overwrite_id,
            "stored_facts": stored_facts,
            "stored_count": len(stored_facts),
            "deduplicated_count": len(duplicates),
            "skipped_items": [],
            "conflicts": conflicts,
            "notes": notes,
            "aliases": aliases,
            "topics": topics,
            "session_id": session_id,
            "actor": actor,
            "timestamp_utc": self._now_iso(),
            "legacy_mode": bool(legacy_mode),
        }

    def _demo_ask_memory(
        self,
        question: str,
        *,
        actor: str,
        session_id: str = "",
        force_transparency: bool = False,
    ) -> dict[str, Any]:
        clean_question = self._sanitize_user_text(question, field_name="question")
        payload = self._demo_memory_payload_runtime()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        all_lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        lessons = self._non_reflection_lessons(all_lessons)
        question_tokens = set(self._tokenize_text(clean_question))

        matched_facts = self._match_facts_for_question(question_tokens, facts, limit=8)
        matched_conversations = self._demo_match_conversations_for_question(
            question_tokens,
            session_id=session_id,
            limit=5,
        )
        matched_lessons = self._match_lessons_for_question(question_tokens, lessons, limit=4)
        matched_values = self._match_values_for_question(question_tokens, values, limit=3)
        matched_projects = self._match_projects_for_query(
            question_tokens,
            projects,
            query_text=clean_question,
            limit=2,
        )
        conversation_source = [
            row
            for row in self._demo_conversation_rows_runtime()
            if isinstance(row, dict) and str(row.get("role", "")) == "user"
        ]
        personality = self._companion_personality(actor)

        if not self.settings.companion_mode:
            answer = MEMORY_UNKNOWN_ANSWER
            if matched_projects:
                answer = self._compose_project_brain_overview_line(matched_projects[0])
            elif matched_facts:
                first = matched_facts[0]
                answer = (
                    f"You told me earlier: {first.get('subject', 'unknown')} "
                    f"{str(first.get('predicate', 'fact')).replace('_', ' ')} is {first.get('object', 'unknown')}."
                )
            elif matched_conversations:
                excerpt = str(matched_conversations[0].get("text", "")).strip()
                answer = f"You told me earlier: {excerpt[:220]}"

            citations = self._build_memory_citations(
                facts=matched_facts,
                conversations=matched_conversations,
                lessons=[],
                values=matched_values,
                projects=matched_projects,
            )
            memory_insight = self._build_memory_insight(
                enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor)),
                matched_facts=matched_facts,
                matched_conversations=matched_conversations,
                matched_lessons=[],
                facts_source=facts,
                conversations_source=conversation_source,
                lessons_source=[],
            )
            return {
                "mode": "ask",
                "status": "answered",
                "question": clean_question,
                "answer": answer,
                "matched_facts": matched_facts,
                "matched_count": len(matched_facts),
                "matched_conversations": matched_conversations,
                "conversation_match_count": len(matched_conversations),
                "matched_lessons": [],
                "lesson_match_count": 0,
                "matched_values": matched_values,
                "values_match_count": len(matched_values),
                "matched_projects": matched_projects,
                "project_match_count": len(matched_projects),
                "citations": citations,
                "memory_insight": memory_insight,
                "used_memory": {
                    "facts": matched_facts[:5],
                    "conversations": matched_conversations[:3],
                    "values": matched_values[:3],
                    "projects": matched_projects[:2],
                },
                "session_id": session_id,
                "actor": actor,
                "timestamp_utc": self._now_iso(),
            }

        answer = self._compose_companion_ask_answer(
            question=clean_question,
            matched_facts=matched_facts,
            matched_conversations=matched_conversations,
            matched_lessons=matched_lessons,
            matched_values=matched_values,
            matched_projects=matched_projects,
            personality_enabled=bool(personality.get("enabled", False)),
            warmth=int(personality.get("warmth", 55)),
            verbosity=int(personality.get("verbosity", 55)),
            curiosity=int(personality.get("curiosity", 50)),
            force_transparency=force_transparency,
        )
        citations = self._build_memory_citations(
            facts=matched_facts,
            conversations=matched_conversations,
            lessons=matched_lessons,
            values=matched_values,
            projects=matched_projects,
        )
        memory_insight = self._build_memory_insight(
            enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor)),
            matched_facts=matched_facts,
            matched_conversations=matched_conversations,
            matched_lessons=matched_lessons,
            facts_source=facts,
            conversations_source=conversation_source,
            lessons_source=lessons,
        )

        return {
            "mode": "ask",
            "status": "answered",
            "question": clean_question,
            "answer": answer,
            "matched_facts": matched_facts,
            "matched_count": len(matched_facts),
            "matched_conversations": matched_conversations,
            "conversation_match_count": len(matched_conversations),
            "matched_lessons": matched_lessons,
            "lesson_match_count": len(matched_lessons),
            "matched_values": matched_values,
            "values_match_count": len(matched_values),
            "matched_projects": matched_projects,
            "project_match_count": len(matched_projects),
            "citations": citations,
            "memory_insight": memory_insight,
            "used_memory": {
                "facts": matched_facts[:5],
                "conversations": matched_conversations[:3],
                "lessons": matched_lessons[:3],
                "values": matched_values[:3],
                "projects": matched_projects[:2],
            },
            "session_id": session_id,
            "actor": actor,
            "timestamp_utc": self._now_iso(),
        }

    def _demo_teach_memory(
        self,
        message: str,
        *,
        actor: str,
        confirm_conflict: bool,
    ) -> dict[str, Any]:
        if self.settings.safe_mode:
            raise ValueError("Safe mode is enabled. /teach is blocked in read-only mode.")
        clean_message = self._sanitize_user_text(message, field_name="message")
        if self._contains_sensitive_memory_text(clean_message):
            raise ValueError("Sensitive data cannot be stored in memory.")
        extracted = self._demo_extract_teach_memory(clean_message)
        payload = self._demo_apply_teach_extract(
            extracted=extracted,
            message=clean_message,
            actor=actor,
            session_id="",
            allow_overwrite=bool(confirm_conflict),
            overwrite_id="",
            legacy_mode=True,
        )
        if payload.get("status") == "overwrite_confirmation_required":
            payload["status"] = "conflict"
            payload["requires_confirmation"] = True
            payload["notes"] = "Conflict detected. Confirm to continue."
            payload["stored_facts"] = []
            payload["stored_count"] = 0
            payload["skipped_items"] = []
        if payload.get("status") == "stored":
            payload["confirmed_conflict"] = bool(payload.get("conflicts")) and bool(confirm_conflict)
            payload["requires_confirmation"] = False
        return payload

    def _demo_confirm_memory_overwrite(
        self,
        overwrite_id: str,
        *,
        decision: str,
        actor: str,
    ) -> tuple[bool, dict[str, Any]]:
        clean_id = str(overwrite_id).strip()
        if not clean_id:
            return False, {"error": "overwrite_id is required."}
        choice = str(decision).strip().lower()
        if choice not in {"approve", "reject"}:
            return False, {"error": "decision must be approve or reject."}

        self._ensure_demo_runtime()
        with self._lock:
            pending_map = self._demo_runtime.get("pending_overwrites", {})
            if not isinstance(pending_map, dict):
                pending_map = {}
                self._demo_runtime["pending_overwrites"] = pending_map
            pending = pending_map.get(clean_id)
            if not isinstance(pending, dict):
                return False, {"error": "Overwrite request not found."}
            if str(pending.get("status", "pending")) != "pending":
                return False, {"error": "Overwrite request is already resolved."}
            pending["status"] = "approved" if choice == "approve" else "rejected"
            pending["decided_at"] = self._now_iso()
            pending["decided_by"] = actor.strip() or "web_ui"

        if choice == "reject":
            payload = {
                "mode": "teach",
                "status": "rejected",
                "overwrite_id": clean_id,
                "message": str(pending.get("message", "")),
                "actor": actor.strip() or "web_ui",
                "timestamp_utc": self._now_iso(),
            }
            self.publish_event("status", {"type": "memory_teach_overwrite_rejected", "payload": payload})
            self.publish_event("logs", {"type": "memory_teach_overwrite_rejected", "payload": payload})
            return True, payload

        payload = self._demo_apply_teach_extract(
            extracted=pending.get("extracted", {}),
            message=str(pending.get("message", "")),
            actor=actor.strip() or "web_ui",
            session_id=str(pending.get("session_id", "")),
            allow_overwrite=True,
            overwrite_id=clean_id,
            legacy_mode=False,
        )
        self.publish_event("status", {"type": "memory_teach_overwrite_confirmed", "payload": payload})
        self.publish_event("logs", {"type": "memory_teach_overwrite_confirmed", "payload": payload})
        return True, payload

    def _demo_parent_teaching_turn(
        self,
        *,
        message: str,
        actor: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        clean_session = self._sanitize_session_id(session_id)
        if not clean_session:
            return None
        self._ensure_demo_runtime()
        with self._lock:
            pending_map = self._demo_runtime.setdefault("pending_parent_teaching", {})
            if not isinstance(pending_map, dict):
                pending_map = {}
                self._demo_runtime["pending_parent_teaching"] = pending_map
            pending = pending_map.get(clean_session)
            memory_payload = self._demo_runtime.get("memory_payload", {})
            if not isinstance(memory_payload, dict):
                memory_payload = {"facts": [], "lessons": [], "preferences": [], "values": [], "projects": [], "legacy_archive": []}
                self._demo_runtime["memory_payload"] = memory_payload
            values = memory_payload.get("values", [])
            if not isinstance(values, list):
                values = []
                memory_payload["values"] = values

            if isinstance(pending, dict):
                category = str(pending.get("category", "value"))
                principle = str(pending.get("principle", "this principle")).strip()
                application = str(message).strip()[:600]
                now = self._now_iso()
                entry = {
                    "id": uuid.uuid4().hex,
                    "timestamp_utc": now,
                    "category": self._normalize_teaching_category(category),
                    "category_label": self._teaching_category_label(category),
                    "principle": principle,
                    "application": application,
                    "source": "parent_teaching_mode",
                    "actor": actor,
                    "session_id": clean_session,
                    "message": str(pending.get("message", "")).strip()[:400],
                    "tags": ["parent_teaching", self._normalize_teaching_category(category)],
                }
                values.append(entry)
                memory_payload["values"] = values[-2000:]
                pending_map.pop(clean_session, None)
                return {
                    "mode": "teach",
                    "status": "stored",
                    "parent_teaching_mode": True,
                    "parent_teaching_stage": "completed",
                    "requires_clarification": False,
                    "category": entry["category"],
                    "category_label": entry["category_label"],
                    "principle": principle,
                    "application": application,
                    "stored_values": [entry],
                    "stored_value_count": 1,
                    "message": str(message),
                    "session_id": clean_session,
                    "actor": actor,
                    "timestamp_utc": now,
                }

            category = self._classify_parent_teaching_category(message)
            principle = self._extract_parent_teaching_principle(message)
            question = self._build_parent_teaching_question(category, principle)
            pending_map[clean_session] = {
                "category": category,
                "principle": principle,
                "question": question,
                "message": str(message),
                "actor": actor,
                "session_id": clean_session,
                "created_at": self._now_iso(),
            }
            return {
                "mode": "teach",
                "status": "parent_teaching_clarify_required",
                "parent_teaching_mode": True,
                "parent_teaching_stage": "clarifying",
                "requires_clarification": True,
                "category": category,
                "category_label": self._teaching_category_label(category),
                "principle": principle,
                "question": question,
                "message": str(message),
                "session_id": clean_session,
                "actor": actor,
                "timestamp_utc": self._now_iso(),
            }

    def _demo_companion_chat_response(
        self,
        message: str,
        *,
        session_id: str,
        actor: str,
        force_transparency: bool,
    ) -> dict[str, Any]:
        payload = self._demo_memory_payload_runtime()
        facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        all_lessons = payload.get("lessons", []) if isinstance(payload.get("lessons"), list) else []
        values = payload.get("values", []) if isinstance(payload.get("values"), list) else []
        projects = payload.get("projects", []) if isinstance(payload.get("projects"), list) else []
        lessons = self._non_reflection_lessons(all_lessons)
        message_tokens = set(self._tokenize_text(message))
        matched_facts = self._match_facts_for_question(message_tokens, facts, limit=3)
        matched_conversations = self._demo_match_conversations_for_question(message_tokens, session_id=session_id, limit=2)
        matched_lessons = self._match_lessons_for_question(message_tokens, lessons, limit=2)
        matched_values = self._match_values_for_question(message_tokens, values, limit=2)
        matched_projects = self._match_projects_for_query(
            message_tokens,
            projects,
            query_text=message,
            limit=2,
        )
        conversation_source = [
            row
            for row in self._demo_conversation_rows_runtime()
            if isinstance(row, dict) and str(row.get("role", "")) == "user"
        ]
        personality = self._companion_personality(actor)
        reply = self._compose_companion_ask_answer(
            question=message,
            matched_facts=matched_facts,
            matched_conversations=matched_conversations,
            matched_lessons=matched_lessons,
            matched_values=matched_values,
            matched_projects=matched_projects,
            personality_enabled=bool(personality.get("enabled", False)),
            warmth=int(personality.get("warmth", 55)),
            verbosity=int(personality.get("verbosity", 55)),
            curiosity=int(personality.get("curiosity", 50)),
            force_transparency=force_transparency,
        )

        if not matched_facts and not matched_lessons and not matched_projects and not matched_conversations and not matched_values:
            if self.settings.companion_mode:
                reply = "I am here with you in the Dashboard, ready to learn. Would you like to ask or teach one step at a time?"
            else:
                reply = "I can chat naturally. If you want me to remember something, switch to Teach and confirm save."

        return {
            "mode": "chat",
            "status": "ok",
            "message": message,
            "reply": reply,
            "citations": self._build_memory_citations(
                facts=matched_facts,
                conversations=matched_conversations,
                lessons=matched_lessons,
                values=matched_values,
                projects=matched_projects,
            ),
            "used_memory": {
                "facts": matched_facts[:5],
                "conversations": matched_conversations[:3],
                "lessons": matched_lessons[:3],
                "values": matched_values[:3],
                "projects": matched_projects[:2],
            },
            "memory_insight": self._build_memory_insight(
                enabled=bool(self.settings.memory_insight_mode and self._is_web_actor(actor)),
                matched_facts=matched_facts,
                matched_conversations=matched_conversations,
                matched_lessons=matched_lessons,
                facts_source=facts,
                conversations_source=conversation_source,
                lessons_source=lessons,
            ),
            "timestamp_utc": self._now_iso(),
        }

    def _demo_chat_message(
        self,
        message: str,
        *,
        intent: str,
        confirm_save: bool,
        parent_teaching_mode: bool,
        session_id: str,
        actor: str,
    ) -> dict[str, Any]:
        clean_message = self._sanitize_user_text(message, field_name="message")
        actor_value = actor.strip() or "web_ui"
        detected = self.classify_chat_intent(clean_message)
        selected_intent = self._normalize_intent(intent) or str(detected.get("intent", "chat"))
        active_session_id = self._resolve_chat_session_id(session_id=session_id, actor=actor_value)
        parent_mode_active = bool(parent_teaching_mode or self.settings.parent_teaching_mode)
        self._ensure_demo_runtime()
        with self._lock:
            pending_parent = self._demo_runtime.get("pending_parent_teaching", {})
            has_pending_parent = isinstance(pending_parent, dict) and active_session_id in pending_parent
        if parent_mode_active and has_pending_parent and selected_intent in {"chat", "teach"}:
            selected_intent = "teach"
        topics = detected.get("topics", [])
        confidence = float(detected.get("confidence", 0.5))

        user_turn = self._demo_append_conversation_turn(
            session_id=active_session_id,
            role="user",
            text=clean_message,
            intent=selected_intent,
            topics=topics if isinstance(topics, list) else [],
            confidence=confidence,
            actor=actor_value,
        )
        is_first_assistant_turn = not self._demo_session_has_assistant_turn(active_session_id)

        response: dict[str, Any]
        if selected_intent == "ask":
            response = self._demo_ask_memory(
                clean_message,
                actor=actor_value,
                session_id=active_session_id,
                force_transparency=is_first_assistant_turn,
            )
            assistant_text = str(response.get("answer", "")).strip() or "No answer generated."
        elif selected_intent == "teach":
            if not bool(confirm_save):
                preview = self._demo_extract_teach_memory(clean_message)
                response = {
                    "mode": "teach",
                    "status": "confirmation_required",
                    "message": clean_message,
                    "requires_confirmation": True,
                    "confirm_save": False,
                    "actor": actor_value,
                    "session_id": active_session_id,
                    "triples": preview.get("triples", []),
                    "aliases": preview.get("aliases", []),
                    "notes": preview.get("notes", ""),
                    "topics": preview.get("topics", []),
                    "timestamp_utc": self._now_iso(),
                }
                assistant_text = "I can save this as memory after you confirm Teach."
            else:
                parent_response = (
                    self._demo_parent_teaching_turn(
                        message=clean_message,
                        actor=actor_value,
                        session_id=active_session_id,
                    )
                    if parent_mode_active
                    else None
                )
                if parent_response is not None:
                    response = parent_response
                    if str(response.get("status", "")) == "parent_teaching_clarify_required":
                        assistant_text = str(response.get("question", "")).strip() or "How should I apply this while debugging?"
                    else:
                        stored_values = int(response.get("stored_value_count", 0))
                        category = str(response.get("category_label", "Values")).strip()
                        assistant_text = f"Stored {stored_values} {category} teaching entry."
                else:
                    extracted = self._demo_extract_teach_memory(clean_message)
                    response = self._demo_apply_teach_extract(
                        extracted=extracted,
                        message=clean_message,
                        actor=actor_value,
                        session_id=active_session_id,
                        allow_overwrite=False,
                        overwrite_id="",
                        legacy_mode=False,
                    )
                    if response.get("status") == "overwrite_confirmation_required":
                        assistant_text = "I detected conflicting memory. Confirm overwrite to continue."
                    else:
                        stored_count = int(response.get("stored_count", 0))
                        assistant_text = f"Saved {stored_count} memory facts."
        elif selected_intent == "goal":
            started, run_result = self.start_run(
                {
                    "mode": "goal",
                    "payload": clean_message,
                    "preview": False,
                }
            )
            response = {
                "mode": "goal",
                "status": "queued" if started else "error",
                "run": run_result,
                "message": clean_message,
                "actor": actor_value,
                "session_id": active_session_id,
                "timestamp_utc": self._now_iso(),
            }
            assistant_text = (
                f"Goal queued: {run_result.get('run_id', '')}"
                if started
                else f"Goal could not start: {run_result.get('error', 'unknown error')}"
            )
        else:
            response = self._demo_companion_chat_response(
                clean_message,
                session_id=active_session_id,
                actor=actor_value,
                force_transparency=is_first_assistant_turn,
            )
            response["actor"] = actor_value
            response["session_id"] = active_session_id
            assistant_text = str(response["reply"])

        if self.settings.companion_mode:
            requires_transparency = (
                is_first_assistant_turn
                or self._is_family_context(clean_message)
                or self._is_grief_context(clean_message)
                or self._is_crisis_context(clean_message)
            )
            transparency_line = self._compose_ai_transparency_line()
            if requires_transparency and transparency_line not in assistant_text:
                assistant_text = f"{assistant_text} {transparency_line}".strip()
                if str(response.get("mode", "")) == "ask":
                    response["answer"] = assistant_text
                elif str(response.get("mode", "")) == "chat":
                    response["reply"] = assistant_text

        assistant_turn = self._demo_append_conversation_turn(
            session_id=active_session_id,
            role="assistant",
            text=assistant_text,
            intent=selected_intent,
            topics=topics if isinstance(topics, list) else [],
            confidence=confidence,
            actor=actor_value,
            metadata={
                "response_status": str(response.get("status", "")),
                "citations": response.get("citations", []),
                "memory_insight": response.get("memory_insight", {}),
                "used_memory": response.get("used_memory", {}),
                "takeaways": response.get("stored_facts", []),
            },
        )

        return {
            "mode": "chat",
            "message": clean_message,
            "detected_intent": detected.get("intent", "chat"),
            "detected_confidence": round(confidence, 3),
            "selected_intent": selected_intent,
            "confirm_save": bool(confirm_save),
            "parent_teaching_mode": parent_mode_active,
            "session_id": active_session_id,
            "user_turn": user_turn,
            "assistant_turn": assistant_turn,
            "response": response,
            "timestamp_utc": self._now_iso(),
        }

    def _demo_submit_approval(
        self,
        *,
        approval_id: str,
        decision: str,
        note: str,
        actor: str,
        confirmation: str,
    ) -> tuple[bool, dict[str, Any]]:
        choice = decision.strip().lower()
        if choice not in {"approve", "reject"}:
            return False, {"error": "Decision must be approve or reject."}

        self._ensure_demo_runtime()
        with self._lock:
            approvals = self._demo_runtime.get("approvals", [])
            if not isinstance(approvals, list):
                approvals = []
                self._demo_runtime["approvals"] = approvals
            approval = next(
                (
                    row
                    for row in approvals
                    if isinstance(row, dict) and str(row.get("id", "")).strip() == str(approval_id).strip()
                ),
                None,
            )
            if not isinstance(approval, dict):
                return False, {"error": "Approval request not found."}
            if str(approval.get("status", "")).strip().lower() != "pending":
                return False, {"error": "Approval is already resolved."}
            if choice == "approve" and bool(approval.get("requires_typed_confirmation")):
                expected = self._demo_typed_confirmation_expected(approval)
                if confirmation.strip().lower() != expected.lower():
                    return False, {"error": f"Typed confirmation required: `{expected}`"}

            approval["status"] = "approved" if choice == "approve" else "rejected"
            approval["decision"] = choice
            approval["decision_note"] = note.strip()
            approval["decided_at"] = self._now_iso()
            approval["actor"] = actor.strip() or "local_user"
            run_id = str(approval.get("run_id", ""))

            audit_entry = {
                "timestamp_utc": self._now_iso(),
                "action": "approval_decision",
                "payload": {
                    "approval_id": str(approval_id).strip(),
                    "decision": choice,
                    "actor": actor.strip() or "local_user",
                    "note": note.strip(),
                },
            }
            appends = self._demo_runtime.setdefault("approval_audit_appends", {})
            if not isinstance(appends, dict):
                appends = {}
                self._demo_runtime["approval_audit_appends"] = appends
            run_audit = appends.setdefault(run_id, [])
            if not isinstance(run_audit, list):
                run_audit = []
                appends[run_id] = run_audit
            run_audit.append(audit_entry)

        self.publish_event(
            f"run:{run_id}",
            {"type": "approval_decision", "run_id": run_id, "approval_id": approval_id, "decision": choice},
        )
        self.publish_event(
            "status",
            {"type": "approval_decision", "run_id": run_id, "approval_id": approval_id, "decision": choice},
        )
        return True, {"approval_id": approval_id, "decision": choice}

    def _demo_run_dirs(self) -> list[Path]:
        runs_root = self._demo_runs_root()
        if not runs_root.exists() or not runs_root.is_dir():
            return []
        rows = [item for item in runs_root.iterdir() if item.is_dir()]
        rows.sort(key=lambda item: item.name, reverse=True)
        return rows

    def _live_data_has_content(self) -> bool:
        has_runs = any(item.is_dir() for item in self.runs_root.iterdir()) if self.runs_root.exists() else False
        memory_payload = self._read_memory_payload()
        has_memory = False
        if isinstance(memory_payload, dict):
            has_memory = any(
                isinstance(memory_payload.get(name), list) and len(memory_payload.get(name, [])) > 0
                for name in ("facts", "lessons", "values", "projects", "legacy_archive")
            )
        has_conversations = bool(self._tail_lines(self._conversations_file, limit=1))
        return has_runs or has_memory or has_conversations

    def _materialize_demo_workspace_files(self) -> int:
        count = 0
        workspace_root = self.config.workspace_dir.resolve()
        for run_dir in self._demo_run_dirs():
            summary = self._read_json(run_dir / "file_summary.json", default={})
            if not isinstance(summary, dict):
                continue
            rows = summary.get("workspace_files", [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    rel = self._normalize_relative_path(str(row.get("path", "")).strip())
                except ValueError:
                    continue
                target = (workspace_root / rel).resolve()
                if target == workspace_root or workspace_root not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                preview = str(row.get("after_preview", "")).strip()
                content = preview if preview else "# demo workspace file\n"
                try:
                    target.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")
                except OSError:
                    continue
                count += 1
        return count

    def _apply_demo_baseline_to_live(self, *, overwrite: bool, actor: str) -> tuple[bool, dict[str, Any]]:
        fixture_root = self._demo_fixture_root()
        runs_fixture = (fixture_root / "mock_runs").resolve()
        if not fixture_root.exists() or not fixture_root.is_dir():
            return False, {"error": f"Demo fixture root not found: {fixture_root}"}
        if not runs_fixture.exists() or not runs_fixture.is_dir():
            return False, {"error": f"Demo runs fixture folder not found: {runs_fixture}"}

        if overwrite:
            if self.runs_root.exists():
                for item in self.runs_root.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
            self.runs_root.mkdir(parents=True, exist_ok=True)

        copied_runs = 0
        for run_dir in runs_fixture.iterdir():
            if not run_dir.is_dir():
                continue
            target = (self.runs_root / run_dir.name).resolve()
            if target.exists():
                if not overwrite:
                    continue
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(run_dir, target)
            copied_runs += 1

        memory_fixture = (fixture_root / "mock_memory_long_term.json").resolve()
        if memory_fixture.exists():
            self.config.memory_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(memory_fixture, self.config.memory_file)

        conversations_fixture = (fixture_root / "mock_conversations.jsonl").resolve()
        if conversations_fixture.exists():
            self._conversations_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(conversations_fixture, self._conversations_file)

        telemetry_fixture = (fixture_root / "mock_telemetry.jsonl").resolve()
        if telemetry_fixture.exists():
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(telemetry_fixture, self.config.logs_dir / "telemetry.jsonl")

        metrics_fixture = (fixture_root / "mock_metrics.json").resolve()
        if metrics_fixture.exists():
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(metrics_fixture, self.config.logs_dir / "metrics.json")

        logs_fixture = (fixture_root / "mock_logs.txt").resolve()
        if logs_fixture.exists():
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(logs_fixture, self.config.logs_dir / "web_control_center.log")

        settings_payload = asdict(self.settings)
        fixture_settings = self._read_demo_json("mock_settings.json", default={})
        if isinstance(fixture_settings, dict):
            allowed_keys = set(settings_payload.keys())
            for key, value in fixture_settings.items():
                if key in allowed_keys:
                    settings_payload[key] = value
        settings_payload["demo_mode"] = True
        self.settings = ControlSettings.from_dict(settings_payload)
        self._save_settings()

        materialized_workspace_files = self._materialize_demo_workspace_files()
        self._reset_demo_runtime()

        payload = {
            "loaded": True,
            "copied_runs": copied_runs,
            "workspace_files_materialized": materialized_workspace_files,
            "demo_mode": True,
            "actor": actor.strip() or "web_ui",
            "timestamp_utc": self._now_iso(),
            "fixture_root": str(fixture_root),
        }
        self.publish_event("status", {"type": "demo_data_loaded", "payload": payload})
        self.publish_event("logs", {"type": "demo_data_loaded", "payload": payload})
        return True, payload

    def load_demo_data(self, *, force: bool = False, actor: str = "web_ui") -> tuple[bool, dict[str, Any]]:
        if self._live_data_has_content() and not force:
            return False, {
                "error": "Live data already exists. Pass confirm_overwrite=true to replace it with demo fixtures.",
                "requires_confirmation": True,
            }
        return self._apply_demo_baseline_to_live(overwrite=True, actor=actor)

    def reset_demo_data(self, *, actor: str = "web_ui") -> tuple[bool, dict[str, Any]]:
        ok, payload = self._apply_demo_baseline_to_live(overwrite=True, actor=actor)
        if not ok:
            return ok, payload
        payload = dict(payload)
        payload["reset"] = True
        self.publish_event("status", {"type": "demo_data_reset", "payload": payload})
        self.publish_event("logs", {"type": "demo_data_reset", "payload": payload})
        return True, payload

    def workspace_edit_file(self, relative_path: str, content: str, actor: str = "web_ui") -> dict[str, Any]:
        if self._demo_mode_enabled():
            raise ValueError("Demo mode is active. Workspace edits are disabled to preserve deterministic fixtures.")
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
        if self._demo_mode_enabled():
            raise ValueError("Demo mode is active. Workspace deletes are disabled to preserve deterministic fixtures.")
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
        if self._demo_mode_enabled():
            raise ValueError("Demo mode is active. Workspace rename is disabled to preserve deterministic fixtures.")
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

    @staticmethod
    def _normalize_relative_path(relative_path: str) -> str:
        raw = str(relative_path).replace("\\", "/").strip()
        cleaned = "/".join(part for part in raw.split("/") if part not in {"", "."})
        if not cleaned:
            raise ValueError("Path cannot be empty.")
        if cleaned.startswith("..") or "/.." in cleaned:
            raise ValueError("Path escapes allowed boundary.")
        return cleaned

    @classmethod
    def _is_self_improvement_blocked_path(cls, relative_path: str) -> bool:
        normalized = str(relative_path).replace("\\", "/").strip().casefold()
        return normalized in SELF_IMPROVEMENT_BLOCKED_PATHS

    def _resolve_project_file_path(self, relative_path: str) -> tuple[Path, str]:
        cleaned = self._normalize_relative_path(relative_path)
        if cleaned.startswith(".git/") or cleaned == ".git":
            raise ValueError("Path targets Git metadata and is not allowed.")
        target = (self.project_root / cleaned).resolve()
        if target == self.project_root or self.project_root not in target.parents:
            raise ValueError("Path escapes project boundary.")
        if target.exists() and target.is_dir():
            raise ValueError("Target path is a folder. Expected a file path.")
        return target, cleaned

    def _resolve_workspace_path(self, relative_path: str) -> tuple[Path, str]:
        cleaned = self._normalize_relative_path(relative_path)
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

    def _self_improvement_rows(self) -> list[dict[str, Any]]:
        payload = self._read_json(self.self_improvements_file, default={"proposals": []})
        if not isinstance(payload, dict):
            payload = {}
        proposals = payload.get("proposals", [])
        if not isinstance(proposals, list):
            proposals = []
        rows = [row for row in proposals if isinstance(row, dict)]
        if rows != proposals:
            self._save_self_improvement_rows(rows)
        return rows

    def _save_self_improvement_rows(self, rows: list[dict[str, Any]]) -> None:
        self._write_json(self.self_improvements_file, {"proposals": rows})

    def _update_self_improvement_record(self, proposal: dict[str, Any]) -> None:
        clean_id = str(proposal.get("id", "")).strip()
        if not clean_id:
            return
        with self._lock:
            rows = self._self_improvement_rows()
            for idx, row in enumerate(rows):
                if str(row.get("id", "")).strip() == clean_id:
                    rows[idx] = proposal
                    break
            else:
                rows.append(proposal)
            self._save_self_improvement_rows(rows)

        sandbox_dir_raw = str(proposal.get("sandbox_dir", "")).strip()
        if not sandbox_dir_raw:
            return
        try:
            sandbox_dir = Path(sandbox_dir_raw).resolve()
        except (OSError, ValueError):
            return
        if sandbox_dir != self.agent_sandbox_root and self.agent_sandbox_root not in sandbox_dir.parents:
            return
        metadata_path = sandbox_dir / "metadata.json"
        self._write_json(metadata_path, proposal)

    def _merge_self_improvement_proposal(self, proposal: dict[str, Any], *, actor: str) -> dict[str, Any]:
        changes = proposal.get("changes", [])
        if not isinstance(changes, list) or not changes:
            raise ValueError("Proposal has no file changes to merge.")

        merged_paths: list[str] = []
        for idx, row in enumerate(changes):
            if not isinstance(row, dict):
                raise ValueError(f"Invalid change entry at index {idx}.")
            normalized = str(row.get("path", "")).strip()
            if not normalized:
                raise ValueError(f"Missing path for change index {idx}.")
            if self._is_self_improvement_blocked_path(normalized):
                raise ValueError(f"Blocked safety path: {normalized}")
            target_path, normalized = self._resolve_project_file_path(normalized)
            sandbox_file_raw = str(row.get("sandbox_file", "")).strip()
            if not sandbox_file_raw:
                raise ValueError(f"Missing sandbox file for change '{normalized}'.")
            try:
                sandbox_file = Path(sandbox_file_raw).resolve()
            except (OSError, ValueError) as exc:
                raise ValueError(f"Invalid sandbox file for '{normalized}': {exc}") from exc
            if sandbox_file == self.agent_sandbox_root or self.agent_sandbox_root not in sandbox_file.parents:
                raise ValueError(f"Sandbox file escaped sandbox root: {sandbox_file}")
            if not sandbox_file.exists() or not sandbox_file.is_file():
                raise ValueError(f"Sandbox prototype file missing: {sandbox_file}")
            try:
                content = sandbox_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"Unable to read sandbox file '{sandbox_file}': {exc}") from exc
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                target_path.write_text(content, encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"Unable to merge '{normalized}': {exc}") from exc
            merged_paths.append(normalized)

        merged_at = self._now_iso()
        updated = dict(proposal)
        updated["status"] = "merged"
        updated["updated_at"] = merged_at
        updated["merge"] = {
            "merged_at": merged_at,
            "actor": actor.strip() or "web_ui",
            "file_count": len(merged_paths),
            "paths": merged_paths,
        }
        return updated

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
    def _is_safe_import_id(import_id: str) -> bool:
        return bool(IMPORT_ID_PATTERN.match(import_id))

    @staticmethod
    def _is_safe_upload_id(upload_id: str) -> bool:
        return bool(UPLOAD_ID_PATTERN.match(upload_id))

    @staticmethod
    def _new_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"run_{stamp}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _new_upload_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"upl_{stamp}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _resolve_app_version(self) -> str:
        explicit = str(os.getenv("DAVID_APP_VERSION", "")).strip()
        if explicit:
            return explicit[:64]
        version_file = (self.project_root / "VERSION").resolve()
        if version_file.exists() and version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if text:
                return text[:64]
        return "dev"

    def _resolve_git_commit(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            return ""
        if result.returncode != 0:
            return ""
        return str(result.stdout or "").strip()[:16]

    @staticmethod
    def _compose_version_stamp(app_version: str, git_commit: str) -> str:
        clean_version = str(app_version or "dev").strip() or "dev"
        clean_commit = str(git_commit or "").strip()
        if clean_commit:
            return f"{clean_version}+{clean_commit}"
        return clean_version

    def _normalize_iso_timestamp(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return self._now_iso()
        parsed = self._parse_timestamp(text)
        if parsed is None:
            return self._now_iso()
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_user_text(value: str, *, field_name: str, max_chars: int = 4_000) -> str:
        text = str(value).replace("\x00", "").strip()
        if not text:
            raise ValueError(f"{field_name} cannot be empty.")
        if len(text) > max_chars:
            raise ValueError(f"{field_name} exceeds max length ({max_chars} chars).")
        return text

    @staticmethod
    def _sanitize_json_metadata(value: Any, *, max_chars: int = 20_000) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object.")
        try:
            normalized_text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"metadata is not JSON serializable: {exc}") from exc
        if len(normalized_text) > max_chars:
            raise ValueError(f"metadata exceeds max length ({max_chars} chars).")
        try:
            normalized = json.loads(normalized_text)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError(f"metadata normalization failed: {exc}") from exc
        return normalized if isinstance(normalized, dict) else {}


def create_control_center(config: AgentConfig | None = None, data_root: Path | None = None) -> DavidControlCenter:
    return DavidControlCenter(config=config, data_root=data_root)


__all__ = ["DavidControlCenter", "create_control_center", "ControlSettings"]
