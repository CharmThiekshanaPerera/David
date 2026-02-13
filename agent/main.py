from __future__ import annotations

import argparse
import json
import sys

from agent.config import AgentConfig, load_config
from agent.loop import DavidAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="David: local safety-first autonomous coding agent")
    parser.add_argument("--goal", type=str, help="Goal for David to execute")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Override maximum iteration count for this run",
    )
    parser.add_argument(
        "--self-diagnostics",
        action="store_true",
        help="Run local safety/config diagnostics and exit",
    )
    return parser


def run_diagnostics(config: AgentConfig) -> int:
    report = {
        "project_root": str(config.project_root),
        "workspace_dir": str(config.workspace_dir),
        "memory_file": str(config.memory_file),
        "logs_dir": str(config.logs_dir),
        "model": config.model,
        "ollama_url": config.ollama_url,
        "allowed_commands": list(config.allowed_commands),
        "checks": {
            "workspace_exists": config.workspace_dir.exists(),
            "memory_file_exists": config.memory_file.exists(),
            "logs_dir_exists": config.logs_dir.exists(),
        },
    }

    try:
        payload = json.loads(config.memory_file.read_text(encoding="utf-8"))
        report["checks"]["memory_json_valid"] = isinstance(payload, dict)
    except Exception:
        report["checks"]["memory_json_valid"] = False

    print(json.dumps(report, indent=2))
    return 0 if all(bool(value) for value in report["checks"].values()) else 1


def _resolve_goal(raw_goal: str | None) -> str:
    if raw_goal and raw_goal.strip():
        return raw_goal.strip()

    print("Enter goal for David:")
    typed = input("> ").strip()
    if not typed:
        raise ValueError("Goal cannot be empty.")
    return typed


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if args.self_diagnostics:
        return run_diagnostics(config)

    try:
        goal = _resolve_goal(args.goal)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    agent = DavidAgent(config)

    try:
        summary = agent.run(goal=goal, max_iterations=args.max_iterations)
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Agent failed: {exc}", file=sys.stderr)
        return 1

    print("=== David Run Summary ===")
    print(f"Goal: {summary.goal}")
    print(f"Success: {summary.success}")
    print(f"Iterations used: {summary.iterations_used}")
    print(f"Message: {summary.message}")
    print(f"Telemetry: {config.logs_dir.joinpath('telemetry.jsonl').as_posix()}")
    print(f"Memory: {config.memory_file.as_posix()}")
    if summary.success:
        print("Task completed successfully.")

    return 0 if summary.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
