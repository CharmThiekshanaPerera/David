# ARCHITECTURE.md — Project Architecture (Overview)

Last updated: 2026-11-14

This is the short, navigable overview. For the full reference (module-by-module
responsibilities, frameworks, UI architecture, data flows), see
[`docs/APP_ARCHITECTURE_AND_CAPABILITIES.md`](docs/APP_ARCHITECTURE_AND_CAPABILITIES.md).
For the agent roles themselves, see [`AGENTS.md`](AGENTS.md). For capabilities, see
[`SKILLS.md`](SKILLS.md). For setup, see [`RUNNING.md`](RUNNING.md).

## What David is

A local, offline, safety-first autonomous coding agent with two front ends (CLI,
Flask web Control Center) sharing one core loop:

```
Planner -> Coder -> Safety Guard -> Executor -> Critic -> Memory
```

Everything runs against a local Ollama instance (`127.0.0.1:11434` only — remote
Ollama URLs are rejected by design). No cloud model calls, no telemetry leaves the
machine.

## Top-level layout

```
agent/        Core loop, contracts, prompts, safety, memory, browser tool, self-improvement
web/          Flask app, control center orchestration, voice/vision services, static UI
config/       Browser domain policy
data/         Runtime settings (control_settings.json) — overrides .env for the web UI
docs/         Detailed architecture, workflow roadmap, web UI reference
memory/       long_term.json (facts/lessons/preferences), conversations.jsonl
logs/         telemetry.jsonl (event log), metrics.json
workspace/    Isolated per-goal project directories (all agent file writes land here)
tests/        Pytest suite
.venv-win/    Project virtual environment (not portable — see RUNNING.md before moving)
```

## Layers (see `docs/APP_ARCHITECTURE_AND_CAPABILITIES.md` §3 for full detail)

1. **Agent layer** (`agent/`) — planning, coding, critique, safety validation,
   restricted execution, memory, telemetry. No Flask/HTTP dependency; usable standalone
   via the CLI.
2. **Control center layer** (`web/control_center.py`) — run orchestration, approvals,
   chat/memory APIs, bundle import/export, uploads, self-improvement workflow. This is
   the biggest single file in the project and the integration point between the agent
   layer and the web UI.
3. **API layer** (`web/app.py`) — Flask routes, local-only + CSRF guards, SSE
   endpoints.
4. **Web UI layer** (`web/static/`) — vanilla HTML/CSS/JS, no frontend framework.
5. **Persistence layer** (`data/`, `memory/`, `logs/`, `workspace/`) — flat
   JSON/JSONL files, no database.

## Safety boundary (the part that must never regress)

- File writes: only inside `workspace/projects/<project_slug>/`, never the workspace
  root, never outside it (`agent/safety.py`).
- Commands: only `python`/`pytest`-prefixed, run with `shell=False`, under a timeout,
  in a trimmed environment (`agent/executor.py`).
- Ollama URL must resolve to localhost.
- `agent/safety.py` and `web/safety.py` are meant to be off-limits to autonomous
  self-edits.

## Where to look for X

| Question | Look at |
|---|---|
| What model does role Y use right now? | `data/control_settings.json` (web UI), `.env` (CLI fallback) — see `RUNNING.md` §3 |
| Why did a run fail? | `logs/telemetry.jsonl`, filtered by date + `event_type` — see `AGENTS.md`'s "Debugging a run" |
| What can David actually do today? | `SKILLS.md` |
| What are the internal agent roles and their prompts? | `AGENTS.md`, `agent/prompts.py` |
| How do I stand this up on a new machine? | `RUNNING.md` |
| Full architecture reference | `docs/APP_ARCHITECTURE_AND_CAPABILITIES.md` |
| Web UI reference | `docs/WEB_UI.md` |
| Longer-range roadmap | `docs/AGENTIC_WORKFLOW_ROADMAP.md`, `SKILLS.md`'s Roadmap section |
