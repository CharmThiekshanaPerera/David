from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.contracts import CodeEdit, CoderOutput, CriticOutput, ExecutionResult, LessonProposal, PlanOutput, PlanStep
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


def _wait_for_terminal(center: DavidControlCenter, run_id: str, timeout_sec: float = 6.0) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        payload = center.get_run(run_id)
        if not payload:
            time.sleep(0.05)
            continue
        status = str(payload.get("meta", {}).get("status", ""))
        if status in {"success", "failed", "rejected", "stopped", "preview_ready"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not reach terminal status in time.")


def test_per_role_model_override_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    seen: dict[str, str | None] = {"planner": None, "coder": None, "critic": None}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            seen["planner"] = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[
                    PlanStep(id="S1", title="Plan", details="Do work.", success_check="tests pass"),
                ],
                success_criteria=["tests pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            seen["coder"] = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    class FakeCritic:
        def __init__(self, _llm, model_name=None):
            seen["critic"] = model_name

        def review(self, goal, plan_json, coder_json, execution_results, tdd_mode=False, tdd_red_phase_complete=False):
            return CriticOutput(
                status="success",
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep tests green", tags=["testing"])],
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

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run(
        {
            "command": "/goal build sample",
            "planner_model": "llama3.2:3b",
            "coder_model": "qwen2.5-coder:1.5b",
            "critic_model": "deepseek-r1:7b",
            "tdd_mode": False,
        }
    )
    assert ok is True

    run = _wait_for_terminal(center, start["run_id"])
    meta = run["meta"]
    assert meta["status"] == "success"
    assert meta["planner_model_used"] == "llama3.2:3b"
    assert meta["coder_model_used"] == "qwen2.5-coder:1.5b"
    assert meta["critic_model_used"] == "deepseek-r1:7b"
    assert str(meta.get("project_slug", "")).startswith("build_sample")
    project_path = Path(str(meta.get("project_path", "")))
    assert project_path.exists()
    assert (project_path / "app.py").exists()
    assert not (config.workspace_dir / "app.py").exists()
    assert seen == {
        "planner": "llama3.2:3b",
        "coder": "qwen2.5-coder:1.5b",
        "critic": "deepseek-r1:7b",
    }


def test_goal_uses_tail_logs_as_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    (config.logs_dir / "web_control_center.log").write_text(
        "INFO server boot\nERROR import failed in module sample_app\n",
        encoding="utf-8",
    )
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    captured: dict[str, str] = {"planner": "", "coder": ""}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            captured["planner"] = str(memory_context)
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="tests pass")],
                success_criteria=["tests pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            captured["coder"] = str(memory_context)
            return CoderOutput(
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
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
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep tests green", tags=["testing"])],
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

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run({"command": "/goal fix errors from logs"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])
    assert run["meta"]["status"] == "success"
    assert "Recent tail logs context:" in captured["planner"]
    assert "import failed in module sample_app" in captured["planner"]
    assert "Recent tail logs context:" in captured["coder"]


def test_goal_context_includes_reflections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["lessons"] = [
        {
            "timestamp_utc": "2026-02-01T00:00:00+00:00",
            "goal": "conversation:s_reflect",
            "lesson": "User prefers step-by-step explanations for better clarity.",
            "tags": ["reflection", "conversation", "preference"],
            "context": "session_id=s_reflect",
            "kind": "reflection",
            "source": "reflection_engine",
            "reflection_key": "conversation:user_msg_1",
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    captured: dict[str, str] = {"planner": ""}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            captured["planner"] = str(memory_context)
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="tests pass")],
                success_criteria=["tests pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
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
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep tests green", tags=["testing"])],
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

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run({"command": "/goal build feature with tests"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])
    assert run["meta"]["status"] == "success"
    assert "Reflection memory before planning:" in captured["planner"]
    assert "step-by-step explanations" in captured["planner"].lower()


def test_goal_context_includes_parent_teaching_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["values"] = [
        {
            "id": "v_1",
            "timestamp_utc": "2026-02-01T00:00:00+00:00",
            "category": "guideline",
            "category_label": "Guidelines",
            "principle": "Always value patience.",
            "application": "Investigate failing tests step by step before changing code.",
            "source": "parent_teaching_mode",
            "actor": "web_ui",
            "session_id": "session_parent_values",
            "message": "Always value patience.",
            "tags": ["parent_teaching", "guideline"],
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    captured: dict[str, str] = {"planner": "", "coder": ""}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            captured["planner"] = str(memory_context)
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="tests pass")],
                success_criteria=["tests pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            captured["coder"] = str(memory_context)
            return CoderOutput(
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
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
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep tests green", tags=["testing"])],
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

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run({"command": "/goal fix failing tests with patience"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])
    assert run["meta"]["status"] == "success"
    assert "Parent teachings (Values / Guidelines / Personal Philosophy):" in captured["planner"]
    assert "Always value patience." in captured["planner"]
    assert "never override safety constraints" in captured["planner"]
    assert "Parent teachings (Values / Guidelines / Personal Philosophy):" in captured["coder"]


def test_goal_run_records_reflection_lesson(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="tests pass")],
                success_criteria=["tests pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
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
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="keep tests green", tags=["testing"])],
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

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run({"command": "/goal capture reflection"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])
    assert run["meta"]["status"] == "success"

    payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    reflections = [
        row
        for row in payload.get("lessons", [])
        if isinstance(row, dict) and str(row.get("kind", "")).lower() == "reflection"
    ]
    assert any(str(row.get("run_id", "")) == start["run_id"] for row in reflections)
    assert any("Run completed successfully." in str(row.get("lesson", "")) for row in reflections)


def test_growth_timeline_aggregates_runs_and_memory(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["facts"] = [
        {
            "id": "f1",
            "subject": "User",
            "predicate": "favorite_style",
            "object": "step_by_step",
            "timestamp": "2026-02-01T00:00:00+00:00",
            "last_updated": "2026-02-01T00:00:00+00:00",
        }
    ]
    memory_payload["lessons"] = [
        {
            "timestamp_utc": "2026-02-02T00:00:00+00:00",
            "goal": "build task",
            "lesson": "Keep tests small and focused.",
            "tags": ["testing"],
            "context": "critic",
        },
        {
            "timestamp_utc": "2026-02-03T00:00:00+00:00",
            "goal": "run:demo",
            "lesson": "Run completed successfully. Tests passed. Longest iteration was #1 at ~0.02s.",
            "tags": ["reflection", "run", "success"],
            "context": "status=success",
            "kind": "reflection",
            "source": "reflection_engine",
            "reflection_key": "run:run_demo_1",
        },
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")

    run_dir = center.runs_root / "run_demo_1"
    (run_dir / "iterations" / "001").mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "run_demo_1",
                "mode": "goal",
                "payload": "Build demo",
                "status": "success",
                "started_at": "2026-02-03T00:00:00+00:00",
                "ended_at": "2026-02-03T00:01:00+00:00",
                "project_slug": "build_demo",
                "message": "All tests passed.",
                "tdd_mode": True,
                "iterations_until_green": 2,
                "iteration": 2,
                "tests_passed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "iterations" / "001" / "execution.json").write_text(
        json.dumps([{"duration_sec": 0.02, "command": "pytest -q", "returncode": 0, "timed_out": False}]) + "\n",
        encoding="utf-8",
    )

    timeline = center.growth_timeline(limit=120)
    summary = timeline["summary"]
    assert summary["goal_runs_total"] >= 1
    assert summary["goal_runs_success"] >= 1
    assert summary["tdd_success_count"] >= 1
    assert summary["memory_size_total"] >= 2
    assert any(item["category"] == "project_success" for item in timeline["milestones"])
    assert any(item["category"] == "lesson_reflection" for item in timeline["milestones"])


def test_goal_run_autonomous_self_improvement_proposal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="Do work.", success_check="tests pass")],
                success_criteria=["tests pass"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
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
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="Keep tests focused.", tags=["testing"])],
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
                    duration_sec=0.02,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run({"command": "/goal autonomous self-improvement proposal"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])
    assert run["meta"]["status"] == "success"

    deadline = time.time() + 2.0
    proposals = center.list_self_improvements(limit=50)
    while int(proposals.get("total", 0)) < 1 and time.time() < deadline:
        time.sleep(0.05)
        proposals = center.list_self_improvements(limit=50)
    assert int(proposals.get("total", 0)) >= 1
    assert int(proposals.get("autonomous_count", 0)) >= 1
    items = proposals.get("items", [])
    assert any(bool((row.get("metadata") or {}).get("autonomous", False)) for row in items if isinstance(row, dict))
    timeline = center.growth_timeline(limit=120)
    assert any(
        str(item.get("category", "")).startswith("autonomous_self_improvement")
        for item in timeline.get("milestones", [])
        if isinstance(item, dict)
    )


def test_tdd_mode_tests_first_then_green(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    executor_state = {"calls": 0}

    class FakePlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            assert tdd_mode is True
            return PlanOutput(
                goal=goal,
                steps=[
                    PlanStep(id="S1", title="Write tests", details="tests first", success_check="pytest fails first"),
                    PlanStep(id="S2", title="Implement", details="make tests pass", success_check="pytest green"),
                ],
                success_criteria=["tests-first then green"],
            )

    class FakeCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            assert tdd_mode is True
            if tdd_phase == "tests_first":
                return CoderOutput(
                    summary="add failing tests",
                    edits=[CodeEdit(path="tests/test_app.py", content="def test_demo():\n    assert False\n", reason="red")],
                    commands=["pytest -q"],
                    done=False,
                    done_reason="",
                )
            return CoderOutput(
                summary="implement",
                edits=[CodeEdit(path="app.py", content="def ok():\n    return True\n", reason="green")],
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
                analysis="iterate",
                next_actions=["continue"],
                lessons=[LessonProposal(lesson="small step", tags=["tdd"])],
            )

    class FakeExecutor:
        def __init__(self, workspace_dir, timeout_sec, max_output_chars):
            self.workspace_dir = workspace_dir

        def run(self, command_specs):
            executor_state["calls"] += 1
            failing = executor_state["calls"] == 1
            return [
                ExecutionResult(
                    command=spec.raw,
                    returncode=1 if ("pytest" in spec.raw and failing) else 0,
                    stdout="",
                    stderr="AssertionError" if ("pytest" in spec.raw and failing) else "",
                    timed_out=False,
                    duration_sec=0.02,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("web.control_center.Planner", FakePlanner)
    monkeypatch.setattr("web.control_center.Coder", FakeCoder)
    monkeypatch.setattr("web.control_center.Critic", FakeCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FakeExecutor)

    ok, start = center.start_run({"command": "/goal use strict tdd", "tdd_mode": True})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])
    meta = run["meta"]
    assert meta["status"] == "success"
    assert meta["tdd_mode"] is True
    assert meta["iterations_until_green"] == 2
    project_path = Path(str(meta.get("project_path", "")))
    assert project_path.exists()
    assert (project_path / "tests" / "test_app.py").exists()
    assert (project_path / "app.py").exists()
    assert not (config.workspace_dir / "tests" / "test_app.py").exists()

    iterations = run["iterations"]
    first_diff_paths = [row["path"] for row in iterations[0]["diffs"]]
    assert first_diff_paths == ["tests/test_app.py"]
    second_diff_paths = [row["path"] for row in iterations[1]["diffs"]]
    assert "app.py" in second_diff_paths


def test_template_injects_tdd_flag_and_goal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    class FastPlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="One step", success_check="ok")],
                success_criteria=["ok"],
            )

    class FastCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            path = "tests/test_template.py" if tdd_mode and tdd_phase == "tests_first" else "template.py"
            done = bool(tdd_mode and tdd_phase != "tests_first")
            return CoderOutput(
                summary="template run",
                edits=[CodeEdit(path=path, content="pass\n", reason="template")],
                commands=["pytest -q"],
                done=done,
                done_reason="",
            )

    class FastCritic:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def review(self, goal, plan_json, coder_json, execution_results, tdd_mode=False, tdd_red_phase_complete=False):
            return CriticOutput(
                status="retry",
                analysis="retry",
                next_actions=["continue"],
                lessons=[LessonProposal(lesson="template", tags=["template"])],
            )

    class FastExecutor:
        def __init__(self, workspace_dir, timeout_sec, max_output_chars):
            self.calls = 0

        def run(self, command_specs):
            self.calls += 1
            # Force red then green for strict TDD template.
            failing = self.calls == 1
            return [
                ExecutionResult(
                    command=spec.raw,
                    returncode=1 if ("pytest" in spec.raw and failing) else 0,
                    stdout="",
                    stderr="AssertionError" if failing else "",
                    timed_out=False,
                    duration_sec=0.01,
                )
                for spec in command_specs
            ]

    monkeypatch.setattr("web.control_center.Planner", FastPlanner)
    monkeypatch.setattr("web.control_center.Coder", FastCoder)
    monkeypatch.setattr("web.control_center.Critic", FastCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FastExecutor)

    ok, started = center.start_run({"mode": "goal", "template_id": "strict_tdd_mode"})
    assert ok is True
    assert started["template_id"] == "strict_tdd_mode"
    assert started["tdd_mode"] is True

    run = _wait_for_terminal(center, started["run_id"])
    meta = run["meta"]
    assert meta["template_id"] == "strict_tdd_mode"
    assert meta["tdd_mode"] is True
    assert "strict TDD" in meta["payload"]
    assert str(meta.get("project_slug", "")).startswith("use_strict_tdd")
    assert Path(str(meta.get("project_path", ""))).exists()


