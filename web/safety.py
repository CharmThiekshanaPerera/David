from __future__ import annotations

import re
from pathlib import Path
from pathlib import PurePosixPath


RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{6,80}$")


def is_safe_run_id(run_id: str) -> bool:
    return bool(RUN_ID_RE.match(run_id.strip()))


def resolve_workspace_relative(workspace_dir: Path, relative_path: str) -> Path:
    normalized = PurePosixPath(relative_path.strip().replace("\\", "/"))
    if not normalized.parts or str(normalized).startswith("/"):
        raise ValueError("Path must be relative to workspace.")
    if any(part in {"", ".", ".."} for part in normalized.parts):
        raise ValueError("Path traversal is not allowed.")

    target = (workspace_dir.resolve() / normalized.as_posix()).resolve()
    workspace = workspace_dir.resolve()

    if workspace not in target.parents and target != workspace:
        raise ValueError("Resolved path escapes workspace boundary.")
    return target


__all__ = ["is_safe_run_id", "resolve_workspace_relative"]
