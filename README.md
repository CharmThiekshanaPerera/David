# David: Offline Self-Evolving Coding Agent

David is a local autonomous coding agent that runs fully offline with Ollama.
He is designed to act like a disciplined junior developer:

- plan first,
- code carefully,
- run safe tests,
- reflect on failures,
- learn from each iteration.

David is **not** a shell bot. He works inside strict safety boundaries.

## What David Does

For each goal, David runs this loop:

1. Planner creates a structured JSON plan and success criteria.
2. Coder proposes JSON file edits and allowed commands.
3. Safety Guard validates paths and write sizes.
4. Executor runs only whitelisted commands (`python`, `pytest`) in `workspace/`.
5. Critic reviews results and proposes improvements.
6. Memory stores lessons in `memory/long_term.json`.
7. Loop repeats until success or iteration limit.

## Safety Rules

David enforces:

- Workspace boundary: file edits are only allowed under `workspace/`.
- Path validation: no `..`, no absolute paths, no drive paths.
- Write limits: per-file and per-iteration byte limits.
- Command allow-list: only commands starting with `python` or `pytest`.
- No shell execution: commands run with `shell=False`.
- Local model only: Ollama URL must be localhost (`127.0.0.1` / `localhost`).

## Project Layout

- `agent/main.py`: CLI entry point (`python -m agent.main`)
- `agent/loop.py`: Planner -> Coder -> Safety -> Executor -> Critic -> Memory orchestrator
- `agent/planner.py`: plan generation contract
- `agent/coder.py`: edit/command proposal contract
- `agent/critic.py`: reflection + next actions contract
- `agent/safety.py`: path/size/command policy enforcement
- `agent/executor.py`: restricted command runner with timeouts
- `agent/memory.py`: long-term lessons store/retrieval
- `agent/telemetry.py`: structured telemetry and performance metrics
- `workspace/`: protected coding area for generated files
- `memory/long_term.json`: persistent lessons
- `logs/telemetry.jsonl`: reasoning/execution event log
- `logs/metrics.json`: iteration performance metrics

## Quick Start (Windows)

### 1. Open project directory

```powershell
cd "D:\Tech Agent Labs\David"
```

### 2. Create and activate virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment

```powershell
copy .env.example .env
```

Edit `.env` if needed (model name, limits, paths).

### 5. Start Ollama locally

In terminal A:

```powershell
ollama serve
```

In terminal B (first time only):

```powershell
ollama pull qwen2.5-coder:1.5b
```

Check model availability:

```powershell
ollama list
```

You should see `qwen2.5-coder:1.5b` in `ollama list`.

### 6. Run David

```powershell
python -m agent.main --goal "Create a Python TODO app with tests"
```

Or run diagnostics only:

```powershell
python -m agent.main --self-diagnostics
```

## How David Learns

- Each iteration can add reusable lessons to `memory/long_term.json`.
- Future goals load relevant lessons to avoid repeating mistakes.
- Telemetry logs each major step for debugging and auditability.

## Tests

Run:

```powershell
pytest -q
```

Current tests validate safety boundaries and executor timeout behavior.

## Suggested Evolution Roadmap

To grow David into a stronger autonomous engineer, add these next:

1. Git integration:
   Auto-commit successful iterations (`git add` + `git commit`) for rollback safety.
2. Diff-based editing:
   Generate patch-style edits and apply only changed lines.
3. Vector memory retrieval:
   Add embedding-based similarity search for better lesson recall.
4. Test-first mode:
   Force `tests first, implementation second` workflow.
5. Task queue:
   Queue and schedule multiple long-running goals.
6. Self-diagnostics hardening:
   Run periodic checks for policy drift and unsafe config changes.
7. Performance analytics:
   Track token usage, pass rate, retry count, and time-to-success trends.
8. Structured telemetry enrichment:
   Add trace IDs and iteration state snapshots for post-mortem analysis.
9. Optional web dashboard:
   Local dashboard showing plans, edits, command outputs, and memory history.

## Notes

- David is intentionally cautious and bounded.
- He improves through iterative reflection, not reckless autonomy.
- Keep goals specific and testable for best results.