def test_start_run_rejects_invalid_model_name(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    ok, payload = center.start_run({"command": "/goal test", "planner_model": "bad model; rm -rf /"})
    assert ok is False
    assert "invalid characters" in str(payload.get("error", "")).lower()


def test_goal_run_targets_selected_workspace_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    target_dir = config.workspace_dir / "projects" / "existing_app"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "README.md").write_text("# Existing App\n", encoding="utf-8")

    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    class FastPlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="One step", success_check="ok")],
                success_criteria=["ok"],
            )

    class FastCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="targeted run",
                edits=[CodeEdit(path="main.py", content="print('targeted')\n", reason="implement")],
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
                lessons=[LessonProposal(lesson="targeted", tags=["workspace"])],
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

    monkeypatch.setattr("web.control_center.Planner", FastPlanner)
    monkeypatch.setattr("web.control_center.Coder", FastCoder)
    monkeypatch.setattr("web.control_center.Critic", FastCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FastExecutor)

    ok, started = center.start_run(
        {
            "mode": "goal",
            "payload": "Add one entry-point file.",
            "workspace_target_path": "projects/existing_app",
        }
    )
    assert ok is True

    run = _wait_for_terminal(center, started["run_id"])
    meta = run["meta"]
    assert meta["status"] == "success"
    assert meta["project_created_new"] is False
    assert meta["workspace_target_path"] == "projects/existing_app"
    assert meta["workspace_target_type"] == "folder"
    assert meta["project_path"] == str(target_dir)
    assert (target_dir / "main.py").exists()


