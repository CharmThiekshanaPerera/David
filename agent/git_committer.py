from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_GITIGNORE_CONTENT = """\
__pycache__/
*.py[cod]
*.pyo
*.egg-info/
.venv/
.env
dist/
build/
.pytest_cache/
.mypy_cache/
*.log
"""

_GIT_AUTHOR_NAME = "David Agent"
_GIT_AUTHOR_EMAIL = "david@localhost"
_TIMEOUT_SEC = 20


@dataclass(frozen=True)
class GitCommitResult:
    success: bool
    skipped: bool
    sha: str
    message: str


class GitCommitter:
    """Manages git auto-commit for an isolated project directory."""

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path
        self._git: str | None = shutil.which("git")

    def _available(self) -> bool:
        return self._git is not None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = _GIT_AUTHOR_NAME
        env["GIT_AUTHOR_EMAIL"] = _GIT_AUTHOR_EMAIL
        env["GIT_COMMITTER_NAME"] = _GIT_AUTHOR_NAME
        env["GIT_COMMITTER_EMAIL"] = _GIT_AUTHOR_EMAIL
        return subprocess.run(
            [str(self._git), *args],
            cwd=self._project_path,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_TIMEOUT_SEC,
            env=env,
        )

    def _ensure_gitignore(self) -> None:
        gitignore = self._project_path / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    def ensure_repo(self) -> bool:
        """Initialize git repo if not already present. Returns True when ready."""
        if not self._available():
            return False
        git_dir = self._project_path / ".git"
        if not git_dir.exists():
            result = self._run(["init", "-b", "main"])
            if result.returncode != 0:
                # Older git versions don't support -b; retry without it
                result = self._run(["init"])
                if result.returncode != 0:
                    return False
        self._ensure_gitignore()
        return True

    def commit(self, message: str) -> GitCommitResult:
        """Stage all changes and create a commit. Never raises — failures are returned."""
        if not self._available():
            return GitCommitResult(success=False, skipped=True, sha="", message="git not found in PATH")

        if not self.ensure_repo():
            return GitCommitResult(success=False, skipped=False, sha="", message="failed to initialize git repo")

        add_result = self._run(["add", "-A"])
        if add_result.returncode != 0:
            err = add_result.stderr.strip()[:200]
            return GitCommitResult(success=False, skipped=False, sha="", message=f"git add failed: {err}")

        status_result = self._run(["status", "--porcelain"])
        if status_result.returncode == 0 and not status_result.stdout.strip():
            return GitCommitResult(success=True, skipped=True, sha="", message="nothing to commit")

        commit_result = self._run(["commit", "-m", message])
        if commit_result.returncode != 0:
            err = commit_result.stderr.strip()[:200]
            return GitCommitResult(success=False, skipped=False, sha="", message=f"git commit failed: {err}")

        sha_result = self._run(["rev-parse", "--short", "HEAD"])
        sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""
        return GitCommitResult(success=True, skipped=False, sha=sha, message=f"committed {sha}")


def build_commit_message(goal: str, iteration: int, coder_summary: str) -> str:
    """Build a structured commit message for a successful David iteration."""
    goal_line = goal.strip()
    if len(goal_line) > 60:
        goal_line = goal_line[:57] + "..."
    subject = f"[David] iter={iteration}: {goal_line}"
    body_lines = [
        f"Goal: {goal.strip()}",
        f"Iteration: {iteration}",
        f"Coder: {coder_summary.strip()[:300]}",
    ]
    return subject + "\n\n" + "\n".join(body_lines)
