"""Tests for agent.self_improvement.version_manager — VersionManager."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.self_improvement.version_manager import VersionManager


# ─── helpers ──────────────────────────────────────────────────────────────────

def _vm(tmp_path: Path) -> VersionManager:
    (tmp_path / "docs").mkdir(exist_ok=True)
    return VersionManager(project_root=tmp_path)


def _write_version(tmp_path: Path, version: str) -> None:
    (tmp_path / "VERSION").write_text(version + "\n", encoding="utf-8")


# ─── current_version ──────────────────────────────────────────────────────────

def test_current_version_returns_default_when_file_missing(tmp_path):
    vm = _vm(tmp_path)
    assert vm.current_version() == "0.1.0"


def test_current_version_reads_file_correctly(tmp_path):
    _write_version(tmp_path, "1.3.7")
    assert _vm(tmp_path).current_version() == "1.3.7"


def test_current_version_strips_whitespace(tmp_path):
    (tmp_path / "VERSION").write_text("  2.0.1  \n", encoding="utf-8")
    assert _vm(tmp_path).current_version() == "2.0.1"


def test_current_version_handles_empty_file(tmp_path):
    (tmp_path / "VERSION").write_text("", encoding="utf-8")
    assert _vm(tmp_path).current_version() == "0.1.0"


def test_current_version_handles_corrupt_file(tmp_path):
    (tmp_path / "VERSION").write_text("\x00\xff", encoding="latin-1")
    # Should not raise — returns whatever it reads or the default
    result = _vm(tmp_path).current_version()
    assert isinstance(result, str)


# ─── bump_patch ───────────────────────────────────────────────────────────────

def test_bump_patch_increments_patch_digit(tmp_path):
    _write_version(tmp_path, "0.1.0")
    new_version = _vm(tmp_path).bump_patch()
    assert new_version == "0.1.1"


def test_bump_patch_writes_new_version_to_file(tmp_path):
    _write_version(tmp_path, "0.1.0")
    vm = _vm(tmp_path)
    vm.bump_patch()
    assert (tmp_path / "VERSION").read_text(encoding="utf-8").strip() == "0.1.1"


def test_bump_patch_sequential_increments(tmp_path):
    _write_version(tmp_path, "0.1.0")
    vm = _vm(tmp_path)
    assert vm.bump_patch() == "0.1.1"
    assert vm.bump_patch() == "0.1.2"
    assert vm.bump_patch() == "0.1.3"


def test_bump_patch_handles_large_patch_number(tmp_path):
    _write_version(tmp_path, "0.1.9")
    assert _vm(tmp_path).bump_patch() == "0.1.10"


def test_bump_patch_preserves_major_and_minor(tmp_path):
    _write_version(tmp_path, "3.7.4")
    new_version = _vm(tmp_path).bump_patch()
    assert new_version == "3.7.5"


def test_bump_patch_recovers_from_invalid_version_format(tmp_path):
    _write_version(tmp_path, "not-a-version")
    new_version = _vm(tmp_path).bump_patch()
    # Should not raise; should produce a valid semver
    parts = new_version.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_bump_patch_creates_version_file_if_missing(tmp_path):
    vm = _vm(tmp_path)
    new_version = vm.bump_patch()
    assert (tmp_path / "VERSION").exists()
    assert new_version == "0.1.1"


# ─── append_log ───────────────────────────────────────────────────────────────

def test_append_log_creates_log_file_when_missing(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(
        version="0.1.1",
        title="Test improvement",
        target_file="agent/planner.py",
        reasoning="Reduces retry rate.",
    )
    log = tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md"
    assert log.exists()


def test_append_log_writes_version_and_title(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(
        version="0.1.1",
        title="Planner prompt improvement",
        target_file="agent/planner.py",
        reasoning="Added more detail to planning prompts.",
    )
    content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "v0.1.1" in content
    assert "Planner prompt improvement" in content


def test_append_log_writes_target_file(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(
        version="0.1.2",
        title="Critic fix",
        target_file="agent/critic.py",
        reasoning="Better abort detection.",
    )
    content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "agent/critic.py" in content


def test_append_log_writes_reasoning(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(
        version="0.1.3",
        title="Memory fix",
        target_file="agent/memory.py",
        reasoning="Deduplication prevents stale lessons from repeating.",
    )
    content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "Deduplication prevents stale lessons" in content


def test_append_log_includes_signal_code_when_provided(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(
        version="0.1.4",
        title="Coder fix",
        target_file="agent/coder.py",
        reasoning="Fewer command failures.",
        signal_code="high_command_failure_rate",
        signal_severity=72,
    )
    content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "high_command_failure_rate" in content
    assert "72" in content


def test_append_log_omits_signal_line_when_no_signal_code(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(
        version="0.1.5",
        title="Manual fix",
        target_file="agent/prompts.py",
        reasoning="Manual improvement.",
        signal_code="",
    )
    content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "Signal:" not in content


def test_append_log_accumulates_multiple_entries(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(version="0.1.1", title="First", target_file="agent/planner.py", reasoning="R1")
    vm.append_log(version="0.1.2", title="Second", target_file="agent/critic.py", reasoning="R2")
    vm.append_log(version="0.1.3", title="Third", target_file="agent/memory.py", reasoning="R3")

    content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "v0.1.1" in content
    assert "v0.1.2" in content
    assert "v0.1.3" in content
    assert content.index("v0.1.1") < content.index("v0.1.2") < content.index("v0.1.3")


def test_append_log_is_append_only(tmp_path):
    vm = _vm(tmp_path)
    vm.append_log(version="0.1.1", title="First", target_file="agent/planner.py", reasoning="R1")
    first_content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")

    vm.append_log(version="0.1.2", title="Second", target_file="agent/critic.py", reasoning="R2")
    second_content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")

    assert second_content.startswith(first_content.rstrip())


def test_append_log_creates_docs_dir_if_missing(tmp_path):
    # Use a fresh tmp subdir so docs/ definitely doesn't exist yet
    project = tmp_path / "fresh_project"
    project.mkdir()
    assert not (project / "docs").exists()

    vm = VersionManager(project_root=project)
    vm.append_log(version="0.1.1", title="T", target_file="agent/planner.py", reasoning="R")

    assert (project / "docs" / "SELF_IMPROVEMENT_LOG.md").exists()


def test_append_log_does_not_raise_on_os_error(tmp_path, monkeypatch):
    """append_log must never raise — it is non-fatal."""
    import builtins
    _real_open = builtins.open

    def _fail_open(path, *args, **kwargs):
        if "SELF_IMPROVEMENT_LOG" in str(path):
            raise PermissionError("no write access")
        return _real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _fail_open)

    vm = _vm(tmp_path)
    vm.append_log(version="0.1.1", title="T", target_file="f.py", reasoning="R")
    # Should complete without raising


# ─── full integration: bump + log ─────────────────────────────────────────────

def test_bump_then_log_reflects_new_version(tmp_path):
    _write_version(tmp_path, "0.1.0")
    vm = _vm(tmp_path)
    new_version = vm.bump_patch()
    vm.append_log(
        version=new_version,
        title="Integration test",
        target_file="agent/planner.py",
        reasoning="Testing bump+log together.",
    )

    assert new_version == "0.1.1"
    log_content = (tmp_path / "docs" / "SELF_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    assert "v0.1.1" in log_content
    assert (tmp_path / "VERSION").read_text(encoding="utf-8").strip() == "0.1.1"
