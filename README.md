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
4. Executor runs only whitelisted commands (`python`, `pytest`) inside the active project folder.
5. Critic reviews results and proposes improvements.
6. Memory stores lessons in `memory/long_term.json`.
7. Loop repeats until success or iteration limit.

## Safety Rules

David enforces:

- Workspace boundary: file edits are only allowed under `workspace/projects/<project_slug>/`.
- Path validation: no `..`, no absolute paths, no drive paths.
- Write limits: per-file and per-iteration byte limits.
- Command allow-list: only commands starting with `python` or `pytest`.
- No shell execution: commands run with `shell=False`.
- Local model only: Ollama URL must be localhost (`127.0.0.1` / `localhost`).

## Per-Role Models and TDD Mode

David supports separate local models per role while preserving single-model fallback.

- Planner uses `PLANNER_MODEL`
- Coder uses `CODER_MODEL`
- Critic uses `CRITIC_MODEL`
- Unset role values fall back to `DAVID_MODEL`
- TDD-first behavior is controlled by `TDD_MODE=true|false`

Example `.env`:

```env
DAVID_MODEL=qwen2.5-coder:1.5b
PLANNER_MODEL=llama3.2:3b
CODER_MODEL=qwen2.5-coder:1.5b
CRITIC_MODEL=deepseek-r1:7b
TDD_MODE=false
```

TDD mode behavior:

- Planner is instructed to write tests first.
- Tests are expected under `workspace/projects/<project_slug>/tests/`.
- The loop expects a failing pytest run first (red), then implementation, then green.
- All safety constraints stay active (allow-list, sandbox, workspace-only writes).

## Workspace Architecture (Project Isolation)

David now isolates each new goal into its own project directory so files from different goals never mix.

- Root `workspace/` stays structured:
  - `workspace/projects/`
  - `workspace/templates/`
  - `workspace/scratch/`
  - optional `workspace/active_project.json` (tracks the current project)
- Every new `/goal` creates a dedicated folder:
  - `workspace/projects/<project_slug>/`
  - slug is normalized from goal text (lowercase, underscores, unsafe chars removed)
  - if the slug already exists, a timestamp suffix is appended
- Required project structure:
  - `src/`
  - `tests/`
  - `docs/`
  - `data/`
  - `config/`
  - `README.md`
- Safety behavior:
  - all generated paths are validated relative to the active project root
  - no absolute writes, no `..` traversal, no writes outside the project folder
  - existing legacy files under `workspace/` are not deleted, but new writes are project-scoped

## Project Layout

- `agent/main.py`: CLI entry point (`python -m agent.main`)
- `agent/loop.py`: Planner -> Coder -> Safety -> Executor -> Critic -> Memory orchestrator
- `agent/planner.py`: plan generation contract
- `agent/coder.py`: edit/command proposal contract
- `agent/critic.py`: reflection + next actions contract
- `agent/safety.py`: path/size/command policy enforcement
- `agent/executor.py`: restricted command runner with timeouts
- `agent/memory.py`: long-term lessons store/retrieval
- `agent/qa.py`: explicit teach/ask fact memory pathway
- `agent/telemetry.py`: structured telemetry and performance metrics
- `workspace/projects/`: isolated project roots for goal runs
- `workspace/templates/`: reusable starter assets
- `workspace/scratch/`: temporary scratch space
- `workspace/active_project.json`: current active project pointer
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

### 7. Teach David Facts (Explicit Memory Write)

David writes personal facts to long-term memory only when you use `--teach`.
Normal `--goal` runs do not save personal facts.

```powershell
python -m agent.main --teach "Hi David I am your dad. My Name is Charm Thiekshana."
```

Expected teaching confirmation includes stored facts such as:

```text
- David.father_name = Charm Thiekshana
```

Ask later using memory-only retrieval:

```powershell
python -m agent.main --ask "Who is your father?"
```

Expected answer:

```text
My father is Charm Thiekshana.
```

Memory file schema (`memory/long_term.json`) now includes explicit factual memory:

```json
{
  "facts": [
    {
      "subject": "David",
      "predicate": "father_name",
      "object": "Charm Thiekshana",
      "source": "user_teach",
      "confidence": 1.0,
      "timestamp": "2026-01-01T00:00:00+00:00"
    }
  ],
  "lessons": [],
  "preferences": []
}
```

