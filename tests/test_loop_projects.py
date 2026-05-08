from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.contracts import CodeEdit, CoderOutput, CriticOutput, ExecutionResult, LessonProposal, PlanOutput, PlanStep
from agent.loop import DavidAgent


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


def _telemetry_events(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def test_loop_goal_writes_inside_project_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work", success_check="pytest")],
                success_criteria=["pytest passes"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(
            self,
            goal,
            plan_json,
            workspace_snapshot,
            memory_context,
            critic_feedback,
            iteration,
            tdd_mode=False,
            tdd_phase="normal",
        ):
            return CoderOutput(
                summary="add implementation",
                edits=[CodeEdit(path="src/app.py", content="def run():\n    return 'ok'\n", reason="implement")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    class FakeCritic:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def review(self, goal, plan_json, coder_json, execution_results, tdd_mode=False, tdd_red_phase_complete=False):
            return CriticOutput(
                status="success",
                analysis="done",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep changes focused", tags=["quality"])],
            )

    class FakeExecutor:
        def __init__(self, workspace_dir, timeout_sec, max_output_chars):
            self.workspace_dir = workspace_dir

        def run(self, command_specs):
            return [
                ExecutionResult(
                    command=spec.raw,
                    returncode=0,
                    stdout="ok",
                    stderr="",
                    timed_out=False,
                    duration_sec=0.01,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("agent.loop.Planner", FakePlanner)
    monkeypatch.setattr("agent.loop.Coder", FakeCoder)
    monkeypatch.setattr("agent.loop.Critic", FakeCritic)
    monkeypatch.setattr("agent.loop.RestrictedExecutor", FakeExecutor)

    agent = DavidAgent(config)
    summary = agent.run("Build Sample")

    assert summary.success is True
    assert not (config.workspace_dir / "src" / "app.py").exists()
    projects = sorted((config.workspace_dir / "projects").iterdir())
    assert projects
    project_dir = projects[0]
    assert (project_dir / "src" / "app.py").exists()

    active = json.loads((config.workspace_dir / "active_project.json").read_text(encoding="utf-8"))
    assert Path(active["project_path"]) == project_dir
    assert active["project_slug"] == project_dir.name

    events = _telemetry_events(config.logs_dir / "telemetry.jsonl")
    run_complete = [row for row in events if row.get("event_type") == "run_complete"]
    assert run_complete
    payload = run_complete[-1]["payload"]
    assert payload["project_slug"] == project_dir.name
    assert payload["project_path"] == str(project_dir)
    assert payload["project_created_new"] is True


def test_loop_includes_tail_logs_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    (config.logs_dir / "web_control_center.log").write_text(
        "WARN stale cache\nERROR runtime failure: missing dependency\n",
        encoding="utf-8",
    )
    captured: dict[str, str] = {"planner": "", "coder": ""}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            captured["planner"] = str(memory_context)
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work", success_check="pytest")],
                success_criteria=["pytest passes"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(
            self,
            goal,
            plan_json,
            workspace_snapshot,
            memory_context,
            critic_feedback,
            iteration,
            tdd_mode=False,
            tdd_phase="normal",
        ):
            captured["coder"] = str(memory_context)
            return CoderOutput(
                summary="add implementation",
                edits=[CodeEdit(path="src/app.py", content="def run():\n    return 'ok'\n", reason="implement")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    class FakeCritic:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def review(self, goal, plan_json, coder_json, execution_results, tdd_mode=False, tdd_red_phase_complete=False):
            return CriticOutput(
                status="success",
                analysis="done",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep changes focused", tags=["quality"])],
            )

    class FakeExecutor:
        def __init__(self, workspace_dir, timeout_sec, max_output_chars):
            self.workspace_dir = workspace_dir

        def run(self, command_specs):
            return [
                ExecutionResult(
                    command=spec.raw,
                    returncode=0,
                    stdout="ok",
                    stderr="",
                    timed_out=False,
                    duration_sec=0.01,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("agent.loop.Planner", FakePlanner)
    monkeypatch.setattr("agent.loop.Coder", FakeCoder)
    monkeypatch.setattr("agent.loop.Critic", FakeCritic)
    monkeypatch.setattr("agent.loop.RestrictedExecutor", FakeExecutor)

    agent = DavidAgent(config)
    summary = agent.run("Fix failures from logs")
    assert summary.success is True
    assert "Recent tail logs context:" in captured["planner"]
    assert "runtime failure: missing dependency" in captured["planner"]
    assert "Recent tail logs context:" in captured["coder"]


def test_loop_tdd_mode_places_tests_under_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    base = _make_config(tmp_path)
    config = replace(base, tdd_mode=True)
    state = {"calls": 0}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            assert tdd_mode is True
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="TDD", details="tests then code", success_check="green")],
                success_criteria=["tests fail then pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(
            self,
            goal,
            plan_json,
            workspace_snapshot,
            memory_context,
            critic_feedback,
            iteration,
            tdd_mode=False,
            tdd_phase="normal",
        ):
            assert tdd_mode is True
            if tdd_phase == "tests_first":
                return CoderOutput(
                    summary="tests first",
                    edits=[CodeEdit(path="tests/test_app.py", content="def test_demo():\n    assert False\n", reason="red")],
                    commands=["pytest -q"],
                    done=False,
                    done_reason="",
                )
            return CoderOutput(
                summary="implement",
                edits=[CodeEdit(path="src/app.py", content="def ok():\n    return True\n", reason="green")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    class FakeCritic:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def review(self, goal, plan_json, coder_json, execution_results, tdd_mode=False, tdd_red_phase_complete=False):
            return CriticOutput(
                status="retry",
                analysis="continue",
                next_actions=["next"],
                lessons=[LessonProposal(lesson="small TDD steps", tags=["tdd"])],
            )

    class FakeExecutor:
        def __init__(self, workspace_dir, timeout_sec, max_output_chars):
            self.workspace_dir = workspace_dir

        def run(self, command_specs):
            state["calls"] += 1
            failing = state["calls"] == 1
            return [
                ExecutionResult(
                    command=spec.raw,
                    returncode=1 if ("pytest" in spec.raw and failing) else 0,
                    stdout="",
                    stderr="AssertionError" if ("pytest" in spec.raw and failing) else "",
                    timed_out=False,
                    duration_sec=0.01,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("agent.loop.Planner", FakePlanner)
    monkeypatch.setattr("agent.loop.Coder", FakeCoder)
    monkeypatch.setattr("agent.loop.Critic", FakeCritic)
    monkeypatch.setattr("agent.loop.RestrictedExecutor", FakeExecutor)

    agent = DavidAgent(config)
    summary = agent.run("Use strict TDD")

    assert summary.success is True
    project_dir = sorted((config.workspace_dir / "projects").iterdir())[0]
    assert (project_dir / "tests" / "test_app.py").exists()
    assert (project_dir / "src" / "app.py").exists()
    assert not (config.workspace_dir / "tests" / "test_app.py").exists()


def test_loop_plan_quality_threshold_blocks_execution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    base = _make_config(tmp_path)
    config = replace(base, plan_quality_threshold=90)
    state = {"planner_calls": 0, "coder_calls": 0}

    class WeakPlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            state["planner_calls"] += 1
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="Done.")],
                success_criteria=["looks good"],
            )

    class FastCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(
            self,
            goal,
            plan_json,
            workspace_snapshot,
            memory_context,
            critic_feedback,
            iteration,
            tdd_mode=False,
            tdd_phase="normal",
        ):
            state["coder_calls"] += 1
            return CoderOutput(
                summary="should not execute",
                edits=[CodeEdit(path="src/app.py", content="print('x')\n", reason="noop")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    monkeypatch.setattr("agent.loop.Planner", WeakPlanner)
    monkeypatch.setattr("agent.loop.Coder", FastCoder)

    agent = DavidAgent(config)
    summary = agent.run("Block weak plan")

    assert summary.success is False
    assert summary.iterations_used == 0
    assert state["planner_calls"] == 2
    assert state["coder_calls"] == 0

    events = _telemetry_events(config.logs_dir / "telemetry.jsonl")
    event_types = [str(row.get("event_type", "")) for row in events]
    assert "plan_quality_scored" in event_types
    assert "plan_quality_replan_requested" in event_types
    assert "plan_quality_rejected" in event_types


def test_loop_plan_quality_replan_allows_execution_when_second_plan_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = _make_config(tmp_path)
    config = replace(base, plan_quality_threshold=85)
    state = {"planner_calls": 0, "coder_calls": 0}

    class RecoveringPlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            state["planner_calls"] += 1
            if state["planner_calls"] == 1:
                return PlanOutput(
                    goal=goal,
                    steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="Done.")],
                    success_criteria=["looks good"],
                )
            return PlanOutput(
                goal=goal,
                steps=[
                    PlanStep(
                        id="S1",
                        title="Define tests first",
                        details="Create tests under tests/ that verify expected behavior and failure cases before implementation.",
                        success_check="pytest -q reports failing tests before code changes.",
                    ),
                    PlanStep(
                        id="S2",
                        title="Implement minimal code in scope",
                        details="Update only project files inside workspace boundaries and avoid unrelated edits.",
                        success_check="Implementation changes are limited and validated by pytest exit code.",
                    ),
                    PlanStep(
                        id="S3",
                        title="Validate and guard risk",
                        details="Run pytest and enforce command limits, timeout checks, and approval or rollback safeguards.",
                        success_check="pytest exits with code 0 and safety checks pass without violations.",
                    ),
                ],
                success_criteria=[
                    "pytest -q exits with code 0.",
                    "All edits stay in workspace scope with safety validation.",
                    "Rollback or approval safeguard exists for risky changes.",
                ],
            )

    class FastCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(
            self,
            goal,
            plan_json,
            workspace_snapshot,
            memory_context,
            critic_feedback,
            iteration,
            tdd_mode=False,
            tdd_phase="normal",
        ):
            state["coder_calls"] += 1
            return CoderOutput(
                summary="implement",
                edits=[CodeEdit(path="src/app.py", content="def run():\n    return 'ok'\n", reason="implement")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    class FastCritic:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def review(self, goal, plan_json, coder_json, execution_results, tdd_mode=False, tdd_red_phase_complete=False):
            return CriticOutput(
                status="success",
                analysis="done",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="use quality feedback loops", tags=["planning"])],
            )

    class FastExecutor:
        def __init__(self, workspace_dir, timeout_sec, max_output_chars):
            self.workspace_dir = workspace_dir

        def run(self, command_specs):
            return [
                ExecutionResult(
                    command=spec.raw,
                    returncode=0,
                    stdout="ok",
                    stderr="",
                    timed_out=False,
                    duration_sec=0.01,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("agent.loop.Planner", RecoveringPlanner)
    monkeypatch.setattr("agent.loop.Coder", FastCoder)
    monkeypatch.setattr("agent.loop.Critic", FastCritic)
    monkeypatch.setattr("agent.loop.RestrictedExecutor", FastExecutor)

    agent = DavidAgent(config)
    summary = agent.run("Recover from weak initial plan")

    assert summary.success is True
    assert summary.iterations_used == 1
    assert state["planner_calls"] == 2
    assert state["coder_calls"] == 1

    events = _telemetry_events(config.logs_dir / "telemetry.jsonl")
    event_types = [str(row.get("event_type", "")) for row in events]
    assert "plan_quality_replan_requested" in event_types
    assert "plan_quality_rejected" not in event_types
