from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.coder import Coder
from agent.config import AgentConfig
from agent.contracts import CriticOutput, ExecutionResult, LessonProposal
from agent.critic import Critic
from agent.executor import RestrictedExecutor
from agent.git_committer import GitCommitter, build_commit_message
from agent.llm import OllamaClient
from agent.memory import LongTermMemory
from agent.plan_quality import build_plan_quality_replan_context, score_plan_quality
from agent.planner import Planner
from agent.projects import ensure_workspace_layout, prepare_project_for_goal
from agent.safety import SafetyError, SafetyGuard, ValidatedEdit
from agent.telemetry import IterationMetric, TelemetryLogger
from agent.workspace import WorkspaceInspector


@dataclass(frozen=True)
class RunSummary:
    goal: str
    success: bool
    iterations_used: int
    message: str


class DavidAgent:
    """Coordinates Planner -> Coder -> Safety -> Executor -> Critic -> Memory loop."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        llm = OllamaClient(config)

        self._planner = Planner(llm, model_name=config.planner_model)
        self._coder = Coder(llm, model_name=config.coder_model)
        self._critic = Critic(llm, model_name=config.critic_model)
        self._memory = LongTermMemory(config.memory_file)
        self._telemetry = TelemetryLogger(config.logs_dir)
        ensure_workspace_layout(config.workspace_dir)

    def run(self, goal: str, max_iterations: int | None = None) -> RunSummary:
        iteration_limit = max_iterations or self._config.max_iterations
        tdd_mode = self._config.tdd_mode
        tdd_red_phase_complete = False
        iterations_until_green: int | None = None
        project = prepare_project_for_goal(self._config.workspace_dir, goal)
        git_committer = GitCommitter(project.project_path) if self._config.git_auto_commit else None
        safety = SafetyGuard(
            workspace_dir=project.project_path,
            max_file_write_bytes=self._config.max_file_write_bytes,
            max_total_write_bytes=self._config.max_total_write_bytes,
            allowed_commands=self._config.allowed_commands,
        )
        executor = RestrictedExecutor(
            workspace_dir=project.project_path,
            timeout_sec=self._config.command_timeout_sec,
            max_output_chars=self._config.max_command_output_chars,
        )
        workspace = WorkspaceInspector(project.project_path)
        project_meta = {
            "project_slug": project.project_slug,
            "project_path": str(project.project_path),
            "project_created_new": project.project_created_new,
        }

        self._telemetry.event(
            "run_started",
            {
                "goal": goal,
                "planner_model_used": self._config.planner_model,
                "coder_model_used": self._config.coder_model,
                "critic_model_used": self._config.critic_model,
                "tdd_mode": tdd_mode,
                **project_meta,
            },
        )

        run_started_at = datetime.now(tz=timezone.utc).isoformat()
        self._memory.clear_session_hints()
        initial_snapshot = workspace.snapshot()
        base_memory_context, memory_meta = self._memory.render_context_and_meta(goal)
        self._telemetry.event(
            "memory_context_injected",
            {
                "goal": goal,
                "lessons_count": len(memory_meta),
                "lessons_used": memory_meta,
                **project_meta,
            },
        )
        log_context = self._build_goal_log_context()
        memory_context = self._compose_goal_context(base_memory_context, log_context)
        threshold = max(0, min(100, int(self._config.plan_quality_threshold)))
        max_plan_attempts = 2 if threshold > 0 else 1
        plan_payload: dict = {}
        plan_quality: dict = {}
        plan_quality_passed = False

        for plan_attempt in range(1, max_plan_attempts + 1):
            plan_memory_context = memory_context
            if plan_attempt > 1:
                plan_memory_context = build_plan_quality_replan_context(
                    memory_context,
                    plan_quality,
                    threshold=threshold,
                    tdd_mode=tdd_mode,
                    attempt=plan_attempt - 1,
                    max_attempts=max_plan_attempts,
                )
                self._telemetry.event(
                    "plan_quality_replan_requested",
                    {
                        "goal": goal,
                        "plan_attempt": plan_attempt,
                        "plan_quality_previous": plan_quality,
                        "planner_model_used": self._config.planner_model,
                        "coder_model_used": self._config.coder_model,
                        "critic_model_used": self._config.critic_model,
                        "tdd_mode": tdd_mode,
                        **project_meta,
                    },
                )

            plan = self._planner.create_plan(
                goal=goal,
                workspace_snapshot=initial_snapshot,
                memory_context=plan_memory_context,
                tdd_mode=tdd_mode,
            )
            plan_payload = plan.to_dict()

            self._telemetry.event(
                "plan_created",
                {
                    "goal": goal,
                    "plan": plan_payload,
                    "plan_attempt": plan_attempt,
                    "auto_replan": plan_attempt > 1,
                    "planner_model_used": self._config.planner_model,
                    "coder_model_used": self._config.coder_model,
                    "critic_model_used": self._config.critic_model,
                    "tdd_mode": tdd_mode,
                    "logs_context_included": bool(log_context.strip()),
                    **project_meta,
                },
            )

            plan_quality = score_plan_quality(plan_payload, tdd_mode=tdd_mode)
            plan_quality_passed = plan_quality.get("score", 0) >= threshold if threshold > 0 else True
            plan_quality["threshold"] = threshold
            plan_quality["passed"] = plan_quality_passed
            plan_quality["attempt"] = plan_attempt
            plan_quality["max_attempts"] = max_plan_attempts
            self._telemetry.event(
                "plan_quality_scored",
                {
                    "goal": goal,
                    "plan_quality": plan_quality,
                    "plan_attempt": plan_attempt,
                    "planner_model_used": self._config.planner_model,
                    "coder_model_used": self._config.coder_model,
                    "critic_model_used": self._config.critic_model,
                    "tdd_mode": tdd_mode,
                    **project_meta,
                },
            )
            if plan_quality_passed:
                break

        if not plan_quality_passed:
            attempts_used = int(plan_quality.get("attempt", max_plan_attempts))
            message = (
                f"Plan quality score {int(plan_quality.get('score', 0))} "
                f"below threshold {threshold} after {attempts_used} planning attempt(s). "
                "Refine planning before execution."
            )
            self._telemetry.event(
                "plan_quality_rejected",
                {
                    "goal": goal,
                    "message": message,
                    "plan_quality": plan_quality,
                    "planner_model_used": self._config.planner_model,
                    "coder_model_used": self._config.coder_model,
                    "critic_model_used": self._config.critic_model,
                    "tdd_mode": tdd_mode,
                    **project_meta,
                },
            )
            self._memory.append_lessons(
                goal=goal,
                lessons=[
                    LessonProposal(
                        lesson="Plan quality gate blocked execution; strengthen objective checks and risk coverage before coding.",
                        tags=["planning", "quality", "safety"],
                    )
                ],
                context=message,
            )
            self._telemetry.event(
                "run_complete",
                {
                    "goal": goal,
                    "success": False,
                    "iterations_used": 0,
                    "planner_model_used": self._config.planner_model,
                    "coder_model_used": self._config.coder_model,
                    "critic_model_used": self._config.critic_model,
                    "tdd_mode": tdd_mode,
                    "iterations_until_green": iterations_until_green,
                    "plan_quality": plan_quality,
                    **project_meta,
                },
            )
            return RunSummary(
                goal=goal,
                success=False,
                iterations_used=0,
                message=message,
            )

        critic_feedback = "No critic feedback yet."
        for iteration in range(1, iteration_limit + 1):
            started = time.perf_counter()
            workspace_snapshot = workspace.snapshot()
            base_memory_context, memory_meta = self._memory.render_context_and_meta(goal)
            if memory_meta:
                self._telemetry.event(
                    "memory_context_injected",
                    {
                        "goal": goal,
                        "iteration": iteration,
                        "lessons_count": len(memory_meta),
                        "lessons_used": memory_meta,
                        **project_meta,
                    },
                )
            log_context = self._build_goal_log_context()
            memory_context = self._compose_goal_context(base_memory_context, log_context)
            tdd_phase = "implementation" if (tdd_mode and tdd_red_phase_complete) else ("tests_first" if tdd_mode else "normal")

            coder_output = self._coder.propose(
                goal=goal,
                plan_json=plan_payload,
                workspace_snapshot=workspace_snapshot,
                memory_context=memory_context,
                critic_feedback=critic_feedback,
                iteration=iteration,
                tdd_mode=tdd_mode,
                tdd_phase=tdd_phase,
            )
            self._telemetry.event(
                "coder_output",
                {
                    "iteration": iteration,
                    "summary": coder_output.summary,
                    "edit_count": len(coder_output.edits),
                    "commands": coder_output.commands,
                    "done": coder_output.done,
                    "planner_model_used": self._config.planner_model,
                    "coder_model_used": self._config.coder_model,
                    "critic_model_used": self._config.critic_model,
                    "tdd_mode": tdd_mode,
                    "tdd_phase": tdd_phase,
                    **project_meta,
                },
            )

            try:
                validated_edits = safety.validate_edits(coder_output.edits)
                if tdd_mode and not tdd_red_phase_complete:
                    has_tests_edit, has_non_test_edit = self._summarize_tdd_test_edits(validated_edits)
                    if not has_tests_edit or has_non_test_edit:
                        reason = (
                            "TDD mode requires tests-first edits under tests/ in the active project before implementation. "
                            "Only test files are allowed until a failing pytest run is observed."
                        )
                        critic_feedback = reason
                        self._telemetry.event(
                            "tdd_violation",
                            {
                                "iteration": iteration,
                                "reason": reason,
                                "has_tests_edit": has_tests_edit,
                                "has_non_test_edit": has_non_test_edit,
                                **project_meta,
                            },
                        )
                        self._record_iteration_metric(
                            iteration=iteration,
                            status="retry",
                            commands_total=0,
                            commands_passed=0,
                            started=started,
                        )
                        self._memory.append_session_hint(
                            goal,
                            "TDD: write tests under tests/ before any implementation edits.",
                            tags=["tdd", "testing"],
                        )
                        continue
                written_paths = safety.apply_edits(validated_edits)
            except SafetyError as exc:
                reason = f"Safety guard rejected edits: {exc}"
                critic_feedback = reason
                self._telemetry.event(
                    "safety_violation",
                    {
                        "iteration": iteration,
                        "error": str(exc),
                        **project_meta,
                    },
                )
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=0,
                    commands_passed=0,
                    started=started,
                )
                self._memory.append_session_hint(
                    goal,
                    f"Safety rejected edits: {str(exc)[:120]}",
                    tags=["safety", "files"],
                )
                continue

            try:
                commands_to_run = self._prepare_commands_for_iteration(coder_output.commands, tdd_mode=tdd_mode)
                command_specs = safety.validate_commands(commands_to_run)
            except SafetyError as exc:
                reason = f"Safety guard rejected commands: {exc}"
                critic_feedback = reason
                self._telemetry.event(
                    "safety_violation",
                    {
                        "iteration": iteration,
                        "error": str(exc),
                        **project_meta,
                    },
                )
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=0,
                    commands_passed=0,
                    started=started,
                )
                self._memory.append_session_hint(
                    goal,
                    f"Safety rejected commands: {str(exc)[:120]}",
                    tags=["safety", "execution"],
                )
                continue

            if not command_specs:
                reason = "No validation commands were proposed. At least one allowed command is required."
                critic_feedback = reason
                self._telemetry.event(
                    "execution_skipped",
                    {
                        "iteration": iteration,
                        "error": reason,
                        **project_meta,
                    },
                )
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=0,
                    commands_passed=0,
                    started=started,
                )
                self._memory.append_session_hint(
                    goal,
                    "No validation commands proposed — include at least one pytest command.",
                    tags=["testing", "discipline"],
                )
                continue

            execution_results = executor.run(command_specs)
            pytest_results = self._extract_pytest_results(execution_results)
            tests_ran = bool(pytest_results)
            tests_passed = bool(pytest_results) and all(
                item.returncode == 0 and not item.timed_out for item in pytest_results
            )
            tests_failed = tests_ran and not tests_passed

            if tdd_mode and not tests_ran:
                reason = "TDD mode requires pytest execution in every iteration."
                critic_feedback = reason
                self._telemetry.event(
                    "tdd_violation",
                    {
                        "iteration": iteration,
                        "reason": reason,
                        **project_meta,
                    },
                )
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=len(execution_results),
                    commands_passed=self._count_passed_commands(execution_results),
                    started=started,
                )
                self._memory.append_session_hint(
                    goal,
                    "TDD: every iteration must run pytest to observe red/green feedback.",
                    tags=["tdd", "testing"],
                )
                continue

            critic_output = self._critic.review(
                goal=goal,
                plan_json=plan_payload,
                coder_json=coder_output.to_dict(),
                execution_results=execution_results,
                tdd_mode=tdd_mode,
                tdd_red_phase_complete=tdd_red_phase_complete,
            )

            self._memory.append_lessons(goal=goal, lessons=critic_output.lessons, context=critic_output.analysis)

            commands_passed = self._count_passed_commands(execution_results)
            iteration_status = critic_output.status
            if tdd_mode and not tdd_red_phase_complete:
                if tests_failed:
                    tdd_red_phase_complete = True
                    iteration_status = "retry"
                    critic_feedback = (
                        "TDD red phase complete. Keep tests and implement minimal code to make them pass."
                    )
                    self._telemetry.event(
                        "tdd_red_phase_complete",
                        {"iteration": iteration, "commands_total": len(execution_results), **project_meta},
                    )
                else:
                    iteration_status = "retry"
                    critic_feedback = (
                        "TDD mode expects failing tests before implementation. Strengthen tests first."
                    )
                    self._telemetry.event(
                        "tdd_violation",
                        {
                            "iteration": iteration,
                            "reason": "Tests passed before observing required red phase.",
                            **project_meta,
                        },
                    )

            self._record_iteration_metric(
                iteration=iteration,
                status=iteration_status,
                commands_total=len(execution_results),
                commands_passed=commands_passed,
                started=started,
            )

            self._telemetry.event(
                "iteration_complete",
                {
                    "iteration": iteration,
                    "status": iteration_status,
                    "written_paths": written_paths,
                    "commands_passed": commands_passed,
                    "commands_total": len(execution_results),
                    "analysis": critic_output.analysis,
                    "planner_model_used": self._config.planner_model,
                    "coder_model_used": self._config.coder_model,
                    "critic_model_used": self._config.critic_model,
                    "tdd_mode": tdd_mode,
                    "tdd_red_phase_complete": tdd_red_phase_complete,
                    **project_meta,
                },
            )

            if (
                self._is_success(critic_output, coder_output.done, execution_results)
                and (not tdd_mode or (tdd_red_phase_complete and tests_passed))
            ):
                if tdd_mode and iterations_until_green is None:
                    iterations_until_green = iteration
                git_result = None
                if git_committer is not None:
                    commit_msg = build_commit_message(goal, iteration, coder_output.summary)
                    git_result = git_committer.commit(commit_msg)
                    self._telemetry.event(
                        "git_auto_commit",
                        {
                            "iteration": iteration,
                            "success": git_result.success,
                            "skipped": git_result.skipped,
                            "sha": git_result.sha,
                            "message": git_result.message,
                            **project_meta,
                        },
                    )
                self._telemetry.event(
                    "run_complete",
                    {
                        "goal": goal,
                        "success": True,
                        "iterations_used": iteration,
                        "planner_model_used": self._config.planner_model,
                        "coder_model_used": self._config.coder_model,
                        "critic_model_used": self._config.critic_model,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                        "git_commit_sha": git_result.sha if git_result else None,
                        **project_meta,
                    },
                )
                self._memory.reinforce_lessons(goal, "success", since_iso=run_started_at)
                return RunSummary(
                    goal=goal,
                    success=True,
                    iterations_used=iteration,
                    message=critic_output.analysis,
                )

            if critic_output.status == "abort":
                self._telemetry.event(
                    "run_complete",
                    {
                        "goal": goal,
                        "success": False,
                        "iterations_used": iteration,
                        "planner_model_used": self._config.planner_model,
                        "coder_model_used": self._config.coder_model,
                        "critic_model_used": self._config.critic_model,
                        "tdd_mode": tdd_mode,
                        "iterations_until_green": iterations_until_green,
                        **project_meta,
                    },
                )
                self._memory.reinforce_lessons(goal, "failure", since_iso=run_started_at)
                return RunSummary(
                    goal=goal,
                    success=False,
                    iterations_used=iteration,
                    message=critic_output.analysis,
                )

            if not (tdd_mode and not tdd_red_phase_complete):
                critic_feedback = self._render_feedback(critic_output, execution_results)

        self._telemetry.event(
            "run_complete",
            {
                "goal": goal,
                "success": False,
                "iterations_used": iteration_limit,
                "planner_model_used": self._config.planner_model,
                "coder_model_used": self._config.coder_model,
                "critic_model_used": self._config.critic_model,
                "tdd_mode": tdd_mode,
                "iterations_until_green": iterations_until_green,
                **project_meta,
            },
        )
        self._memory.reinforce_lessons(goal, "failure", since_iso=run_started_at)
        return RunSummary(
            goal=goal,
            success=False,
            iterations_used=iteration_limit,
            message="Iteration limit reached before meeting success criteria.",
        )

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

    def _record_iteration_metric(
        self,
        iteration: int,
        status: str,
        commands_total: int,
        commands_passed: int,
        started: float,
    ) -> None:
        duration = round(time.perf_counter() - started, 3)
        self._telemetry.metric(
            IterationMetric(
                iteration=iteration,
                status=status,
                duration_sec=duration,
                commands_total=commands_total,
                commands_passed=commands_passed,
            )
        )

    @staticmethod
    def _contains_sensitive_log_text(text: str) -> bool:
        lowered = str(text or "").casefold()
        return any(
            marker in lowered
            for marker in (
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
        )

    @classmethod
    def _compose_goal_context(cls, memory_context: str, log_context: str) -> str:
        base = str(memory_context or "").strip() or "No prior lessons available."
        logs = str(log_context or "").strip()
        if not logs:
            return base
        return (
            f"{base}\n\nRecent tail logs context:\n"
            f"{logs}\n\n"
            "Use logs to diagnose failures and prioritize minimal fixes related to observed errors."
        ).strip()

    def _build_goal_log_context(self, *, limit_lines: int = 160, max_chars: int = 7000) -> str:
        files = [
            self._config.logs_dir / "telemetry.jsonl",
            self._config.logs_dir / "web_control_center.log",
        ]
        critical_markers = ("error", "traceback", "exception", "failed", "failure", "timeout")
        selected: list[str] = []
        seen: set[str] = set()

        def _append(prefix: str, line: str) -> None:
            clean = str(line).strip()
            if not clean or self._contains_sensitive_log_text(clean):
                return
            row = f"[{prefix}] {clean}"
            if row in seen:
                return
            seen.add(row)
            selected.append(row)

        for path in files:
            if not path.exists():
                continue
            try:
                rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            name = path.name
            tail = rows[-max(30, min(limit_lines, 500)) :]
            for row in tail:
                lowered = str(row).casefold()
                if any(marker in lowered for marker in critical_markers):
                    _append(name, row)
            for row in tail[-40:]:
                _append(name, row)

        if not selected:
            return ""
        text = "\n".join(selected[-max(20, min(limit_lines, 220)) :])
        if len(text) > max_chars:
            text = f"...[truncated]\n{text[-max_chars:]}"
        return text

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
    def _is_success(critic: CriticOutput, coder_done: bool, results: list[ExecutionResult]) -> bool:
        commands_ok = bool(results) and all(item.returncode == 0 and not item.timed_out for item in results)
        if critic.status == "success" and commands_ok:
            return True
        return coder_done and commands_ok
