from __future__ import annotations

import argparse
import json
import sys

import json as _json

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
    parser.add_argument(
        "--propose-improvement",
        action="store_true",
        help=(
            "Analyze David's telemetry, generate a self-improvement proposal, "
            "and stage it for Web UI review. Requires Ollama to be running."
        ),
    )
    return parser


def run_diagnostics(config: AgentConfig) -> int:
    report = {
        "project_root": str(config.project_root),
        "workspace_dir": str(config.workspace_dir),
        "memory_file": str(config.memory_file),
        "logs_dir": str(config.logs_dir),
        "model": config.model,
        "planner_model": config.planner_model,
        "coder_model": config.coder_model,
        "critic_model": config.critic_model,
        "tdd_mode": config.tdd_mode,
        "plan_quality_threshold": config.plan_quality_threshold,
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


def run_propose_improvement(config: AgentConfig) -> int:
    """
    Analyze telemetry, generate a self-improvement proposal via the local LLM,
    validate it, and write it to data/self_improvements.json for Web UI review.
    """
    from agent.self_improvement.analyzer import PerformanceAnalyzer
    from agent.self_improvement.proposer import ImprovementProposer
    from agent.self_improvement.stager import ProposalStager, build_proposal_record
    from agent.self_improvement.version_manager import VersionManager

    print("=== David Self-Improvement Cycle ===")

    # Step 1 — Analyze telemetry for weakness signals
    print("Step 1/4  Analyzing telemetry and metrics...")
    analyzer = PerformanceAnalyzer(config.logs_dir)
    signals = analyzer.analyze()

    if not signals:
        print("No actionable weakness signals found in telemetry.")
        print("Run more goals first so David has enough data to self-improve.")
        return 0

    top = signals[0]
    print(f"          Top signal: [{top.signal_code}] severity={top.severity}/100")
    print(f"          Module:     {top.module_path}")
    print(f"          Evidence:   {top.evidence}")

    # Step 2 — Generate improvement proposal with local LLM
    print("Step 2/4  Generating improvement proposal (calling Ollama)...")
    llm = OllamaClient(config)
    proposer = ImprovementProposer(llm, config.project_root)
    proposal = proposer.propose(top)

    if proposal is None:
        print("Could not generate a proposal.")
        print("Possible reasons: target file is blocked, LLM returned no change, or Ollama is unreachable.")
        return 1

    print(f"          Reasoning:  {proposal.reasoning[:120]}...")

    # Step 3 — Stage and validate
    sandbox_root = (config.workspace_dir / "agent_sandbox").resolve()
    sandbox_root.mkdir(parents=True, exist_ok=True)
    print("Step 3/4  Validating (syntax check + test suite)...")
    stager = ProposalStager(config.project_root, sandbox_root)
    staging = stager.stage(proposal)

    if not staging.success:
        print(f"Staging failed: {staging.error}")
        return 1

    syntax_label = "✅ OK" if staging.syntax_ok else "❌ FAILED"
    tests_label = "✅ passed" if staging.tests_passed else "⚠️  failed (review carefully)"
    print(f"          Syntax:     {syntax_label}")
    print(f"          Tests:      {tests_label}")

    # Step 4 — Write proposal record to data/self_improvements.json
    print("Step 4/4  Writing proposal for Web UI review...")
    data_dir = (config.project_root / "data").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    si_file = data_dir / "self_improvements.json"

    try:
        existing = _json.loads(si_file.read_text(encoding="utf-8")) if si_file.exists() else {}
    except (_json.JSONDecodeError, OSError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    proposals = existing.get("proposals", [])
    if not isinstance(proposals, list):
        proposals = []

    record = build_proposal_record(staging, proposal)
    proposals.append(record)
    si_file.write_text(_json.dumps({"proposals": proposals}, indent=2) + "\n", encoding="utf-8")

    vm = VersionManager(config.project_root)
    print()
    print("=== Proposal Created ===")
    print(f"  ID:          {staging.proposal_id}")
    print(f"  Target:      {proposal.target_path}")
    print(f"  Sandbox:     {staging.sandbox_dir}")
    print(f"  Current ver: {vm.current_version()}")
    print()
    print("Open the Web UI → Dashboard → Proposed Improvements to review and approve.")
    print("Approving will apply the change and bump the VERSION to the next patch release.")
    return 0


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

    if args.propose_improvement:
        try:
            return run_propose_improvement(config)
        except Exception as exc:
            print(f"Self-improvement cycle failed: {exc}", file=sys.stderr)
            return 1

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
