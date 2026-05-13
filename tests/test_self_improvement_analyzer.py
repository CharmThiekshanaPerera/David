"""Tests for agent.self_improvement.analyzer — PerformanceAnalyzer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.self_improvement.analyzer import (
    EVOLVABLE_MODULES,
    PerformanceAnalyzer,
    WeaknessSignal,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _write_metrics(logs_dir: Path, iterations: list[dict]) -> None:
    (logs_dir / "metrics.json").write_text(
        json.dumps({"iterations": iterations}), encoding="utf-8"
    )


def _write_telemetry(logs_dir: Path, events: list[dict]) -> None:
    lines = [json.dumps(e) for e in events]
    (logs_dir / "telemetry.jsonl").write_text("\n".join(lines), encoding="utf-8")


def _run_complete(success: bool) -> dict:
    return {"event_type": "run_complete", "payload": {"success": success}}


def _event(event_type: str) -> dict:
    return {"event_type": event_type, "payload": {}}


# ─── analyzer: empty / missing state ──────────────────────────────────────────

def test_analyze_returns_empty_when_no_logs(tmp_path):
    analyzer = PerformanceAnalyzer(tmp_path)
    assert analyzer.analyze() == []


def test_analyze_returns_empty_when_metrics_empty(tmp_path):
    _write_metrics(tmp_path, [])
    analyzer = PerformanceAnalyzer(tmp_path)
    assert analyzer.analyze() == []


def test_analyze_returns_empty_when_telemetry_has_no_run_complete(tmp_path):
    _write_telemetry(tmp_path, [_event("coder_output"), _event("plan_created")])
    analyzer = PerformanceAnalyzer(tmp_path)
    assert analyzer.analyze() == []


def test_analyze_does_not_raise_on_corrupt_metrics(tmp_path):
    (tmp_path / "metrics.json").write_text("not json{{{{", encoding="utf-8")
    analyzer = PerformanceAnalyzer(tmp_path)
    assert analyzer.analyze() == []


def test_analyze_does_not_raise_on_corrupt_telemetry(tmp_path):
    (tmp_path / "telemetry.jsonl").write_text("bad line\n{broken", encoding="utf-8")
    analyzer = PerformanceAnalyzer(tmp_path)
    assert analyzer.analyze() == []


# ─── metrics: high retry rate ─────────────────────────────────────────────────

def test_high_retry_rate_produces_planner_signal(tmp_path):
    # 6 retries out of 8 → 75% retry rate, above 50% threshold
    iterations = [{"status": "retry"}] * 6 + [{"status": "success"}] * 2
    _write_metrics(tmp_path, iterations)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    planner_signals = [s for s in signals if s.module_path == "agent/planner.py"]
    assert any(s.signal_code == "high_retry_rate" for s in planner_signals)


def test_low_retry_rate_produces_no_retry_signal(tmp_path):
    # 1 retry out of 8 → 12.5%, below 50% threshold
    iterations = [{"status": "retry"}] * 1 + [{"status": "success"}] * 7
    _write_metrics(tmp_path, iterations)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert not any(s.signal_code == "high_retry_rate" for s in signals)


def test_high_retry_rate_severity_proportional_to_rate(tmp_path):
    # 8/8 retries → severity 100
    _write_metrics(tmp_path, [{"status": "retry"}] * 8)
    signals = PerformanceAnalyzer(tmp_path).analyze()
    retry_signals = [s for s in signals if s.signal_code == "high_retry_rate"]
    assert retry_signals
    assert retry_signals[0].severity == 100


# ─── metrics: high command failure rate ───────────────────────────────────────

def test_high_command_fail_rate_produces_coder_signal(tmp_path):
    # 5/8 iterations had failing commands → 62% fail rate, above 40% threshold
    iterations = (
        [{"status": "retry", "commands_total": 2, "commands_passed": 0}] * 5
        + [{"status": "success", "commands_total": 2, "commands_passed": 2}] * 3
    )
    _write_metrics(tmp_path, iterations)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert any(s.signal_code == "high_command_failure_rate" and s.module_path == "agent/coder.py"
               for s in signals)


def test_low_command_fail_rate_no_signal(tmp_path):
    # 2/8 → 25%, below 40% threshold
    iterations = (
        [{"status": "retry", "commands_total": 2, "commands_passed": 0}] * 2
        + [{"status": "success", "commands_total": 2, "commands_passed": 2}] * 6
    )
    _write_metrics(tmp_path, iterations)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert not any(s.signal_code == "high_command_failure_rate" for s in signals)


# ─── telemetry: named event signals ───────────────────────────────────────────

def test_safety_violation_events_produce_coder_signal(tmp_path):
    # 3 safety_violations in 5 runs → 60% rate, above 20% threshold
    events = [_run_complete(True)] * 5 + [_event("safety_violation")] * 3
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert any(s.signal_code == "safety_violation" and s.module_path == "agent/coder.py"
               for s in signals)


def test_plan_quality_rejected_events_produce_planner_signal(tmp_path):
    # 2 plan_quality_rejected in 4 runs → 50% rate, above 20% threshold
    events = [_run_complete(True)] * 4 + [_event("plan_quality_rejected")] * 2
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert any(s.signal_code == "plan_quality_rejected" and s.module_path == "agent/planner.py"
               for s in signals)


def test_rare_events_below_threshold_produce_no_signal(tmp_path):
    # 1 safety_violation in 20 runs → 5% rate, below 20% threshold
    events = [_run_complete(True)] * 20 + [_event("safety_violation")] * 1
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert not any(s.signal_code == "safety_violation" for s in signals)


# ─── telemetry: low overall success rate ──────────────────────────────────────

def test_low_success_rate_produces_critic_signal(tmp_path):
    # 5 failed out of 6 runs → 83% failure rate, above 60% threshold, and ≥3 runs
    events = [_run_complete(False)] * 5 + [_run_complete(True)] * 1
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert any(s.signal_code == "low_success_rate" and s.module_path == "agent/critic.py"
               for s in signals)


def test_low_success_rate_not_triggered_below_min_runs(tmp_path):
    # Only 2 runs total — below the minimum of 3 for this signal
    events = [_run_complete(False)] * 2
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert not any(s.signal_code == "low_success_rate" for s in signals)


def test_good_success_rate_no_critic_signal(tmp_path):
    # 5 successes out of 6 → only 16% failure rate, below 60%
    events = [_run_complete(True)] * 5 + [_run_complete(False)] * 1
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    assert not any(s.signal_code == "low_success_rate" for s in signals)


# ─── deduplication and ordering ───────────────────────────────────────────────

def test_signals_sorted_by_severity_descending(tmp_path):
    # Create conditions for multiple signals with different severities
    iterations = [{"status": "retry"}] * 8  # 100% retry rate → severity 100
    _write_metrics(tmp_path, iterations)
    events = [_run_complete(True)] * 10 + [_event("safety_violation")] * 3  # 30% rate
    _write_telemetry(tmp_path, events)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    severities = [s.severity for s in signals]
    assert severities == sorted(severities, reverse=True)


def test_duplicate_module_signal_code_deduped_to_highest_severity(tmp_path):
    # Build telemetry that generates the same (module, signal_code) from two paths
    # high_retry_rate can come from both metrics and events — ensure deduplication
    iterations = [{"status": "retry"}] * 8
    _write_metrics(tmp_path, iterations)

    signals = PerformanceAnalyzer(tmp_path).analyze()

    # Count occurrences of same (module_path, signal_code) combinations
    seen: dict[tuple[str, str], int] = {}
    for s in signals:
        key = (s.module_path, s.signal_code)
        seen[key] = seen.get(key, 0) + 1

    assert all(count == 1 for count in seen.values()), "Duplicate (module, signal_code) found"


# ─── WeaknessSignal dataclass ─────────────────────────────────────────────────

def test_weakness_signal_is_frozen():
    signal = WeaknessSignal(
        module_path="agent/planner.py",
        signal_code="high_retry_rate",
        evidence="50% retry rate",
        severity=50,
    )
    with pytest.raises((AttributeError, TypeError)):
        signal.severity = 99  # type: ignore[misc]


# ─── evolvable modules constant ───────────────────────────────────────────────

def test_evolvable_modules_excludes_safety_and_executor():
    assert "agent/safety.py" not in EVOLVABLE_MODULES
    assert "agent/executor.py" not in EVOLVABLE_MODULES
    assert "web/safety.py" not in EVOLVABLE_MODULES
    assert "agent/config.py" not in EVOLVABLE_MODULES


def test_evolvable_modules_includes_expected_targets():
    assert "agent/planner.py" in EVOLVABLE_MODULES
    assert "agent/coder.py" in EVOLVABLE_MODULES
    assert "agent/critic.py" in EVOLVABLE_MODULES
    assert "agent/prompts.py" in EVOLVABLE_MODULES
