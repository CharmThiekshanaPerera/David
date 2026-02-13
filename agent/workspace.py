from __future__ import annotations

from pathlib import Path


class WorkspaceInspector:
    """Creates compact workspace context for model prompts."""

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = workspace_dir

    def snapshot(self, max_files: int = 40, max_chars_per_file: int = 1_500) -> str:
        files = [path for path in self._workspace_dir.rglob("*") if path.is_file()]
        files.sort()

        if not files:
            return "Workspace is empty."

        lines: list[str] = []
        for path in files[:max_files]:
            relative = path.relative_to(self._workspace_dir).as_posix()
            text = self._safe_read(path, max_chars=max_chars_per_file)
            lines.append(f"FILE: {relative}\n{text}")

        if len(files) > max_files:
            lines.append(f"... {len(files) - max_files} more files not shown")

        return "\n\n".join(lines)

    @staticmethod
    def _safe_read(path: Path, max_chars: int) -> str:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return "<binary or unreadable content skipped>"

        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "\n...[truncated]"
