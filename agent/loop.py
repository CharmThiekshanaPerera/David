from __future__ import annotations

import time
from dataclasses import dataclass

from agent.coder import Coder
from agent.config import AgentConfig
from agent.contracts import CriticOutput, ExecutionResult, LessonProposal
from agent.critic import Critic
from agent.executor import RestrictedExecutor
from agent.llm import OllamaClient
from agent.memory import LongTermMemory
from agent.planner import Planner
from agent.safety import SafetyError, SafetyGuard
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

        self._planner = Planner(llm)
        self._coder = Coder(llm)
        self._critic = Critic(llm)
        self._safety = SafetyGuard(
            workspace_dir=config.workspace_dir,
            max_file_write_bytes=config.max_file_write_bytes,
            max_total_write_bytes=config.max_total_write_bytes,
            allowed_commands=config.allowed_commands,
        )
        self._executor = RestrictedExecutor(
            workspace_dir=config.workspace_dir,
            timeout_sec=config.command_timeout_sec,
            max_output_chars=config.max_command_output_chars,
        )
        self._memory = LongTermMemory(config.memory_file)
        self._workspace = WorkspaceInspector(config.workspace_dir)
        self._telemetry = TelemetryLogger(config.logs_dir)

    def run(self, goal: str, max_iterations: int | None = None) -> RunSummary:
        iteration_limit = max_iterations or self._config.max_iterations

        initial_snapshot = self._workspace.snapshot()
        memory_context = self._memory.render_context(goal)
        plan = self._planner.create_plan(goal=goal, workspace_snapshot=initial_snapshot, memory_context=memory_context)

        self._telemetry.event("plan_created", {"goal": goal, "plan": plan.to_dict()})

        critic_feedback = "No critic feedback yet."
        for iteration in range(1, iteration_limit + 1):
            started = time.perf_counter()
            workspace_snapshot = self._workspace.snapshot()
            memory_context = self._memory.render_context(goal)

            coder_output = self._coder.propose(
                goal=goal,
                plan_json=plan.to_dict(),
                workspace_snapshot=workspace_snapshot,
                memory_context=memory_context,
                critic_feedback=critic_feedback,
                iteration=iteration,
            )
            self._telemetry.event(
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
                validated_edits = self._safety.validate_edits(coder_output.edits)
                written_paths = self._safety.apply_edits(validated_edits)
            except SafetyError as exc:
                reason = f"Safety guard rejected edits: {exc}"
                critic_feedback = reason
                self._telemetry.event("safety_violation", {"iteration": iteration, "error": str(exc)})
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=0,
                    commands_passed=0,
                    started=started,
                )
                self._memory.append_lessons(
                    goal=goal,
                    lessons=[
                        LessonProposal(
                            lesson="Safety validation must pass before any file write.",
                            tags=["safety", "files"],
                        )
                    ],
                    context=reason,
                )
                continue

            try:
                command_specs = self._safety.validate_commands(coder_output.commands)
            except SafetyError as exc:
                reason = f"Safety guard rejected commands: {exc}"
                critic_feedback = reason
                self._telemetry.event("safety_violation", {"iteration": iteration, "error": str(exc)})
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=0,
                    commands_passed=0,
                    started=started,
                )
                self._memory.append_lessons(
                    goal=goal,
                    lessons=[
                        LessonProposal(
                            lesson="Command execution must stay inside the allow-list.",
                            tags=["safety", "execution"],
                        )
                    ],
                    context=reason,
                )
                continue

            if not command_specs:
                reason = "No validation commands were proposed. At least one allowed command is required."
                critic_feedback = reason
                self._telemetry.event("execution_skipped", {"iteration": iteration, "error": reason})
                self._record_iteration_metric(
                    iteration=iteration,
                    status="retry",
                    commands_total=0,
                    commands_passed=0,
                    started=started,
                )
                self._memory.append_lessons(
                    goal=goal,
                    lessons=[
                        LessonProposal(
                            lesson="Every iteration must include at least one validation command.",
                            tags=["testing", "discipline"],
                        )
                    ],
                    context=reason,
                )
                continue

            execution_results = self._executor.run(command_specs)
            critic_output = self._critic.review(
                goal=goal,
                plan_json=plan.to_dict(),
                coder_json=coder_output.to_dict(),
                execution_results=execution_results,
            )

            self._memory.append_lessons(goal=goal, lessons=critic_output.lessons, context=critic_output.analysis)

            commands_passed = self._count_passed_commands(execution_results)
            self._record_iteration_metric(
                iteration=iteration,
                status=critic_output.status,
                commands_total=len(execution_results),
                commands_passed=commands_passed,
                started=started,
            )

            self._telemetry.event(
                "iteration_complete",
                {
                    "iteration": iteration,
                    "status": critic_output.status,
                    "written_paths": written_paths,
                    "commands_passed": commands_passed,
                    "commands_total": len(execution_results),
                    "analysis": critic_output.analysis,
                },
            )

            if self._is_success(critic_output, coder_output.done, execution_results):
                return RunSummary(
                    goal=goal,
                    success=True,
                    iterations_used=iteration,
                    message=critic_output.analysis,
                )

            if critic_output.status == "abort":
                return RunSummary(
                    goal=goal,
                    success=False,
                    iterations_used=iteration,
                    message=critic_output.analysis,
                )

            critic_feedback = self._render_feedback(critic_output, execution_results)

        return RunSummary(
            goal=goal,
            success=False,
            iterations_used=iteration_limit,
            message="Iteration limit reached before meeting success criteria.",
        )

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
