# David App Architecture and Capabilities

Last updated: 2026-02-25

This document is a single reference for the app structure, code layout, workflow plan, feature set, module/function responsibilities, frameworks, and UI architecture.

## 1. App Overview

David is a local, safety-first coding agent with two interfaces:

1. CLI (`python -m agent.main`)
2. Local web control center (`python -m web.server`)

Primary goals:

1. Plan and execute coding tasks in isolated workspace projects.
2. Keep file writes and command execution inside strict safety boundaries.
3. Store reusable memory (facts, lessons, values, project knowledge, reflections).
4. Provide transparent run visibility (timeline, replay, compare, approvals, telemetry).

Core loop shape:

1. Planner
2. Coder
3. Safety guard
4. Executor
5. Critic
6. Memory update

## 2. Frameworks and Runtime Stack

Backend/runtime:

1. Python
2. Flask (web server and API)
3. requests (Ollama/local model HTTP calls)
4. python-dotenv (env config loading)
5. pytest (test suite)

Frontend:

1. Server-rendered static assets only
2. Vanilla HTML/CSS/JavaScript (`web/static/index.html`, `web/static/styles.css`, `web/static/app.js`)
3. EventSource/SSE streaming for status/log/run/voice stream channels

Model/runtime integrations:

1. Local Ollama (`/api/chat` for planner/coder/critic and optional upload vision enrichment)
2. Optional local STT:
   - Whisper CLI
   - whisper.cpp CLI
3. Optional local TTS:
   - Browser speech synthesis
   - Piper CLI

No React/Vue/Angular is used in current UI code.

## 3. High-Level Architecture

Main layers:

1. Agent layer (`agent/`)
   - Planning, coding, critique, safety validation, restricted execution, memory, telemetry.
2. Control center layer (`web/control_center.py`)
   - Run orchestration, approvals, chat/memory APIs, bundle import/export, uploads, self-improvement workflow.
3. API layer (`web/app.py`)
   - Route definitions, local-only and CSRF guards, input validation, SSE endpoints.
4. Web UI layer (`web/static/`)
   - Dashboard/tabs, run controls, memory chat, uploads, voice controls, streaming/poll fallback.
5. Persistence layer (`data/`, `memory/`, `logs/`, `workspace/`)
   - Runs, settings, uploads, memory facts/lessons, conversations, telemetry, project workspaces.

## 4. Repository Structure (Top-Level)

```text
agent/        # Core autonomous loop and contracts
web/          # Flask app, control center, voice/upload services, static UI
docs/         # Product and workflow documentation
tests/        # Pytest suite (agent + web + UI asset behavior)
memory/       # Long-term memory and conversation store
logs/         # Telemetry, metrics, web logs
data/         # Runs, settings, uploads, mock fixtures
workspace/    # Project-isolated coding workspace + sandbox areas
```

## 5. Code Map: Key Modules, Classes, and Functions

### `agent/` (core autonomy)

1. `agent/main.py`
   - CLI parser and mode routing (`--goal`, `--chat`, `--teach`, `--ask`, diagnostics).
   - `parse_chat_command` normalizes `/goal`, `/ask`, `/teach` commands.
2. `agent/loop.py`
   - `DavidAgent.run`: orchestrates Planner -> Coder -> Safety -> Executor -> Critic -> Memory loop.
   - Includes TDD phases, telemetry events, and iteration metrics.
3. `agent/config.py`
   - `AgentConfig`, environment parsing, bounds checking, local-only Ollama URL enforcement.
4. `agent/planner.py`
   - `Planner.create_plan` returns structured plan JSON; fallback plan on invalid model output.
5. `agent/coder.py`
   - `Coder.propose` returns edit/command JSON contract; safe fallback when JSON invalid.
6. `agent/critic.py`
   - `Critic.review` evaluates execution and proposes status/actions/lessons.
7. `agent/contracts.py`
   - Strict dataclass contracts for plan/coder/critic/execution payloads.
8. `agent/safety.py`
   - `SafetyGuard`: path boundary checks, write-size limits, command allow-list (`python`, `pytest`), per-iteration command limits.
9. `agent/executor.py`
   - `RestrictedExecutor`: `subprocess.run(shell=False)` with timeout, clipped output, minimal environment.
10. `agent/memory.py`
   - `LongTermMemory`: fact storage/search, lesson append/retrieval, sensitive-data rejection.
11. `agent/qa.py`
   - `MemoryTeacherQA`: explicit teach/ask path for factual memory.
12. `agent/projects.py`
   - Workspace/project isolation and per-goal project scaffolding under `workspace/projects/`.
13. `agent/telemetry.py`
   - Event and metric logging (`telemetry.jsonl`, `metrics.json`).
14. `agent/workspace.py`
   - Workspace snapshot generation for model context.

### `web/` (control center and API)

1. `web/server.py`
   - Web server entrypoint and bind configuration.
2. `web/app.py`
   - Flask app factory, local-only request guard, CSRF enforcement, API route map, SSE endpoints.
3. `web/control_center.py`
   - `DavidControlCenter` runtime manager.
   - Run lifecycle, approvals, replay/compare, bundle import/export, chat/memory, uploads, growth timeline, logs/telemetry APIs, self-improvement lifecycle.
