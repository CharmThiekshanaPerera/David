"""Tests for agent.self_improvement.proposer — ImprovementProposer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.self_improvement.analyzer import WeaknessSignal
from agent.self_improvement.proposer import (
    BLOCKED_PATHS,
    ImprovementProposal,
    ImprovementProposer,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

_VALID_SIGNAL = WeaknessSignal(
    module_path="agent/planner.py",
    signal_code="high_retry_rate",
    evidence="75% retry rate observed.",
    severity=75,
)

_ORIGINAL_SOURCE = "# planner module\n\ndef create_plan():\n    pass\n"

_IMPROVED_SOURCE = "# planner module — improved\n\ndef create_plan():\n    return {}\n"


class _FakeLLM:
    """Minimal LLM stub that returns a canned response."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str, str | None]] = []

    def chat(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        self.calls.append((system_prompt, user_prompt, model))
        return self._response

    @property
    def config(self):
        class _Cfg:
            critic_model = "test-model"
        return _Cfg()


class _RaisingLLM:
    """LLM stub that always raises."""

    def chat(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        raise RuntimeError("Ollama unreachable")

    @property
    def config(self):
        class _Cfg:
            critic_model = "test-model"
        return _Cfg()


def _proposer(llm, project_root: Path) -> ImprovementProposer:
    return ImprovementProposer(llm=llm, project_root=project_root)


def _make_target(project_root: Path, path: str = "agent/planner.py", content: str = _ORIGINAL_SOURCE) -> Path:
    target = project_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ─── blocked paths ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("blocked_path", sorted(BLOCKED_PATHS))
def test_propose_returns_none_for_blocked_path(tmp_path, blocked_path):
    signal = WeaknessSignal(
        module_path=blocked_path,
        signal_code="test_signal",
        evidence="test evidence",
        severity=80,
    )
    llm = _FakeLLM('{"reasoning": "r", "content": "x"}')
    result = _proposer(llm, tmp_path).propose(signal)
    assert result is None
    assert llm.calls == [], "LLM should not be called for blocked paths"


def test_blocked_paths_always_includes_safety_modules():
    assert "agent/safety.py" in BLOCKED_PATHS
    assert "web/safety.py" in BLOCKED_PATHS
    assert "agent/executor.py" in BLOCKED_PATHS
    assert "agent/config.py" in BLOCKED_PATHS


# ─── missing / non-existent file ──────────────────────────────────────────────

def test_propose_returns_none_when_target_file_missing(tmp_path):
    # agent/planner.py does not exist in tmp_path
    llm = _FakeLLM('{"reasoning": "r", "content": "improved"}')
    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)
    assert result is None


def test_propose_returns_none_when_target_is_directory(tmp_path):
    # Create a directory at the target path
    (tmp_path / "agent" / "planner.py").mkdir(parents=True, exist_ok=True)
    llm = _FakeLLM('{"reasoning": "r", "content": "improved"}')
    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)
    assert result is None


# ─── LLM failure ──────────────────────────────────────────────────────────────

def test_propose_returns_none_when_llm_raises(tmp_path):
    _make_target(tmp_path)
    result = _proposer(_RaisingLLM(), tmp_path).propose(_VALID_SIGNAL)
    assert result is None


def test_propose_returns_none_when_llm_returns_empty_string(tmp_path):
    _make_target(tmp_path)
    llm = _FakeLLM("")
    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)
    assert result is None


def test_propose_returns_none_when_llm_returns_invalid_json(tmp_path):
    _make_target(tmp_path)
    llm = _FakeLLM("This is not JSON at all.")
    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)
    assert result is None


def test_propose_returns_none_when_content_field_missing(tmp_path):
    _make_target(tmp_path)
    llm = _FakeLLM('{"reasoning": "some reason"}')
    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)
    assert result is None


# ─── identical content ────────────────────────────────────────────────────────

def test_propose_returns_none_when_llm_returns_identical_content(tmp_path):
    _make_target(tmp_path, content=_ORIGINAL_SOURCE)
    # LLM echoes back the same source
    llm = _FakeLLM(f'{{"reasoning": "no change needed", "content": {repr(_ORIGINAL_SOURCE)}}}')
    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)
    assert result is None