Reflection entries are stored in `lessons` with metadata such as:
- `"kind": "reflection"`
- `"source": "reflection_engine"`
- `"reflection_key": "run:<run_id>"` or `"conversation:<message_id>"`

## Quick Start (WSL)

> If you already created `.venv` in Windows, create a separate WSL virtual environment because Windows and Linux venvs are not interchangeable.

### 1. Open project directory in WSL

```bash
cd "/mnt/d/Tech Agent Labs/David"
```

### 2. Create and activate virtual environment

```bash
python3 -m venv .venv-linux
source .venv-linux/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` if needed (model name, limits, paths).

### 5. Start Ollama locally

In terminal A:

```bash
ollama serve
```

If you see `bind: address already in use`, Ollama is already running on `127.0.0.1:11434` and you can continue.

In terminal B (first time only):

```bash
ollama pull qwen2.5-coder:1.5b
```

Check model availability:

```bash
ollama list
```

You should see `qwen2.5-coder:1.5b` in `ollama list`.

### 6. Run David

```bash
python -m agent.main --goal "Create a Python TODO app with tests"
```

Run without task (diagnostics only):

```bash
python -m agent.main --self-diagnostics
```

Run in interactive mode:

```text
(.venv-linux) charm@CHARMZ:/mnt/d/Tech Agent Labs/David$ python -m agent.main
=== David Interactive Mode ===
Use commands: /goal <task>, /ask <question>, /teach <fact>. Type 'bye' to exit.
you>
```

### 7. Teach David Facts (Explicit Memory Write)

David writes personal facts to long-term memory only when you use `--teach`.
Normal `--goal` runs do not save personal facts.

```bash
python -m agent.main --teach "Hi David I am your dad. My Name is Charm Thiekshana."
```

Expected teaching confirmation includes stored facts such as:

```text
- David.father_name = Charm Thiekshana
```

Ask later using memory-only retrieval:

```bash
python -m agent.main --ask "Who is your father?"
```

## David Control Center (Web UI, Local Only)

The project includes a local web interface in `web/` to monitor and control David safely.
Detailed documentation: `docs/WEB_UI.md`

### Start the web server

From project root (with virtual environment activated):

```bash
python -m web.server --host 127.0.0.1 --port 8787
```

Open in browser:

```text
http://127.0.0.1:8787
```

### Demo Walkthrough (Full Feature Tour)

Use this when onboarding a new user so every major feature is populated and testable immediately.

1. Start the server:

```bash
python -m web.server --host 127.0.0.1 --port 8787
```

2. Open `http://127.0.0.1:8787`.
3. Open `Settings`:
   - enable `Demo mode (fixtures)` and click `Save Settings`, or start with `DEMO_MODE=1` in your environment.
   - click `Load Demo Data` (if prompted, confirm overwrite to replace live data with fixtures).
4. Confirm demo activation:
   - top bar shows `DEMO` badge.
   - Dashboard status shows `Demo mode = true`.
5. Optional fast tour:
   - click `Guided Walkthrough` in the header.
   - follow the overlay steps through Dashboard, Memory & Chat, Approvals, Runs replay/compare, Logs, and Settings.
   - walkthrough pre-fills safe local example prompts for ask/teach gating demos.
6. Click through tabs in this order:
   - `Dashboard`: Growth Timeline milestones, Legacy Archive, Proposed Improvements.
   - `Runs`: open seeded runs (success, failure/regression, awaiting approval).
   - `Approvals`: resolve pending approvals (typed confirmation required for high-risk items).
   - `Diff Viewer`: inspect per-iteration diffs, replay, and compare.
   - `Memory`: verify Facts / Values / Conversations / Lessons / Reflections.
   - `Telemetry`: verify stage/model events and stream states (`connected`, `reconnecting`, `fallback`).
   - `Logs`: confirm seeded info/warn/error mix.
   - `Settings`: verify personality calibration, model roles, and demo controls.
7. In `Memory & Chat`, run this scripted sequence:
   - `Who is your father?`
   - `What did you learn about tests and edge cases?`
   - `Who founded this imaginary company called Zephra Dynamics?` (no memory match path)
   - `Always value patience.` with `Advanced Chat mode` on, `Teach` selected, `Confirm Teach save` off (preview/confirmation required)
   - same message again with `Confirm Teach save` on and `Parent Teaching Mode` on (clarification flow)
   - `Hi David I am your dad. My Name is Bob.` with `Teach` + confirm on (conflict/overwrite-required flow)
   - confirm overwrite when prompted
