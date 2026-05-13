"""Integration tests for the --propose-improvement CLI command.

Tests agent.main.run_propose_improvement() end-to-end using fake
LLM responses and real file system operations (via tmp_path).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.main import run_propose_improvement
from agent.self_improvement.analyzer import WeaknessSignal


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_config(tmp_path: Path):
    """Build a minimal AgentConfig-like object pointing at tmp_path."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = MagicMock()
    cfg.logs_dir = logs_dir
    cfg.workspace_dir = workspace
    cfg.project_root = tmp_path
    cfg.critic_model = "test-model"
    cfg.temperature = 0.2
    cfg.ollama_url = "http://127.0.0.1:11434/api/chat"
    cfg.model = "test-model"
    return cfg


def _write_metrics(logs_dir: Path, iterations: list[dict]) -> None:
    (logs_dir / "metrics.json").write_text(
        json.dumps({"iterations": iterations}), encoding="utf-8"
    )


def _write_target_module(tmp_path: Path, path: str = "agent/planner.py") -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# planner\ndef create_plan():\n    pass\n", encoding="utf-8")


_IMPROVED_CONTENT = "# planner improved\ndef create_plan():\n    return {}\n"

_VALID_LLM_RESPONSE = json.dumps({
    "reasoning": "Added return value to make plan non-empty.",
    "content": _IMPROVED_CONTENT,
})


# ─── no signals → exit 0 ──────────────────────────────────────────────────────

def test_propose_improvement_returns_0_when_no_signals(tmp_path, capsys):
    config = _make_config(tmp_path)
    # No metrics or telemetry written → analyzer produces no signals

    result = run_propose_improvement(config)

    assert result == 0
    out = capsys.readouterr().out
    assert "No actionable weakness signals" in out


# ─── proposer returns None → exit 1 ──────────────────────────────────────────

def test_propose_improvement_returns_1_when_proposer_fails(tmp_path, capsys):
    config = _make_config(tmp_path)
    # Create high retry rate signal
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    # Target module exists
    _write_target_module(tmp_path)

    # LLM returns garbage → proposer returns None
    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = "not json"
        instance.config.critic_model = "test-model"

        result = run_propose_improvement(config)

    assert result == 1
    out = capsys.readouterr().out
    assert "Could not generate a proposal" in out


# ─── stager fails syntax check → exit 1 ──────────────────────────────────────

def test_propose_improvement_returns_1_when_stager_fails(tmp_path, capsys):
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    broken_python = "def broken(\n  # missing close"
    bad_response = json.dumps({"reasoning": "oops", "content": broken_python})

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = bad_response
        instance.config.critic_model = "test-model"

        result = run_propose_improvement(config)

    assert result == 1
    out = capsys.readouterr().out
    assert "Staging failed" in out


# ─── happy path: full successful cycle ───────────────────────────────────────

def test_propose_improvement_happy_path_writes_to_self_improvements_json(tmp_path, capsys):
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = _VALID_LLM_RESPONSE
        instance.config.critic_model = "test-model"

        result = run_propose_improvement(config)

    assert result == 0

    si_file = tmp_path / "data" / "self_improvements.json"
    assert si_file.exists(), "self_improvements.json must be written"

    payload = json.loads(si_file.read_text(encoding="utf-8"))
    assert "proposals" in payload
    assert len(payload["proposals"]) == 1

    proposal = payload["proposals"][0]
    assert proposal["status"] == "pending"
    assert proposal["decision"] is None
    assert proposal["merge"] is None


def test_propose_improvement_happy_path_shows_proposal_id(tmp_path, capsys):
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = _VALID_LLM_RESPONSE
        instance.config.critic_model = "test-model"

        run_propose_improvement(config)

    out = capsys.readouterr().out
    assert "ID:" in out
    assert "improve_" in out


def test_propose_improvement_happy_path_shows_web_ui_instruction(tmp_path, capsys):
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = _VALID_LLM_RESPONSE
        instance.config.critic_model = "test-model"

        run_propose_improvement(config)

    out = capsys.readouterr().out
    assert "Web UI" in out
    assert "Proposed Improvements" in out


def test_propose_improvement_creates_sandbox_file(tmp_path):
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = _VALID_LLM_RESPONSE
        instance.config.critic_model = "test-model"

        run_propose_improvement(config)

    sandbox_root = config.workspace_dir / "agent_sandbox"
    staged_files = list(sandbox_root.rglob("file_000_*.py"))
    assert staged_files, "At least one staged file must exist in agent_sandbox"


def test_propose_improvement_staged_file_has_proposed_content(tmp_path):
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = _VALID_LLM_RESPONSE
        instance.config.critic_model = "test-model"

        run_propose_improvement(config)

    sandbox_root = config.workspace_dir / "agent_sandbox"
    staged_files = list(sandbox_root.rglob("file_000_*.py"))
    assert staged_files
    content = staged_files[0].read_text(encoding="utf-8")
    # Strip both sides for comparison — line endings may differ
    assert content.strip() == _IMPROVED_CONTENT.strip()


def test_propose_improvement_appends_to_existing_proposals(tmp_path):
    """Running --propose-improvement twice appends both records."""
    config = _make_config(tmp_path)
    _write_metrics(config.logs_dir, [{"status": "retry"}] * 6 + [{"status": "success"}] * 2)
    _write_target_module(tmp_path)

    with patch("agent.main.OllamaClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat.return_value = _VALID_LLM_RESPONSE
        instance.config.critic_model = "test-model"

        run_propose_improvement(config)

        # Slightly different content so stager gets a different hash
        instance.chat.return_value = json.dumps({
            "reasoning": "Second proposal.",
            "content": _IMPROVED_CONTENT + "\n# second\n",
        })
        run_propose_improvement(config)

    si_file = tmp_path / "data" / "self_improvements.json"
    payload = json.loads(si_file.read_text(encoding="utf-8"))
    assert len(payload["proposals"]) == 2


# ─── CLI argument parsing ─────────────────────────────────────────────────────

def test_propose_improvement_flag_parsed_correctly():
    from agent.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["--propose-improvement"])
    assert args.propose_improvement is True


def test_propose_improvement_flag_default_is_false():
    from agent.main import build_parser
    parser = build_parser()
    args = parser.parse_args([])
    assert args.propose_improvement is False


def test_propose_improvement_and_goal_can_coexist_in_parser():
    """Parser must accept --propose-improvement as a standalone flag."""
    from agent.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["--propose-improvement"])
    assert args.propose_improvement is True
    assert args.goal is None
