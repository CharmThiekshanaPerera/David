from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.projects import prepare_project_for_goal, resolve_existing_project_path, sanitize_project_slug


def test_sanitize_project_slug_normalizes_text() -> None:
    slug = sanitize_project_slug(" Build CLI Tool!!! v2 ")
    assert slug == "build_cli_tool_v2"


def test_sanitize_project_slug_fallback_for_empty() -> None:
    slug = sanitize_project_slug("   ")
    assert slug == "project"


def test_prepare_project_for_goal_creates_structure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    project = prepare_project_for_goal(workspace, "Create a tiny calculator app")

    assert project.project_slug.startswith("create_a_tiny_calculator_app")
    assert project.project_created_new is True
    assert project.project_path.exists()
    assert (workspace / "projects").exists()
    assert (workspace / "templates").exists()
    assert (workspace / "scratch").exists()

    for folder in ("src", "tests", "docs", "data", "config"):
        assert (project.project_path / folder).is_dir()
    assert (project.project_path / "README.md").is_file()

    active = json.loads((workspace / "active_project.json").read_text(encoding="utf-8"))
    assert active["project_slug"] == project.project_slug
    assert active["project_path"] == str(project.project_path)


def test_prepare_project_for_goal_uniquifies_slug_if_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    first = prepare_project_for_goal(workspace, "My Project")
    second = prepare_project_for_goal(workspace, "My Project")

    assert first.project_slug == "my_project"
    assert second.project_slug != first.project_slug
    assert second.project_slug.startswith("my_project_")
    assert second.project_path.exists()


def test_resolve_existing_project_path_blocks_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    prepare_project_for_goal(workspace, "safe goal")

    with pytest.raises(ValueError):
        resolve_existing_project_path(workspace, outside)