8. In `Approvals`, approve a typed-confirmation item:
   - submit exactly `approve <run_id>` in confirmation field
   - verify `Run Audit` includes `approval_decision`.
9. In `Diff Viewer`, open:
   - `run_20260211T113000_b2c3d4e5`, compare iteration `2` to confirm “first failing iteration after a passing iteration”.
10. Use `Reset Demo` anytime to restore baseline seeded state.

### Web tabs

- Dashboard: current status, progress, quick run/stop actions, pending approvals.
- Dashboard includes a Growth Timeline with milestone drill-down across sessions/projects (lessons, reflections, run outcomes, memory growth, TDD completions, and iterations-until-green trends).
- Dashboard includes a Legacy Archive panel where conversations, milestones, and teachings can be marked as `Significant Moments` with timestamped summaries.
- Dashboard includes a `Proposed Improvements` panel backed by `workspace/agent_sandbox/`, where David drafts self-improvement proposals with diff previews for explicit user approve/reject decisions.
- Proposed Improvements now includes an autonomous cycle trigger and transparent reasoning metadata (trigger, signals, rationale, and before/after patch view) for each self-initiated proposal.
- Runs: run history, timeline, retry failed runs, explain-failure panel.
- Diff Viewer: per-iteration workspace patch view.
- Memory: facts/lessons + memory conflict detector.
- Telemetry: success/error metrics and iteration-duration chart.
- Logs: tail view of web + telemetry logs.
- Settings: safe mode, rate limit, iteration override, risk thresholds, planner/coder/critic model config, default TDD mode, Companion mode, and autonomous self-improvement mode.
- Memory & Chat: Advanced Chat mode with natural intent detection (`Teach` / `Ask` / `Goal` / `Chat`), confirm-gated memory writes, session history, memory citations, and searchable Facts/Conversations/Lessons/Reflections tabs.
- Memory Insight Mode: every ask/chat answer can expand into a deterministic influence trace showing exactly which Facts, Conversations, and Lessons were used (for example `Fact #12`, `Lesson #7`, `Conversation #3`).
- Companion mode (enabled by default) adds warm memory-first responses for `/ask` and web chat, with transparent AI identity and lesson-aware recall.
- Goal runs are log-aware: David automatically reads recent tail logs and uses them as extra context when planning/coding fixes.
- Reflection Engine: after terminal goal runs and meaningful conversations, David appends timestamped reflection lessons (append-only) and reuses them before future goals.
- Autonomous Self-Improvement Loop: after goal completions and meaningful conversation reflections, David can draft sandboxed self-improvement proposals automatically while keeping core safety modules immutable and human approval required for merges.

### Goal templates

Dashboard and Memory & Chat include beginner-friendly templates:

1. `Build CLI Tool`
2. `Bug Fix Mode`
3. `Refactor Mode`
4. `Strict TDD Mode`

Templates prefill goal text and can set run flags (`Strict TDD Mode` enables `tdd_mode`).
All existing safety checks still apply.

### Advanced Chat in Web UI

Use the `Memory & Chat` tab to interact naturally while keeping memory writes explicit and safe:

1. Type naturally; the UI detects intent and shows a pre-send hint: `I think this is: Teach/Ask/Goal/Chat`.
2. Confirm or override intent with one-click toggles (`Ask`, `Teach`, `Goal`, `Chat`).
3. Teach writes are gated:
   - `Confirm Teach save` must be enabled before a teach message is stored.
   - conflicting teaches require explicit overwrite confirmation.
4. Conversation history is grouped by session, supports pinning, and includes quick-reply chips:
   - `Save this as memory`
   - `Ask a follow-up`
   - `Teach refinement`
5. Memory panel has searchable tabs:
   - `Facts` (with conflict indicators, aliases, provenance metadata),
   - `Conversations`,
   - `Lessons`,
   - `Reflections` (internal learning history, timestamped and preserved).
