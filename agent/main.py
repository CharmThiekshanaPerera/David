from __future__ import annotations

import argparse
import json
import sys

from agent.config import AgentConfig, load_config
from agent.loop import DavidAgent
from agent.llm import OllamaClient
from agent.memory import LongTermMemory
from agent.qa import MemoryTeacherQA


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="David: local safety-first autonomous coding agent")
    parser.add_argument("--goal", type=str, help="Goal for David to execute")
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Run David in continuous interactive mode until you type bye.",
    )
    parser.add_argument(
        "--teach",
        type=str,
        help="Explicitly teach David facts from a natural-language message.",
    )
    parser.add_argument(
        "--ask",
        type=str,
        help="Ask David a question that must be answered from stored memory facts.",
    )
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


def run_teach(config: AgentConfig, message: str) -> int:
    memory = LongTermMemory(config.memory_file)
    llm = OllamaClient(config)
    teacher = MemoryTeacherQA(llm=llm, memory=memory)
    result = teacher.teach(message)

    print("=== David Teaching Summary ===")
    print(f"Input: {message.strip()}")
    print(f"Stored facts: {len(result.stored_facts)}")
    for fact in result.stored_facts:
        print(f"- {fact.subject}.{fact.predicate} = {fact.object}")
    if result.skipped_items:
        print("Skipped:")
        for item in result.skipped_items:
            print(f"- {item}")
    if result.notes:
        print(f"Notes: {result.notes}")
    return 0


def run_ask(config: AgentConfig, question: str) -> int:
    memory = LongTermMemory(config.memory_file)
    llm = OllamaClient(config)
    teacher = MemoryTeacherQA(llm=llm, memory=memory)
    answer = teacher.ask(question)

    print("=== David Memory Answer ===")
    print(f"Question: {question.strip()}")
    print(f"Answer: {answer}")
    return 0


def parse_chat_command(raw_text: str) -> tuple[str, str] | None:
    text = raw_text.strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in {"bye", "exit", "quit"}:
        return ("exit", "")
    if lowered in {"help", "/help"}:
        return ("help", "")
    if lowered.startswith("/teach "):
        return ("teach", text[7:].strip())
    if lowered.startswith("/ask "):
        return ("ask", text[5:].strip())
    if lowered.startswith("/goal "):
        return ("goal", text[6:].strip())
    return ("unknown", text)


def run_chat(config: AgentConfig) -> int:
    print("=== David Interactive Mode ===")
    print("Use commands: /goal <task>, /ask <question>, /teach <fact>. Type 'bye' to exit.")
    agent = DavidAgent(config)

    while True:
        try:
            raw = input("you> ")
        except EOFError:
            print("David: Bye.")
            return 0

        parsed = parse_chat_command(raw)
        if parsed is None:
            continue
        mode, payload = parsed

        if mode == "exit":
            print("David: Bye.")
            return 0
        if mode == "help":
            print("Commands:")
            print("- /goal <task>")
            print("- /ask <question>")
            print("- /teach <message>")
            print("- bye")
            continue
        if mode == "unknown":
            print("David: Use /goal, /ask, or /teach. Type /help for options.")
            continue
        if not payload:
            print("David: Command content cannot be empty.")
            continue

        if mode == "teach":
            try:
                run_teach(config, payload)
            except Exception as exc:
                print(f"David: teach failed: {exc}")
            continue
        if mode == "ask":
            try:
                run_ask(config, payload)
            except Exception as exc:
                print(f"David: ask failed: {exc}")
            continue

        try:
            summary = agent.run(goal=payload, max_iterations=None)
            print("=== David Run Summary ===")
            print(f"Goal: {summary.goal}")
            print(f"Success: {summary.success}")
            print(f"Iterations used: {summary.iterations_used}")
            print(f"Message: {summary.message}")
            if summary.success:
                print("Task completed successfully.")
        except Exception as exc:
            print(f"David: goal failed: {exc}")


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

    chosen_modes = sum(
        1
        for value in (args.goal, args.teach, args.ask)
        if isinstance(value, str) and value.strip()
    )
    if args.chat and chosen_modes:
        print("Use --chat by itself or use one of --goal, --teach, --ask.", file=sys.stderr)
        return 1
    if chosen_modes > 1:
        print("Use only one of --goal, --teach, or --ask at a time.", file=sys.stderr)
        return 1
    if args.chat:
        return run_chat(config)
    if args.teach and args.teach.strip():
        try:
            return run_teach(config, args.teach)
        except Exception as exc:
            print(f"Teach failed: {exc}", file=sys.stderr)
            return 1
    if args.ask and args.ask.strip():
        try:
            return run_ask(config, args.ask)
        except Exception as exc:
            print(f"Ask failed: {exc}", file=sys.stderr)
            return 1
    if not args.goal:
        return run_chat(config)

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