4. `web/voice_service.py`
   - Local STT/TTS helpers, transcript normalization, command sanitization.
5. `web/upload_analysis.py`
   - Local analysis for `csv/xlsx/xls/pdf/png/jpg/jpeg/gif/bmp/webp`, plus upload Q&A.
6. `web/safety.py`
   - Run-id validation and workspace-relative path resolution helpers.

### `web/static/` (UI)

1. `index.html`
   - Tabbed interface and component layout.
2. `app.js`
   - App state store, API calls, streaming/poll fallback, run/memory/upload/voice flows, guided walkthrough.
3. `styles.css`
   - Theme variables (dark + light), layout components, responsive and animated UI styling.

## 6. Functional Workflow

### Goal execution flow

1. User submits goal (`CLI` or `POST /api/run`).
2. Project path resolved:
   - New isolated project under `workspace/projects/`, or
   - Existing workspace target folder/file context.
3. Planner generates structured plan.
4. Plan quality scorer evaluates clarity, testability, and risk coverage.
5. If score is below configured threshold, planner is retried once with quality feedback.
6. If the retried plan still scores below threshold, run stops with `planning_quality` failure before coding/execution.
7. Coder proposes full-file edits + allowed commands.
8. Safety guard validates edits and commands.
9. Executor runs commands with timeout/output limits.
10. Critic reviews results and returns `success|retry|abort` and lessons.
11. Lessons/reflections are persisted.
12. Artifacts are written to `data/runs/<run_id>/`.
13. Web UI streams status, logs, timeline updates.

### TDD mode behavior

1. Tests-first enforcement in early phase.
2. Requires observed failing pytest run before implementation success is allowed.
3. Auto-injects `pytest -q` if missing in iteration commands.

## 7. Feature and Capability Inventory

Core run management:

1. Queue/start/stop runs
2. Preview mode
3. Retry run
4. Goal templates (Build CLI Tool, Bug Fix Mode, Refactor Mode, Strict TDD Mode)
5. Workspace-targeted goal runs
6. Plan quality score gate with configurable threshold (`0-100`, `0=disabled`) and one auto-replan attempt

Safety controls:

1. Local-only server access
2. CSRF protection for state-changing endpoints
3. Command allow-list enforcement
4. Path traversal/absolute path/drive path rejection
5. Write-size and multi-command limits
6. Safe mode (read-only posture for risky operations)
7. Approval queue with optional typed confirmation for high-risk actions
8. Protected self-improvement paths (`agent/safety.py`, `web/safety.py`)

Run artifacts and observability:

1. Run metadata, per-iteration coder/execution/critic/diff/risk files
2. Timeline and audit trails
3. Replay/compare iteration viewer
4. Bundle export/import with read-only imported bundle inspection
5. Telemetry summary and regression warnings
6. Plan-quality analytics (reject/replan/recovery rates, score distribution, template bands)
6. Logs tail endpoints and UI log viewer

Memory and companion capabilities:

1. Facts, lessons, reflections, values, projects, conversation history
2. Teach conflict detection and overwrite confirmation flow
3. Ask memory-first responses with citations
4. Memory Insight traces of influences
5. Parent Teaching Mode and clarification prompts
6. Legacy Archive for significant moments
7. Companion mode with transparency and grief/crisis support overlays

Upload analysis:

1. Analyze supported file types locally
2. Table profiling for structured files (headers, sample rows, column profiles, numeric stats)
3. PDF/image content briefs
4. Ask questions about selected upload analysis
5. Optional local Ollama OCR/vision-style enrichment for images/PDF summaries

Voice mode (local):

1. Audio transcription endpoint (`/api/voice/transcribe`)
2. TTS chunk synthesis endpoint (`/api/voice/tts`)
3. Full chat stream endpoint (`/api/voice/chat/stream`)
4. Voice diagnostics and stream ping endpoints
5. VAD/manual modes, continual mode, pause/resume, barge-in and text-only options in UI
6. Voice goal confirmation gate (requires explicit confirmation for goal intent)

Autonomous self-improvement:

1. Proposal drafting into `workspace/agent_sandbox/`
2. Proposal review and merge/reject decision flow
3. Autonomous cycle triggers from run/conversation signals
4. Proposal lifecycle tracking and growth timeline integration

## 8. API Surface (Grouped)

Run and workflow:

1. `/api/status`, `/api/run`, `/api/stop`, `/api/runs`
2. `/api/run/<run_id>`, `/api/run/<run_id>/timeline`, `/api/run/<run_id>/files`
3. `/api/run/<run_id>/audit`, `/api/run/<run_id>/replay`, `/api/run/<run_id>/compare`
4. `/api/run/<run_id>/retry`, `/api/run/<run_id>/bundle`

Bundles/imports:

1. `/api/bundles/import`
2. `/api/bundles/imports`
3. `/api/bundles/import/<import_id>` plus timeline/files/audit/replay/compare

Workspace operations:

1. `/api/workspace/tree`
2. `/api/workspace/file/edit`
3. `/api/workspace/path/delete`
4. `/api/workspace/path/rename`

