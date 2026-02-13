from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IterationMetric:
    iteration: int
    status: str
    duration_sec: float
    commands_total: int
    commands_passed: int


class TelemetryLogger:
    """Writes structured JSON logs for traceability and diagnostics."""

    def __init__(self, logs_dir: Path) -> None:
        self._events_path = logs_dir / "telemetry.jsonl"
        self._metrics_path = logs_dir / "metrics.json"
        logs_dir.mkdir(parents=True, exist_ok=True)
        if not self._metrics_path.exists():
            self._metrics_path.write_text('{"iterations": []}\n', encoding="utf-8")

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        with self._events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def metric(self, metric: IterationMetric) -> None:
        data = self._read_metrics()
        rows = data.setdefault("iterations", [])
        rows.append(asdict(metric))
        self._metrics_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def _read_metrics(self) -> dict[str, Any]:
        try:
            data = json.loads(self._metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"iterations": []}
        if not isinstance(data, dict):
            data = {"iterations": []}
        if not isinstance(data.get("iterations"), list):
            data["iterations"] = []
        return data