def test_goal_run_updates_project_brain_memory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    class FastPlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Create CLI module", details="Add entry point", success_check="ok")],
                success_criteria=["ok"],
            )

    class FastCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="project brain seed",
                edits=[
                    CodeEdit(path="main.py", content="print('hello')\n", reason="entry"),
                    CodeEdit(path="tests/test_main.py", content="def test_ok():\n    assert True\n", reason="tests"),
                ],
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
                analysis="Project completed with passing tests.",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="Watch edge-case validation.", tags=["testing", "edge-case"])],
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

    monkeypatch.setattr("web.control_center.Planner", FastPlanner)
    monkeypatch.setattr("web.control_center.Coder", FastCoder)
    monkeypatch.setattr("web.control_center.Critic", FastCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FastExecutor)

    ok, started = center.start_run({"command": "/goal build project brain sample"})
    assert ok is True
    run = _wait_for_terminal(center, started["run_id"])
    assert run["meta"]["status"] == "success"

    payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    projects = payload.get("projects", [])
    assert isinstance(projects, list)
    assert projects
    entry = projects[-1]
    assert str(entry.get("project_relative_path", "")).startswith("projects/")
    assert str(entry.get("architecture_summary", "")).strip()
    assert isinstance(entry.get("key_design_decisions"), list)
    assert entry.get("key_design_decisions")
    assert "test" in str(entry.get("testing_approach", "")).lower()
    assert isinstance(entry.get("known_weaknesses"), list)
    assert entry.get("known_weaknesses")