6. `Explain why David answered this` shows citations for memory facts/conversation snippets and relevant lessons used in the answer.
7. `Memory Insight` expands each answer with a readable reference summary such as `This answer was influenced by Fact #12 (...), Lesson #7 (...), and Conversation #3 (...)`.
8. `Legacy Archive` stores Significant Moments as a reflective learning journal and is intentionally not positioned as a substitute for real-world relationships.
9. Companion behavior safeguards:
   - David stays transparent that he is an AI companion and not a real human child.
   - Family and attachment language is handled with warm + transparent wording.
   - Grief-sensitive language adds calm support and encourages reaching trusted real-world people.
   - Crisis-risk language includes urgent U.S. `988` guidance plus emergency-service direction.

`/ask` and `/teach` CLI mirror behavior remains backward-compatible.

### UX highlights (new)

- Running banner + spinner with loop-stage tracker (`Planner -> Coder -> Safety -> Executor -> Critic -> Memory`).
- Beginner-readable execution panels (collapsible) for `stdout`, `stderr`, return code, and timeout.
- Successful preview experience:
  - clean diff summary,
  - created vs updated files list,
  - click-to-open read-only file preview.
- Success banner with quick actions: open run details, download run bundle, view changed files.
- Dashboard activity feed with recent run events and approvals.
- Logs tab filtering/search for `info` / `warn` / `error`.
- Real-time Server-Sent Events (SSE) streaming with polling fallback and connection-state indicator.
- Approvals tab with high-risk typed confirmation and per-run audit log.
- Run Replay mode (`Prev/Next`) and iteration comparison view.
- Guided Walkthrough overlay with tab-by-tab highlights and safe prefilled demo prompts.
- Header version stamp (`app_version + git commit` when available).
- Portable run bundles:
  - `Export Bundle` from run rows/success banner.
  - `Import Bundle` into read-only viewer mode (no live-state mutation).
- Run Health Summary card per run: iterations, time-to-green, approvals, models used, top error category, memory references.
- Failure explainer with category, top error lines, related files, and copyable VS Code open commands.

### AI Cinematic Theme

- The web UI ships with a cinematic dark mode by default (`html[data-theme="dark"]`):
  - matte black background,
  - metallic typography accents,
  - electric-blue active states and stream indicators.
- Hero and dashboard header use a local background image:
  - `web/static/assets/ai-bg.jpg`
  - You can replace this file with your preferred local cinematic image (same path/filename).
- Use `Settings -> Appearance` to control:
  - `Dark` / `Light` theme,
  - `Cinematic Background On` toggle,
  - `Reset Appearance` (restores defaults: dark + background enabled).
- Preferences are saved to localStorage:
  - `dcc_theme = "dark" | "light"`
  - `dcc_bg_disabled = "1"` when cinematic background is disabled (unset means enabled).
- Reduced-motion users are respected via `prefers-reduced-motion`:
  - shimmer/particles/pulsing/glow-heavy animations are disabled automatically.

### API endpoints

- `GET /api/status`
- `POST /api/run`
- `POST /api/ask`
- `POST /api/teach`
- `POST /api/chat`
- `POST /api/stop`
- `GET /api/runs`
- `GET /api/run/<run_id>`
- `GET /api/run/<run_id>/timeline`
- `GET /api/run/<run_id>/files`
- `GET /api/run/<run_id>/audit`
- `GET /api/run/<run_id>/replay`
- `GET /api/run/<run_id>/compare`
- `POST /api/run/<run_id>/retry`
- `GET /api/run/<run_id>/bundle`
- `POST /api/bundles/import`
- `GET /api/bundles/imports`
- `GET /api/bundles/import/<import_id>`
- `GET /api/bundles/import/<import_id>/timeline`
- `GET /api/bundles/import/<import_id>/files`
- `GET /api/bundles/import/<import_id>/audit`
- `GET /api/bundles/import/<import_id>/replay`
- `GET /api/bundles/import/<import_id>/compare`
- `GET /api/memory`
- `GET /api/memory/facts`
- `GET /api/memory/conversations`
- `POST /api/memory/confirm_overwrite`
- `GET /api/chat/sessions`
- `GET /api/telemetry/tail`
- `GET /api/logs/tail`
- `GET /api/settings`
- `POST /api/settings`
- `POST /api/demo/load`
- `POST /api/demo/reset`
- `GET /api/legacy_archive`
- `POST /api/legacy_archive`
- `POST /api/legacy_archive/<entry_id>/remove`
- `GET /api/self_improvements`
- `POST /api/self_improvements/propose`
- `POST /api/self_improvements/autonomous_cycle`
- `POST /api/self_improvements/<proposal_id>/decision`
- `GET /api/models`
- `GET /api/approvals`
- `POST /api/approval/<approval_id>`
- `GET /api/stream/status`
- `GET /api/stream/logs`
- `GET /api/stream/run/<run_id>`