Memory/chat:

1. `/api/ask`, `/api/teach`, `/api/chat`
2. `/api/memory`, `/api/memory/facts`, `/api/memory/conversations`
3. `/api/memory/conversations/clear`, `/api/memory/confirm_overwrite`
4. `/api/chat/sessions`

Uploads:

1. `/api/uploads/analyze`, `/api/uploads`, `/api/uploads/<upload_id>`
2. `/api/uploads/<upload_id>/ask`

Voice:

1. `/api/voice/transcribe`, `/api/voice/tts`, `/api/voice/chat/stream`
2. `/api/voice/diagnostics`, `/api/voice/stream/ping`

Governance and system:

1. `/api/approvals`, `/api/approval/<approval_id>`
2. `/api/self_improvements`, `/api/self_improvements/propose`
3. `/api/self_improvements/autonomous_cycle`, `/api/self_improvements/<proposal_id>/decision`
4. `/api/legacy_archive`, `/api/legacy_archive/<entry_id>/remove`
5. `/api/telemetry/tail`, `/api/telemetry/plan_quality`, `/api/logs/tail`, `/api/growth_timeline`, `/api/models`, `/api/settings`
6. SSE: `/api/stream/status`, `/api/stream/logs`, `/api/stream/run/<run_id>`
7. Health: `/healthz`

## 9. Web UI Architecture

Main tabs:

1. Dashboard
2. Memory and Chat
3. Runs
4. Approvals
5. Diff Viewer
6. Memory
7. Telemetry
8. Logs
9. Settings

UI implementation notes:

1. Single-page style tab switching in `app.js`.
2. Stream-first updates via SSE, with timed polling fallback if stream disconnects.
3. Local state object tracks runs, memory, settings, uploads, voice, and selected entities.
4. Settings include model roles, safety/rate limits, voice, appearance, and demo controls.
   - includes `plan_quality_threshold` tuning.
5. Guided walkthrough is built into UI and pre-fills sample flows.
6. Theming supports dark/light modes and cinematic background toggle.
7. Run Health Summary surfaces plan quality score, pass/fail result, threshold, and subscores.

## 10. Data and Artifact Layout

Persistent stores:

1. `memory/long_term.json` (facts, lessons, values, projects, legacy archive)
2. `memory/conversations.jsonl`
3. `logs/telemetry.jsonl`
4. `logs/metrics.json`
5. `logs/web_control_center.log`
6. `data/control_settings.json`
7. `data/self_improvements.json`
8. `data/uploads/index.json` and `data/uploads/files/`

Run artifacts per run:

1. `data/runs/<run_id>/meta.json`
2. `data/runs/<run_id>/plan.json`
3. `data/runs/<run_id>/plan_quality.json`
4. `data/runs/<run_id>/timeline.jsonl`
5. `data/runs/<run_id>/audit.jsonl`
6. `data/runs/<run_id>/result.json`
7. `data/runs/<run_id>/iterations/<n>/coder.json`
8. `data/runs/<run_id>/iterations/<n>/execution.json`
9. `data/runs/<run_id>/iterations/<n>/critic.json`
10. `data/runs/<run_id>/iterations/<n>/diffs.json`
11. `data/runs/<run_id>/iterations/<n>/risk.json`

Plan quality operator policy:

1. Start threshold at `60` for mixed goals.
2. Raise gradually (`70-75`) once planner consistency is stable.
3. Keep `0` during exploratory phases where hard planning gates are undesirable.

## 11. Current Plan and Roadmap Snapshot

Source: `docs/AGENTIC_WORKFLOW_ROADMAP.md` (last updated 2026-02-22)

Non-negotiables:

1. Project-scoped writes only
2. Restricted command policy
3. Path traversal protections
4. Safety module edit protection
5. Human confirmation for high-impact actions

Milestones:

1. M1 (March 2026): Reliability and determinism
2. M2 (April 2026): Planning and edit quality
3. M3 (May 2026): Memory and learning effectiveness
4. M4 (June 2026): Human governance and operational scale

Priority backlog (next 6):

1. Harden preflight checks and failure messaging
2. Diff-based patch application path
3. Plan-quality scoring in run metadata
4. Bundle viewer regression expansion
5. Lesson ranking from run outcomes
6. Queue runner with bounded concurrency

## 12. Test Coverage Snapshot

Current suite:

1. 157 tests across agent, control center, web API, UI assets, voice, memory, and safety flows.
2. Coverage areas include:
   - safety/path/command guards
   - project layout/isolation
   - run lifecycle and artifacts
   - demo mode behavior
   - memory teach/ask/conflict flows
   - companion/memory-insight behaviors
   - upload analysis
   - voice settings/endpoints/state machine hooks
   - self-improvement lifecycle and policy protections

## 13. Related Docs

1. `README.md` - setup, usage, and high-level capabilities
2. `docs/WEB_UI.md` - deep web UI and testing guide
3. `docs/AGENTIC_WORKFLOW_ROADMAP.md` - roadmap and operating cadence
4. `docs/self_improvement_change_history.md` - proposal/change chronology