def test_goal_context_includes_project_brain_for_revisit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    target_dir = config.workspace_dir / "projects" / "existing_app"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "main.py").write_text("print('existing')\n", encoding="utf-8")
    (target_dir / "tests").mkdir(parents=True, exist_ok=True)
    (target_dir / "tests" / "test_main.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    memory_payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
    memory_payload["projects"] = [
        {
            "id": "project_memory_existing_app",
            "created_at": "2026-02-01T00:00:00+00:00",
            "last_updated": "2026-02-01T00:00:00+00:00",
            "project_slug": "existing_app",
            "project_path": str(target_dir),
            "project_relative_path": "projects/existing_app",
            "architecture_summary": "modular CLI structure with JSON storage and dedicated tests",
            "key_design_decisions": ["Planned around: Keep modules isolated."],
            "testing_approach": "Pytest tests under tests/ with iterative command validation.",
            "known_weaknesses": ["Edge-case validation needed improvement."],
            "last_goal": "Earlier revisit",
            "last_run_id": "run_prev",
            "last_status": "success",
            "last_message": "done",
            "source": "project_brain_engine",
            "history": [],
        }
    ]
    config.memory_file.write_text(json.dumps(memory_payload) + "\n", encoding="utf-8")
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    captured: dict[str, str] = {"planner": ""}

    class FastPlanner:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def create_plan(self, goal, workspace_snapshot, memory_context, tdd_mode=False):
            captured["planner"] = str(memory_context)
            return PlanOutput(
                goal=goal,
                steps=[PlanStep(id="S1", title="Plan", details="One step", success_check="ok")],
                success_criteria=["ok"],
            )

    class FastCoder:
        def __init__(self, _llm, model_name=None):
            self.model_name = model_name

        def propose(self, goal, plan_json, workspace_snapshot, memory_context, critic_feedback, iteration, tdd_mode=False, tdd_phase="normal"):
            return CoderOutput(
                summary="targeted run",
                edits=[CodeEdit(path="main.py", content="print('targeted')\n", reason="implement")],
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
                lessons=[LessonProposal(lesson="targeted", tags=["workspace"])],
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

    monkeypatch.setattr("web.control_center.Planner", FastPlanner)
    monkeypatch.setattr("web.control_center.Coder", FastCoder)
    monkeypatch.setattr("web.control_center.Critic", FastCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FastExecutor)

    ok, started = center.start_run(
        {
            "mode": "goal",
            "payload": "Revisit existing app and improve validation.",
            "workspace_target_path": "projects/existing_app",
        }
    )
    assert ok is True
    run = _wait_for_terminal(center, started["run_id"])
    assert run["meta"]["status"] == "success"
    assert "Project Brain recall:" in captured["planner"]
    assert "modular CLI structure with JSON storage" in captured["planner"]
    assert "Edge-case validation needed improvement." in captured["planner"]


def test_get_run_files_syncs_full_workspace_listing(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")

    project_root = config.workspace_dir / "projects" / "demo_project"
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (project_root / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (config.workspace_dir / "templates" / "base.txt").write_text("template\n", encoding="utf-8")

    run_dir = (tmp_path / "data" / "runs" / "run_test_files")
    iter_dir = run_dir / "iterations" / "001"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps({"id": "run_test_files", "project_slug": "demo_project", "project_path": str(project_root)}) + "\n",
        encoding="utf-8",
    )
    (iter_dir / "diffs.json").write_text(
        json.dumps(
            [
                {
                    "path": "src/app.py",
                    "change_type": "edited",
                    "workspace_path": str(project_root / "src" / "app.py"),
                    "added": 1,
                    "removed": 0,
                    "after_preview": "print('hello')",
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = center.get_run_files("run_test_files")
    assert payload is not None
    workspace_paths = {row["path"] for row in payload["workspace_files"]}
    workspace_dirs = set(payload.get("workspace_dirs", []))
    assert "projects/demo_project/src/app.py" in workspace_paths
    assert "projects/demo_project/tests/test_app.py" in workspace_paths
    assert "templates/base.txt" in workspace_paths
    assert "projects" in workspace_dirs
    assert "projects/demo_project" in workspace_dirs
    assert "projects/demo_project/src" in workspace_dirs
    assert "projects/demo_project/tests" in workspace_dirs
    assert payload["workspace_file_total"] >= len(workspace_paths)
    assert payload["workspace_dir_total"] >= len(workspace_dirs)
    assert payload["workspace_files_truncated"] is False


def test_goal_run_blocks_execution_when_plan_quality_below_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    center.update_settings({"plan_quality_threshold": 90})
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
                edits=[CodeEdit(path="app.py", content="print('x')\n", reason="noop")],
                commands=["pytest -q"],
                done=True,
                done_reason="done",
            )

    monkeypatch.setattr("web.control_center.Planner", WeakPlanner)
    monkeypatch.setattr("web.control_center.Coder", FastCoder)

    ok, start = center.start_run({"command": "/goal build with weak planning"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])

    assert run["meta"]["status"] == "failed"
    assert int(run["meta"]["plan_quality_threshold"]) == 90
    assert int(run["meta"]["plan_quality_score"]) < 90
    assert run["meta"]["plan_quality_passed"] is False
    assert state["planner_calls"] == 2
    assert state["coder_calls"] == 0

    result = run["result"]
    assert str(result.get("status", "")) == "failed"
    failure = result.get("failure_details", {})
    assert str(failure.get("category", "")) == "planning_quality"

    plan_quality = run.get("plan_quality", {})
    assert int(plan_quality.get("threshold", 0)) == 90
    assert bool(plan_quality.get("passed")) is False

    timeline_steps = [str(row.get("step", "")) for row in run.get("timeline", []) if isinstance(row, dict)]
    assert "plan_quality_scored" in timeline_steps
    assert "plan_quality_replan_requested" in timeline_steps
    assert "plan_quality_rejected" in timeline_steps


def test_goal_run_replans_once_and_executes_when_second_plan_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    center.update_settings({"plan_quality_threshold": 85})
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
                        title="Write failing tests first",
                        details="Create tests in tests/ for expected behavior and edge cases before implementation.",
                        success_check="pytest -q shows a failing test before code changes.",
                    ),
                    PlanStep(
                        id="S2",
                        title="Implement focused changes",
                        details="Apply minimal implementation only within workspace boundaries and keep scope constrained.",
                        success_check="Changes stay scoped and validation commands run with expected output.",
                    ),
                    PlanStep(
                        id="S3",
                        title="Verify and enforce safeguards",
                        details="Run pytest and enforce timeout, size limits, and rollback or approval safeguards.",
                        success_check="pytest exits with code 0 and safety constraints remain satisfied.",
                    ),
                ],
                success_criteria=[
                    "pytest -q exits with code 0.",
                    "Workspace boundaries and allow-list checks are respected.",
                    "Risk controls include timeout/limits and rollback or approval safeguards.",
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
                summary="single pass",
                edits=[CodeEdit(path="app.py", content="print('ok')\n", reason="implement")],
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
                analysis="all good",
                next_actions=["finish"],
                lessons=[LessonProposal(lesson="respond to plan quality feedback", tags=["planning"])],
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

    monkeypatch.setattr("web.control_center.Planner", RecoveringPlanner)
    monkeypatch.setattr("web.control_center.Coder", FastCoder)
    monkeypatch.setattr("web.control_center.Critic", FastCritic)
    monkeypatch.setattr("web.control_center.RestrictedExecutor", FastExecutor)

    ok, start = center.start_run({"command": "/goal recover from weak first plan"})
    assert ok is True
    run = _wait_for_terminal(center, start["run_id"])

    assert run["meta"]["status"] == "success"
    assert int(run["meta"]["plan_quality_threshold"]) == 85
    assert int(run["meta"]["plan_quality_score"]) >= 85
    assert run["meta"]["plan_quality_passed"] is True
    assert state["planner_calls"] == 2
    assert state["coder_calls"] == 1

    timeline_steps = [str(row.get("step", "")) for row in run.get("timeline", []) if isinstance(row, dict)]
    assert "plan_quality_replan_requested" in timeline_steps
    assert "plan_quality_rejected" not in timeline_steps


def test_plan_quality_telemetry_aggregates_replan_and_recovery(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    center = DavidControlCenter(config=config, data_root=tmp_path / "data")
    runs_root = tmp_path / "data" / "runs"

    def _write_run(run_id: str, meta: dict, plan_quality: dict) -> None:
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
        (run_dir / "plan_quality.json").write_text(json.dumps(plan_quality) + "\n", encoding="utf-8")

    _write_run(
        "run_plan_1",
        {
            "id": "run_plan_1",
            "mode": "goal",
            "status": "failed",
            "template_id": "build_cli_tool",
            "plan_quality_score": 58,
            "plan_quality_threshold": 70,
            "plan_quality_passed": False,
            "started_at": "2026-02-01T00:00:00+00:00",
        },
        {
            "score": 58,
            "threshold": 70,
            "passed": False,
            "attempts": [
                {"score": 55, "threshold": 70, "passed": False},
                {"score": 58, "threshold": 70, "passed": False},
            ],
        },
    )
    _write_run(
        "run_plan_2",
        {
            "id": "run_plan_2",
            "mode": "goal",
            "status": "success",
            "template_id": "bug_fix_mode",
            "plan_quality_score": 82,
            "plan_quality_threshold": 70,
            "plan_quality_passed": True,
            "started_at": "2026-02-02T00:00:00+00:00",
        },
        {
            "score": 82,
            "threshold": 70,
            "passed": True,
            "attempts": [
                {"score": 62, "threshold": 70, "passed": False},
                {"score": 82, "threshold": 70, "passed": True},
            ],
        },
    )
    _write_run(
        "run_plan_3",
        {
            "id": "run_plan_3",
            "mode": "goal",
            "status": "success",
            "template_id": "bug_fix_mode",
            "plan_quality_score": 88,
            "plan_quality_threshold": 70,
            "plan_quality_passed": True,
            "started_at": "2026-02-03T00:00:00+00:00",
        },
        {
            "score": 88,
            "threshold": 70,
            "passed": True,
            "attempt": 1,
            "max_attempts": 1,
        },
    )
    _write_run(
        "run_non_goal",
        {
            "id": "run_non_goal",
            "mode": "ask",
            "status": "success",
            "template_id": "",
            "started_at": "2026-02-04T00:00:00+00:00",
        },
        {},
    )

    payload = center.plan_quality_telemetry(limit_runs=20)
    assert int(payload["scored_runs"]) == 3
    assert int(payload["threshold_enabled_runs"]) == 3
    assert int(payload["rejected_runs"]) == 1
    assert int(payload["replanned_runs"]) == 2
    assert int(payload["recovered_on_replan_runs"]) == 1
    assert float(payload["reject_rate"]) == pytest.approx(1 / 3, rel=0.0, abs=0.001)
    assert float(payload["recovered_on_replan_rate"]) == pytest.approx(0.5, rel=0.0, abs=0.001)
    assert int(payload["max_attempts"]) >= 2

    by_template = {str(row.get("template_id", "")): row for row in payload.get("by_template", [])}
    assert "bug_fix_mode" in by_template
    bug_fix = by_template["bug_fix_mode"]
    assert int(bug_fix["runs"]) == 2
    assert float(bug_fix["replan_rate"]) == pytest.approx(0.5, rel=0.0, abs=0.001)
    assert float(bug_fix["recovered_on_replan_rate"]) == pytest.approx(1.0, rel=0.0, abs=0.001)
