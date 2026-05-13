"""Performance analyzer for David's self-improvement system.

Reads telemetry and metrics logs to produce quantitative weakness signals
that identify which module is most in need of improvement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Maps telemetry event types to the module they implicate
_EVENT_TO_MODULE: dict[str, str] = {
    "plan_quality_rejected": "agent/planner.py",
    "plan_quality_replan_requested": "agent/planner.py",
    "tdd_violation": "agent/planner.py",
    "safety_violation": "agent/coder.py",
    "execution_skipped": "agent/coder.py",
}

# Modules David is allowed to propose improvements for
EVOLVABLE_MODULES: frozenset[str] = frozenset({
    "agent/prompts.py",
    "agent/critic.py",
    "agent/planner.py",
    "agent/coder.py",
    "agent/memory.py",
    "agent/plan_quality.py",
})

_MAX_TELEMETRY_LINES = 2_000
_MIN_RETRY_RATE = 0.5
_MIN_COMMAND_FAIL_RATE = 0.4
_MIN_EVENT_RATE = 0.2
_MIN_FAIL_RATE = 0.6
_MIN_RUNS_FOR_FAIL_SIGNAL = 3


@dataclass(frozen=True)
class WeaknessSignal:
    """A single identified weakness in David's performance."""

    module_path: str   # relative path from project root, e.g. "agent/planner.py"
    signal_code: str   # machine-readable code, e.g. "high_retry_rate"
    evidence: str      # human-readable description of observed data
    severity: int      # 0–100, higher = more urgent


class PerformanceAnalyzer:
    """Reads logs/metrics.json and logs/telemetry.jsonl to find weakness signals."""

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir

    def analyze(self) -> list[WeaknessSignal]:
        """Return weakness signals sorted by descending severity. Never raises."""
        try:
            return self._analyze_inner()
        except Exception:  # pragma: no cover — defensive boundary
            return []

    def _analyze_inner(self) -> list[WeaknessSignal]:
        signals: list[WeaknessSignal] = []
        signals.extend(self._analyze_metrics(self._load_metrics()))
        signals.extend(self._analyze_events(self._load_telemetry_events()))

        # Deduplicate: same (module, signal_code) → keep highest severity
        deduped: dict[tuple[str, str], WeaknessSignal] = {}
        for signal in signals:
            key = (signal.module_path, signal.signal_code)
            if key not in deduped or signal.severity > deduped[key].severity:
                deduped[key] = signal

        return sorted(deduped.values(), key=lambda s: s.severity, reverse=True)

    # ------------------------------------------------------------------ loaders

    def _load_metrics(self) -> dict[str, Any]:
        path = self._logs_dir / "metrics.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_telemetry_events(self) -> list[dict[str, Any]]:
        path = self._logs_dir / "telemetry.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines[-_MAX_TELEMETRY_LINES:]:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    events.append(row)
            except json.JSONDecodeError:
                continue
        return events

    # ----------------------------------------------------------------- metrics

    def _analyze_metrics(self, metrics: dict[str, Any]) -> list[WeaknessSignal]:
        signals: list[WeaknessSignal] = []
        iterations = metrics.get("iterations", [])
        if not isinstance(iterations, list) or not iterations:
            return signals

        total = len(iterations)

        retry_count = sum(
            1 for i in iterations
            if isinstance(i, dict) and str(i.get("status", "")) == "retry"
        )
        retry_rate = retry_count / total

        failed_commands = sum(
            1 for i in iterations
            if isinstance(i, dict)
            and int(i.get("commands_total") or 0) > 0
            and int(i.get("commands_passed") or 0) < int(i.get("commands_total") or 0)
        )
        command_fail_rate = failed_commands / total

        if retry_rate >= _MIN_RETRY_RATE:
            signals.append(WeaknessSignal(
                module_path="agent/planner.py",
                signal_code="high_retry_rate",
                evidence=(
                    f"{retry_count}/{total} iterations needed retries "
                    f"({int(retry_rate * 100)}% retry rate). "
                    "Planner may be producing under-specified plans."
                ),
                severity=min(100, int(retry_rate * 100)),
            ))

        if command_fail_rate >= _MIN_COMMAND_FAIL_RATE:
            signals.append(WeaknessSignal(
                module_path="agent/coder.py",
                signal_code="high_command_failure_rate",
                evidence=(
                    f"{failed_commands}/{total} iterations had failing commands "
                    f"({int(command_fail_rate * 100)}% fail rate). "
                    "Coder may be producing code that does not run correctly."
                ),
                severity=min(100, int(command_fail_rate * 100)),
            ))

        return signals

    # ------------------------------------------------------------------ events

    def _analyze_events(self, events: list[dict[str, Any]]) -> list[WeaknessSignal]:
        signals: list[WeaknessSignal] = []

        total_runs = sum(
            1 for e in events
            if isinstance(e, dict) and e.get("event_type") == "run_complete"
        )
        if total_runs == 0:
            return signals

        # Count named event types
        event_counts: dict[str, int] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            etype = str(event.get("event_type", "")).strip()
            if etype in _EVENT_TO_MODULE:
                event_counts[etype] = event_counts.get(etype, 0) + 1

        for event_type, module_path in _EVENT_TO_MODULE.items():
            count = event_counts.get(event_type, 0)
            if count == 0:
                continue
            rate = count / total_runs
            if rate >= _MIN_EVENT_RATE:
                signals.append(WeaknessSignal(
                    module_path=module_path,
                    signal_code=event_type,
                    evidence=(
                        f"Event '{event_type}' occurred {count} times across "
                        f"{total_runs} runs ({int(rate * 100)}%). "
                        f"This indicates a recurring issue in {module_path}."
                    ),
                    severity=min(100, int(rate * 80) + 20),
                ))

        # Overall failure rate → critic may be too strict or missing recovery paths
        if total_runs >= _MIN_RUNS_FOR_FAIL_SIGNAL:
            failed_runs = sum(
                1 for e in events
                if isinstance(e, dict)
                and e.get("event_type") == "run_complete"
                and not bool((e.get("payload") or {}).get("success", True))
            )
            fail_rate = failed_runs / total_runs
            if fail_rate >= _MIN_FAIL_RATE:
                signals.append(WeaknessSignal(
                    module_path="agent/critic.py",
                    signal_code="low_success_rate",
                    evidence=(
                        f"{failed_runs}/{total_runs} runs failed "
                        f"({int(fail_rate * 100)}% failure rate). "
                        "Critic may be too strict or missing recoverable error paths."
                    ),
                    severity=min(100, int(fail_rate * 90)),
                ))

        return signals
