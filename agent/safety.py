from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from agent.contracts import CodeEdit


class SafetyError(RuntimeError):
    """Raised when a proposed operation violates safety policy."""


@dataclass(frozen=True)
class ValidatedEdit:
    relative_path: str
    absolute_path: Path
    content: str
    reason: str


@dataclass(frozen=True)
class CommandSpec:
    raw: str
    argv: list[str]


class SafetyGuard:
    """Enforces strict file and command safety boundaries."""

    def __init__(
        self,
        workspace_dir: Path,
        max_file_write_bytes: int,
        max_total_write_bytes: int,
        allowed_commands: tuple[str, ...],
        max_commands_per_iteration: int = 6,
    ) -> None:
        self._workspace_dir = workspace_dir.resolve()
        self._max_file_write_bytes = max_file_write_bytes
        self._max_total_write_bytes = max_total_write_bytes
        self._allowed_commands = set(allowed_commands)
        self._max_commands_per_iteration = max_commands_per_iteration

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    def validate_edits(self, edits: list[CodeEdit]) -> list[ValidatedEdit]:
        # Deduplicate by path: keep the last edit per path so the model's
        # "create empty then fill" two-step pattern resolves to the filled version.
        seen: dict[str, CodeEdit] = {}
        for edit in edits:
            seen[edit.path] = edit
        deduped = [seen[e.path] for e in edits if e.path in seen and seen[e.path] is e]

        validated: list[ValidatedEdit] = []
        total_bytes = 0

        for edit in deduped:
            relative = self._normalize_relative_path(edit.path)
            absolute = (self._workspace_dir / relative).resolve()
            self._assert_inside_workspace(absolute)

            file_bytes = len(edit.content.encode("utf-8"))
            if file_bytes > self._max_file_write_bytes:
                raise SafetyError(
                    f"Edit for `{edit.path}` exceeds per-file limit "
                    f"({file_bytes} > {self._max_file_write_bytes} bytes)."
                )
            total_bytes += file_bytes

            validated.append(
                ValidatedEdit(
                    relative_path=relative.as_posix(),
                    absolute_path=absolute,
                    content=edit.content,
                    reason=edit.reason,
                )
            )

        if total_bytes > self._max_total_write_bytes:
            raise SafetyError(
                "Combined edit size exceeds limit "
                f"({total_bytes} > {self._max_total_write_bytes} bytes)."
            )

        return validated

    def apply_edits(self, validated_edits: list[ValidatedEdit]) -> list[str]:
        written_paths: list[str] = []
        for edit in validated_edits:
            edit.absolute_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = edit.absolute_path.with_suffix(edit.absolute_path.suffix + ".tmp")
            temp_path.write_text(edit.content, encoding="utf-8")
            os.replace(temp_path, edit.absolute_path)
            written_paths.append(edit.relative_path)
        return written_paths

    def validate_commands(self, commands: list[str]) -> list[CommandSpec]:
        if len(commands) > self._max_commands_per_iteration:
            raise SafetyError(
                f"Too many commands in one iteration ({len(commands)} > {self._max_commands_per_iteration})."
            )

        specs: list[CommandSpec] = []
        for index, raw in enumerate(commands):
            if not raw.strip():
                raise SafetyError(f"Command {index} is empty.")

            try:
                argv = shlex.split(raw, posix=True)
            except ValueError as exc:
                raise SafetyError(f"Command {index} cannot be parsed safely: {exc}") from exc

            if not argv:
                raise SafetyError(f"Command {index} has no executable.")

            executable = argv[0].lower()
            if executable not in self._allowed_commands:
                allowed = ", ".join(sorted(self._allowed_commands))
                raise SafetyError(
                    f"Command `{argv[0]}` is not allowed. Allowed commands: {allowed}."
                )

            specs.append(CommandSpec(raw=raw, argv=argv))

        return specs

    def _normalize_relative_path(self, raw_path: str) -> PurePosixPath:
        path = raw_path.strip().replace("\\", "/")
        if not path:
            raise SafetyError("Edit path cannot be empty.")
        if path.startswith("/"):
            raise SafetyError(f"Absolute paths are not allowed: {raw_path}")
        if len(path) >= 2 and path[1] == ":":
            raise SafetyError(f"Drive-based paths are not allowed: {raw_path}")

        normalized = PurePosixPath(path)
        if normalized.name in {"", ".", ".."}:
            raise SafetyError(f"Invalid edit path: {raw_path}")

        for part in normalized.parts:
            if part in {"", ".", ".."}:
                raise SafetyError(f"Path traversal is not allowed: {raw_path}")

        return normalized

    def _assert_inside_workspace(self, target: Path) -> None:
        workspace = str(self._workspace_dir)
        candidate = str(target)
        try:
            common = os.path.commonpath([workspace, candidate])
        except ValueError as exc:
            raise SafetyError(f"Path resolution failed for workspace boundary check: {target}") from exc
        if common != workspace:
            raise SafetyError(f"Path escapes workspace boundary: {target}")
