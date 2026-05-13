"""Tests for agent.self_improvement.stager — ProposalStager."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.self_improvement.analyzer import WeaknessSignal
from agent.self_improvement.proposer import ImprovementProposal
from agent.self_improvement.stager import (
    ProposalStager,
    StagingResult,
    _check_syntax,
    _make_proposal_id,
    build_proposal_record,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

_SIGNAL = WeaknessSignal(
    module_path="agent/planner.py",
    signal_code="high_retry_rate",
    evidence="75% retry rate.",
    severity=75,
)

_VALID_PYTHON = "# improved\ndef create_plan():\n    return {}\n"
_INVALID_PYTHON = "def broken(\n  # missing close paren"


def _proposal(
    target_path: str = "agent/planner.py",
    original: str = "# original\ndef create_plan(): pass\n",
    proposed: str = _VALID_PYTHON,
    reasoning: str = "Better return value handling.",
) -> ImprovementProposal:
    return ImprovementProposal(
        target_path=target_path,
        original_content=original,
        proposed_content=proposed,
        reasoning=reasoning,
        signal=_SIGNAL,
    )


def _stager(tmp_path: Path) -> ProposalStager:
    sandbox = tmp_path / "agent_sandbox"
    sandbox.mkdir()
    return ProposalStager(project_root=tmp_path, sandbox_root=sandbox)


# ─── _check_syntax ────────────────────────────────────────────────────────────

def test_check_syntax_passes_valid_python():
    ok, err = _check_syntax("x = 1\ndef foo():\n    pass\n")
    assert ok is True
    assert err == ""


def test_check_syntax_fails_invalid_python():
    ok, err = _check_syntax(_INVALID_PYTHON)
    assert ok is False
    assert err != ""


def test_check_syntax_passes_empty_string():
    ok, err = _check_syntax("")
    assert ok is True


def test_check_syntax_passes_multiline_class():
    src = (
        "class Foo:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "    def method(self):\n"
        "        return self.x\n"
    )
    ok, _ = _check_syntax(src)
    assert ok is True


# ─── syntax failure → StagingResult.success=False ─────────────────────────────

def test_stage_returns_failure_for_invalid_python(tmp_path):
    stager = _stager(tmp_path)
    result = stager.stage(_proposal(proposed=_INVALID_PYTHON))

    assert result.success is False
    assert result.syntax_ok is False
    assert "Syntax error" in result.error


def test_stage_failure_writes_no_sandbox_file(tmp_path):
    stager = _stager(tmp_path)
    stager.stage(_proposal(proposed=_INVALID_PYTHON))

    sandbox = tmp_path / "agent_sandbox"
    # No proposal directory should have been created
    assert list(sandbox.iterdir()) == []


# ─── happy path: valid proposal ───────────────────────────────────────────────

def test_stage_returns_success_for_valid_proposal(tmp_path):
    result = _stager(tmp_path).stage(_proposal())
    assert result.success is True
    assert result.syntax_ok is True
    assert result.proposal_id != ""


def test_stage_creates_sandbox_file_with_proposed_content(tmp_path):
    result = _stager(tmp_path).stage(_proposal(proposed=_VALID_PYTHON))

    assert result.sandbox_file.exists()
    assert result.sandbox_file.read_text(encoding="utf-8") == _VALID_PYTHON


def test_stage_sandbox_file_inside_prototype_dir(tmp_path):
    result = _stager(tmp_path).stage(_proposal())

    # file must be at <sandbox_root>/<proposal_id>/prototype/file_000_<name>
    assert result.sandbox_file.parent.name == "prototype"
    assert result.sandbox_file.name.startswith("file_000_")


def test_stage_sandbox_file_uses_safe_path_name(tmp_path):
    result = _stager(tmp_path).stage(_proposal(target_path="agent/planner.py"))

    # Slashes must be replaced with underscores in the file name
    assert "/" not in result.sandbox_file.name
    assert "agent_planner" in result.sandbox_file.name


def test_stage_sandbox_dir_is_inside_sandbox_root(tmp_path):
    sandbox_root = tmp_path / "agent_sandbox"
    sandbox_root.mkdir()
    stager = ProposalStager(project_root=tmp_path, sandbox_root=sandbox_root)

    result = stager.stage(_proposal())

    assert sandbox_root in result.sandbox_dir.parents or result.sandbox_dir == sandbox_root


def test_stage_writes_proposal_doc(tmp_path):
    result = _stager(tmp_path).stage(_proposal())

    proposal_doc = result.sandbox_dir / "PROPOSAL.md"
    assert proposal_doc.exists()
    content = proposal_doc.read_text(encoding="utf-8")
    assert "agent/planner.py" in content
    assert "high_retry_rate" in content


def test_stage_proposal_doc_contains_reasoning(tmp_path):
    result = _stager(tmp_path).stage(_proposal(reasoning="This improves retry handling."))

    doc = (result.sandbox_dir / "PROPOSAL.md").read_text(encoding="utf-8")
    assert "This improves retry handling." in doc


# ─── proposal ID uniqueness ───────────────────────────────────────────────────

def test_make_proposal_id_includes_module_name():
    proposal = _proposal(target_path="agent/planner.py")
    pid = _make_proposal_id(proposal)
    assert "agent_planner_py" in pid


def test_make_proposal_id_includes_timestamp_prefix():
    proposal = _proposal()
    pid = _make_proposal_id(proposal)
    # Format: improve_<module>_<YYYYMMDDTHHmmss>_<hash>
    assert pid.startswith("improve_")
    parts = pid.split("_")
    assert len(parts) >= 3


def test_make_proposal_id_differs_for_different_content():
    p1 = _proposal(proposed="def a(): pass\n")
    p2 = _proposal(proposed="def b(): pass\n")
    # SHA1 hash suffix should differ
    assert _make_proposal_id(p1) != _make_proposal_id(p2)


# ─── build_proposal_record ────────────────────────────────────────────────────

def test_build_proposal_record_has_required_keys(tmp_path):
    staging = _stager(tmp_path).stage(_proposal())
    record = build_proposal_record(staging, _proposal())

    required = {"id", "title", "rationale", "status", "actor", "created_at",
                 "updated_at", "sandbox_dir", "proposal_doc", "changes",
                 "metadata", "decision", "merge"}
    assert required.issubset(record.keys())


def test_build_proposal_record_status_is_pending(tmp_path):
    staging = _stager(tmp_path).stage(_proposal())
    record = build_proposal_record(staging, _proposal())
    assert record["status"] == "pending"


def test_build_proposal_record_decision_and_merge_are_none(tmp_path):
    staging = _stager(tmp_path).stage(_proposal())
    record = build_proposal_record(staging, _proposal())
    assert record["decision"] is None
    assert record["merge"] is None


def test_build_proposal_record_changes_has_sandbox_file(tmp_path):
    proposal = _proposal()
    staging = _stager(tmp_path).stage(proposal)
    record = build_proposal_record(staging, proposal)

    assert len(record["changes"]) == 1
    change = record["changes"][0]
    assert change["path"] == "agent/planner.py"
    assert "sandbox_file" in change
    assert Path(change["sandbox_file"]).exists()


def test_build_proposal_record_metadata_includes_signal_info(tmp_path):
    proposal = _proposal()
    staging = _stager(tmp_path).stage(proposal)
    record = build_proposal_record(staging, proposal)

    meta = record["metadata"]
    assert meta["signal_code"] == "high_retry_rate"
    assert meta["signal_severity"] == 75
    assert meta["syntax_ok"] is True


def test_build_proposal_record_is_valid_json_serializable(tmp_path):
    proposal = _proposal()
    staging = _stager(tmp_path).stage(proposal)
    record = build_proposal_record(staging, proposal)

    # Must not raise
    serialized = json.dumps(record)
    assert len(serialized) > 0


def test_build_proposal_record_respects_custom_actor(tmp_path):
    proposal = _proposal()
    staging = _stager(tmp_path).stage(proposal)
    record = build_proposal_record(staging, proposal, actor="test_runner")
    assert record["actor"] == "test_runner"


# ─── StagingResult dataclass ──────────────────────────────────────────────────

def test_staging_result_is_frozen():
    result = StagingResult(
        success=True,
        proposal_id="test",
        sandbox_file=Path("."),
        sandbox_dir=Path("."),
        syntax_ok=True,
        tests_passed=True,
        test_output="ok",
        error="",
    )
    with pytest.raises((AttributeError, TypeError)):
        result.success = False  # type: ignore[misc]


# ─── defensive: stager never raises ──────────────────────────────────────────

def test_stager_does_not_raise_on_unwritable_sandbox(tmp_path, monkeypatch):
    """Even if sandbox write fails, stager returns a StagingResult."""
    import agent.self_improvement.stager as stager_mod

    def _bad_mkdir(*args, **kwargs):
        raise PermissionError("no write access")

    monkeypatch.setattr(Path, "mkdir", _bad_mkdir)
    stager = ProposalStager(project_root=tmp_path, sandbox_root=tmp_path / "sandbox")

    # Should return a StagingResult, not raise
    result = stager.stage(_proposal())
    assert isinstance(result, StagingResult)
