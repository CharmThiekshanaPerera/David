from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SLUG_SAFE_PATTERN = re.compile(r"[^a-z0-9]+")
PROJECT_FOLDERS = ("projects", "templates", "scratch")
PROJECT_LAYOUT_FOLDERS = ("src", "tests", "docs", "data", "config")


@dataclass(frozen=True)
class ProjectContext:
    project_slug: str
    project_path: Path
    project_created_new: bool


def sanitize_project_slug(goal: str, max_len: int = 64) -> str:
    raw = goal.strip().lower()
    if not raw:
        return "project"
    slug = SLUG_SAFE_PATTERN.sub("_", raw)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "project"
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("_")
    return slug or "project"


def ensure_workspace_layout(workspace_dir: Path) -> None:
    workspace = workspace_dir.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    for folder in PROJECT_FOLDERS:
        (workspace / folder).mkdir(parents=True, exist_ok=True)


def prepare_project_for_goal(workspace_dir: Path, goal: str) -> ProjectContext:
    workspace = workspace_dir.resolve()
    ensure_workspace_layout(workspace)
    projects_root = (workspace / "projects").resolve()

    base_slug = sanitize_project_slug(goal)
    project_slug = base_slug
    candidate = (projects_root / project_slug).resolve()
    created_new = True
    if candidate.exists():
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        project_slug = f"{base_slug}_{stamp}"
        candidate = (projects_root / project_slug).resolve()
        index = 1
        while candidate.exists():
            project_slug = f"{base_slug}_{stamp}_{index}"
            candidate = (projects_root / project_slug).resolve()
            index += 1

    _assert_inside_projects_root(projects_root, candidate)
    candidate.mkdir(parents=True, exist_ok=False)
    _ensure_project_layout(candidate, goal=goal)
    _write_active_project(workspace, project_slug=project_slug, project_path=candidate, goal=goal)

    return ProjectContext(
        project_slug=project_slug,
        project_path=candidate,
        project_created_new=created_new,
    )


def resolve_existing_project_path(workspace_dir: Path, project_path: str | Path) -> Path:
    workspace = workspace_dir.resolve()
    ensure_workspace_layout(workspace)
    projects_root = (workspace / "projects").resolve()

    candidate = Path(project_path).resolve()
    _assert_inside_projects_root(projects_root, candidate)
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("Project path does not exist under workspace/projects.")
    return candidate


def _ensure_project_layout(project_dir: Path, goal: str) -> None:
    for folder in PROJECT_LAYOUT_FOLDERS:
        (project_dir / folder).mkdir(parents=True, exist_ok=True)

    readme_path = project_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            (
                "# Project\n\n"
                f"Goal: {goal.strip() or 'N/A'}\n\n"
                "## Structure\n\n"
                "- `src/`: implementation code\n"
                "- `tests/`: automated tests\n"
                "- `docs/`: documentation\n"
                "- `data/`: local runtime data\n"
                "- `config/`: project configuration\n"
            ),
            encoding="utf-8",
        )


def _write_active_project(workspace_dir: Path, project_slug: str, project_path: Path, goal: str) -> None:
    payload = {
        "project_slug": project_slug,
        "project_path": str(project_path),
        "goal": goal,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    (workspace_dir / "active_project.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _assert_inside_projects_root(projects_root: Path, candidate: Path) -> None:
    root = str(projects_root)
    target = str(candidate)
    try:
        common = os.path.commonpath([root, target])
    except ValueError as exc:
        raise ValueError("Project path validation failed.") from exc
    if common != root:
        raise ValueError("Project path escapes workspace/projects boundary.")
