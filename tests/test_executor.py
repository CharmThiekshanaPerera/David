from __future__ import annotations

from agent.executor import RestrictedExecutor
from agent.safety import CommandSpec


def test_executor_runs_python_command(tmp_path):
    executor = RestrictedExecutor(workspace_dir=tmp_path, timeout_sec=5, max_output_chars=1000)
    result = executor.run([CommandSpec(raw="python -c \"print('ok')\"", argv=["python", "-c", "print('ok')"])])[0]

    assert result.returncode == 0
    assert "ok" in result.stdout
    assert result.timed_out is False


def test_executor_reports_timeout(tmp_path):
    executor = RestrictedExecutor(workspace_dir=tmp_path, timeout_sec=1, max_output_chars=1000)
    spec = CommandSpec(
        raw="python -c \"import time; time.sleep(2)\"",
        argv=["python", "-c", "import time; time.sleep(2)"],
    )

    result = executor.run([spec])[0]

    assert result.timed_out is True
    assert result.returncode == 124
