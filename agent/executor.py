from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from agent.contracts import ExecutionResult
from agent.safety import CommandSpec


class RestrictedExecutor:
    """Runs only pre-validated commands in the protected workspace."""

    def __init__(self, workspace_dir: Path, timeout_sec: int, max_output_chars: int) -> None:
        self._workspace_dir = workspace_dir
        self._timeout_sec = timeout_sec
        self._max_output_chars = max_output_chars

    def run(self, commands: list[CommandSpec]) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for spec in commands:
            results.append(self._run_one(spec))
        return results

    def _run_one(self, spec: CommandSpec) -> ExecutionResult:
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                spec.argv,
                cwd=self._workspace_dir,
                capture_output=True,
                text=True,
                timeout=self._timeout_sec,
                shell=False,
                env=self._safe_env(),
            )
            duration = time.perf_counter() - start
            return ExecutionResult(
                command=spec.raw,
                returncode=completed.returncode,
                stdout=self._clip(completed.stdout),
                stderr=self._clip(completed.stderr),
                timed_out=False,
                duration_sec=round(duration, 3),
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - start
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return ExecutionResult(
                command=spec.raw,
                returncode=124,
                stdout=self._clip(stdout),
                stderr=self._clip(stderr),
                timed_out=True,
                duration_sec=round(duration, 3),
            )

    def _clip(self, text: str) -> str:
        if len(text) <= self._max_output_chars:
            return text
        return text[: self._max_output_chars] + "\n...[truncated]"

    @staticmethod
    def _safe_env() -> dict[str, str]:
        # Keep a small environment surface to avoid accidental secret leakage.
        safe_keys = {"PATH", "SYSTEMROOT", "WINDIR", "VIRTUAL_ENV", "PYTHONPATH"}
        env = {key: value for key, value in os.environ.items() if key in safe_keys}
        env["PYTHONIOENCODING"] = "utf-8"
        return env
