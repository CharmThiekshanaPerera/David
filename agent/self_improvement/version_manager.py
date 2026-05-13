"""Version manager for David's self-improvement system.

Reads and bumps the VERSION file (semver patch) and appends entries
to docs/SELF_IMPROVEMENT_LOG.md when a proposal is approved and merged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_VERSION = "0.1.0"


class VersionManager:
    """Manages the VERSION file and the append-only SELF_IMPROVEMENT_LOG."""

    def __init__(self, project_root: Path) -> None:
        self._version_file = project_root / "VERSION"
        self._log_file = project_root / "docs" / "SELF_IMPROVEMENT_LOG.md"

    # ------------------------------------------------------------------ version

    def current_version(self) -> str:
        """Return the current version string, defaulting to 0.1.0 if file is missing."""
        if not self._version_file.exists():
            return _DEFAULT_VERSION
        try:
            raw = self._version_file.read_text(encoding="utf-8", errors="replace").strip()
            return raw if raw else _DEFAULT_VERSION
        except OSError:
            return _DEFAULT_VERSION

    def bump_patch(self) -> str:
        """
        Increment the patch component of the current version and persist it.
        Example: 0.1.0 → 0.1.1 → 0.1.2 ...
        Returns the new version string.
        """
        current = self.current_version()
        parts = current.split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1])
            patch = int(parts[2])
        except (IndexError, ValueError):
            major, minor, patch = 0, 1, 0

        new_version = f"{major}.{minor}.{patch + 1}"
        try:
            self._version_file.write_text(new_version + "\n", encoding="utf-8")
        except OSError:
            pass  # non-fatal — version bump failure should not block the merge
        return new_version

    # -------------------------------------------------------------------- log

    def append_log(
        self,
        *,
        version: str,
        title: str,
        target_file: str,
        reasoning: str,
        actor: str = "web_ui",
        signal_code: str = "",
        signal_severity: int = 0,
    ) -> None:
        """
        Append a structured changelog entry to docs/SELF_IMPROVEMENT_LOG.md.
        Creates the file with a header if it does not exist yet.
        """
        self._log_file.parent.mkdir(parents=True, exist_ok=True)

        if not self._log_file.exists():
            try:
                self._log_file.write_text(
                    "# David Self-Improvement Log\n\n"
                    "Append-only changelog of approved self-upgrades.\n\n"
                    "---\n\n",
                    encoding="utf-8",
                )
            except OSError:
                return

        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        signal_line = f"**Signal:** `{signal_code}` (severity {signal_severity}/100)\n" if signal_code else ""

        entry = (
            f"## v{version} — {timestamp}\n\n"
            f"**Title:** {title}\n"
            f"**File:** `{target_file}`\n"
            f"**Approved by:** {actor}\n"
            f"{signal_line}"
            f"\n"
            f"**Reasoning:** {reasoning}\n\n"
            "---\n\n"
        )

        try:
            with self._log_file.open("a", encoding="utf-8") as handle:
                handle.write(entry)
        except OSError:
            pass  # non-fatal
