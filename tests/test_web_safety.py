from __future__ import annotations

from pathlib import Path

import pytest

from web.safety import is_safe_run_id, resolve_workspace_relative


def test_is_safe_run_id():
    assert is_safe_run_id("run_20260101T000000_ab12cd34")
    assert not is_safe_run_id("../bad")
    assert not is_safe_run_id("run space")


def test_resolve_workspace_relative_allows_child(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)

    resolved = resolve_workspace_relative(workspace, "src/main.py")
    assert resolved == workspace / "src/main.py"


def test_resolve_workspace_relative_rejects_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)

    with pytest.raises(ValueError):
        resolve_workspace_relative(workspace, "../outside.py")