# ─── happy path ───────────────────────────────────────────────────────────────

def test_propose_returns_proposal_on_valid_llm_response(tmp_path):
    _make_target(tmp_path, content=_ORIGINAL_SOURCE)
    response = json.dumps({"reasoning": "added return value", "content": _IMPROVED_SOURCE})
    llm = _FakeLLM(response)

    result = _proposer(llm, tmp_path).propose(_VALID_SIGNAL)

    assert isinstance(result, ImprovementProposal)
    assert result.target_path == "agent/planner.py"
    assert result.original_content == _ORIGINAL_SOURCE
    assert result.proposed_content == _IMPROVED_SOURCE
    assert "added return value" in result.reasoning
    assert result.signal is _VALID_SIGNAL


def test_propose_sends_signal_evidence_in_prompt(tmp_path):
    _make_target(tmp_path, content=_ORIGINAL_SOURCE)
    llm = _FakeLLM(json.dumps({"reasoning": "r", "content": _IMPROVED_SOURCE}))

    _proposer(llm, tmp_path).propose(_VALID_SIGNAL)

    assert llm.calls, "LLM should have been called"
    _, user_prompt, _ = llm.calls[0]
    assert "high_retry_rate" in user_prompt
    assert "75" in user_prompt          # severity
    assert "75% retry rate" in user_prompt  # evidence


def test_propose_uses_critic_model(tmp_path):
    _make_target(tmp_path, content=_ORIGINAL_SOURCE)
    llm = _FakeLLM(json.dumps({"reasoning": "r", "content": _IMPROVED_SOURCE}))

    _proposer(llm, tmp_path).propose(_VALID_SIGNAL)

    _, _, model = llm.calls[0]
    assert model == "test-model"


def test_propose_reads_target_file_content_into_prompt(tmp_path):
    _make_target(tmp_path, content=_ORIGINAL_SOURCE)
    llm = _FakeLLM(json.dumps({"reasoning": "r", "content": _IMPROVED_SOURCE}))

    _proposer(llm, tmp_path).propose(_VALID_SIGNAL)

    _, user_prompt, _ = llm.calls[0]
    assert "create_plan" in user_prompt   # from _ORIGINAL_SOURCE


# ─── _parse_response ──────────────────────────────────────────────────────────

def test_parse_response_extracts_from_clean_json():
    result = ImprovementProposer._parse_response(
        '{"reasoning": "better", "content": "def foo(): pass"}'
    )
    assert result is not None
    reasoning, content = result
    assert reasoning == "better"
    assert content == "def foo(): pass"


def test_parse_response_extracts_from_json_surrounded_by_text():
    raw = 'Here is my suggestion:\n{"reasoning": "fix", "content": "x = 1"}\nDone.'
    result = ImprovementProposer._parse_response(raw)
    assert result is not None
    _, content = result
    assert content == "x = 1"


def test_parse_response_returns_none_for_no_json():
    assert ImprovementProposer._parse_response("No JSON here at all.") is None


def test_parse_response_returns_none_for_empty_content_field():
    result = ImprovementProposer._parse_response('{"reasoning": "r", "content": ""}')
    assert result is None


def test_parse_response_returns_none_for_missing_content_field():
    result = ImprovementProposer._parse_response('{"reasoning": "r"}')
    assert result is None


def test_parse_response_handles_missing_reasoning_gracefully():
    result = ImprovementProposer._parse_response('{"content": "def foo(): pass"}')
    assert result is not None
    reasoning, content = result
    assert reasoning == ""
    assert content == "def foo(): pass"


# ─── ImprovementProposal dataclass ────────────────────────────────────────────

def test_improvement_proposal_is_frozen():
    proposal = ImprovementProposal(
        target_path="agent/planner.py",
        original_content="old",
        proposed_content="new",
        reasoning="better",
        signal=_VALID_SIGNAL,
    )
    with pytest.raises((AttributeError, TypeError)):
        proposal.target_path = "other"  # type: ignore[misc]