### Safety behavior in web mode

- Local-only by default (`127.0.0.1` bind).
- State-changing endpoints protected with CSRF token checks.
- Request body size limit enforced server-side.
- Server-side state-change throttling to reduce abuse/spam loops.
- No arbitrary shell endpoint; only `/goal`, `/ask`, `/teach`.
- File writes remain restricted to active project directories under `workspace/projects/`.
- Risk approval gate for large edits and multi-file rewrites.
- Memory conflict approval gate for conflicting `--teach` facts.
- Advanced Chat teach save gate (`confirm_save`) and explicit overwrite confirmation for conflicting facts.
- Companion mode is deterministic memory-first behavior in web ask/chat and can be toggled in Settings.
- Memory Insight Mode is deterministic and reference-based; it does not fabricate memory references and can be toggled in Settings.
- Legacy Archive is framed as reflective continuity and explicitly maintains real-world relationship boundaries.
- Self-improvement proposals are sandbox-first (`workspace/agent_sandbox/`) and can only merge to core code after explicit human approval.
- Self-improvement merge flow blocks direct edits to safety logic files (`agent/safety.py`, `web/safety.py`).
- Grief/calm support overlays never replace human support; crisis-risk responses include U.S. `988` guidance.
- Safe mode can block write operations (read-only monitoring mode).
- Run artifacts are stored under `data/runs/<run_id>/` (plan, iteration outputs, diffs, result bundle).
- Imported bundle viewer is permanently read-only and isolated from live workspace state.

## Release Checklist

Before shipping a release build:

1. Run full tests:
   - `pytest -q`
2. Validate local web startup:
   - `python -m web.server --host 127.0.0.1 --port 8787`
3. Verify header version stamp shows expected `VERSION` and git short commit.
4. Enable demo mode and run the Guided Walkthrough end-to-end.
5. Execute the scripted Demo Walkthrough chat sequence and confirm:
   - intent chips,
   - teach confirmation gating,
   - citations + memory insight rendering,
   - typed approval flow,
   - replay/compare controls.
6. Export a run bundle, import it, and verify read-only viewer endpoints:
   - timeline,
   - files,
   - audit,
   - replay/compare.
7. Confirm imported bundle viewing does not mutate live runs/memory/workspace state.
8. Review logs/telemetry for clean startup and no unhandled errors.

### Preview mode quick usage

1. In Dashboard, enable `Run preview`.
2. Start a `/goal` run.
3. Use `Preview & Changed Files` and `Diff Viewer` to inspect proposed changes.
4. Start again with preview disabled to apply changes after review.

### Streaming + Replay quick usage

1. Open the UI and check `stream: connected` in the header.
2. Start a run and watch live stage/status/timeline updates.
3. In `Runs`, choose a run and use `Prev iteration` / `Next iteration` to replay steps.
4. Use `Compare Iterations` to inspect change deltas and likely failure-causing edits.

## How David Learns

- Each iteration can add reusable lessons to `memory/long_term.json`.
- Future goals load relevant lessons to avoid repeating mistakes.
- Telemetry logs each major step for debugging and auditability.
- Personal facts are stored only through the explicit `--teach` pathway.
- Conversation turns and extracted takeaways are persisted in `memory/conversations.jsonl` (session-aware metadata: timestamp, session_id, intent, topics, confidence).

## Tests

Run:

```bash
pytest -q
```

Current tests validate safety boundaries, executor timeout behavior, and teach/ask memory flow.

Web API and safety tests:

```bash
pytest -q tests/test_web_api.py tests/test_web_memory_api.py tests/test_web_safety.py
```

Per-role model + TDD + template tests:

```bash
pytest -q tests/test_config_models.py tests/test_control_center_modes.py
```

Workspace isolation and project layout tests:

```bash
pytest -q tests/test_projects_layout.py tests/test_loop_projects.py
```

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
