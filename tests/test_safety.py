from __future__ import annotations

import pytest

from agent.contracts import CodeEdit
from agent.safety import SafetyError, SafetyGuard


def _guard(tmp_path):
    return SafetyGuard(
        workspace_dir=tmp_path,
        max_file_write_bytes=100,
        max_total_write_bytes=200,
        allowed_commands=("python", "pytest"),
        max_commands_per_iteration=3,
    )


def test_validate_edit_accepts_safe_relative_path(tmp_path):
    guard = _guard(tmp_path)
    edits = [CodeEdit(path="src/app.py", content="print('ok')\n", reason="add app")]

    validated = guard.validate_edits(edits)

    assert len(validated) == 1
    assert validated[0].relative_path == "src/app.py"


def test_validate_edit_rejects_parent_traversal(tmp_path):
    guard = _guard(tmp_path)
    edits = [CodeEdit(path="../outside.py", content="x", reason="escape")]

    with pytest.raises(SafetyError):
        guard.validate_edits(edits)


def test_validate_edit_rejects_windows_drive_path(tmp_path):
    guard = _guard(tmp_path)
    edits = [CodeEdit(path="C:\\temp\\evil.py", content="x", reason="escape")]

    with pytest.raises(SafetyError):
        guard.validate_edits(edits)


def test_validate_edit_rejects_oversized_write(tmp_path):
    guard = _guard(tmp_path)
    edits = [CodeEdit(path="big.txt", content="a" * 101, reason="too large")]

    with pytest.raises(SafetyError):
        guard.validate_edits(edits)


def test_validate_commands_allowlist(tmp_path):
    guard = _guard(tmp_path)
    specs = guard.validate_commands(["python -m pytest -q", "pytest -q"])

    assert len(specs) == 2
    assert specs[0].argv[0] == "python"
    assert specs[1].argv[0] == "pytest"


def test_validate_commands_rejects_non_whitelisted_command(tmp_path):
    guard = _guard(tmp_path)

    with pytest.raises(SafetyError):
        guard.validate_commands(["pip install requests"])
