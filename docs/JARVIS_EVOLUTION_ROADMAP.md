# David — JARVIS Evolution Roadmap

Last updated: 2026-05-13

## Vision

David is inspired by J.A.R.V.I.S from Iron Man — a fully personal, local, privacy-preserving AI that:

- Runs entirely on your own hardware (Ollama, no cloud AI APIs)
- Lets you choose your own models per role
- Has a controlled built-in browser as the **only** internet channel
- Remembers everything across sessions (facts, lessons, conversations, research)
- Can talk and listen via local voice (no cloud audio)
- Improves its own code over time with your approval
- Acts proactively — not just when asked

## Non-Negotiable Constraints (Never Break These)

- `agent/safety.py` and `web/safety.py` are permanently immutable to autonomous edits.
- All AI inference stays on localhost Ollama — no external AI API calls, ever.
- All internet access is routed through the controlled browser channel only — no raw socket calls from agent code.
- Every self-improvement proposal requires explicit human approval before merge.
- All file writes stay inside `workspace/projects/<slug>/` during goal runs.

---

## Priority Order

| # | Capability | Why First |
|---|---|---|
| 1 | Self-Evolution (version-based upgrades) | The defining JARVIS trait — David grows over time |
| 2 | Controlled Browser (sandboxed internet) | Makes David useful for real research |
| 3 | Persistent Skill Library | Compounds every past success into future speed |
| 4 | Scheduled & Proactive Goals | David acts without being prompted |
| 5 | Hardware Intelligence | Makes model selection practical and automatic |
| 6 | Wake Word + Voice-First Interaction | The JARVIS day-to-day feel |
| 7 | Multi-Agent Parallelism | Faster complex goals |
| 8 | Security Audit Mode | Keeps the privacy promise verifiable |

---

## Phase 1 — Self-Evolution (Version-Based Code Upgrades)

**Goal:** David analyzes his own performance, proposes improvements to his own code, tests them, and presents them for your approval. He never edits safety modules.

### What David can evolve
- `agent/prompts.py` — better prompt templates based on observed failures
- `agent/critic.py` — sharper success/failure detection logic
- `agent/planner.py` — more structured planning for complex goals
- `agent/memory.py` — better lesson deduplication and retrieval
- `agent/plan_quality.py` — tighter scoring rubrics

### What is permanently locked from self-edits
- `agent/safety.py`
- `agent/executor.py`
- `agent/config.py`
- `web/safety.py`
- Any file under `tests/`

### Step-by-Step Build Guide

**Step 1 — VERSION file and changelog**
- Create `VERSION` file at project root containing a semver string (e.g. `0.1.0`).
- Create `docs/SELF_IMPROVEMENT_LOG.md` — append-only changelog David writes to when a self-upgrade is approved and applied.

**Step 2 — Performance analyzer (`agent/self_improvement/analyzer.py`)**
- Reads `logs/metrics.json` and `logs/telemetry.jsonl`.
- Computes per-module weakness signals:
  - High retry rate → planner or coder prompt quality issue
  - Frequent safety violations → coder needs tighter constraint awareness
  - Low plan quality scores → planner needs richer success criteria
- Outputs a structured `WeaknessReport` JSON: which module, what signal, severity score.

**Step 3 — Proposal generator (`agent/self_improvement/proposer.py`)**
- Takes a `WeaknessReport` and the current content of the target module.
- Sends it to the critic model with a prompt: "Given this weakness signal and the current code, propose a minimal targeted improvement."
- Output is a unified diff (patch format) against the target file.
- Validates the patch does not touch locked files — hard reject if it does.

**Step 4 — Staging and test runner (`agent/self_improvement/stager.py`)**
- Applies the patch to a temporary copy of the file (never in-place directly).
- Runs `pytest -q` against the patched copy using the restricted executor.
- If tests pass: promotes the proposal to `workspace/agent_sandbox/proposals/<timestamp>/`.
- If tests fail: discards the patch, logs the failure, no proposal created.

**Step 5 — Web UI approval flow**
- The existing `Proposed Improvements` panel in the Dashboard already exists.
- Extend it to show: trigger signal, affected file, before/after diff, test result summary.
- Approval writes the patch to the real file, bumps `VERSION` (patch version), appends to `SELF_IMPROVEMENT_LOG.md`, and git-commits the change.
- Rejection logs the decision so David learns not to propose similar changes again.

**Step 6 — Automatic trigger after goal runs**
- After every 5 successful goal runs, David automatically runs the analyzer.
- If weakness score exceeds threshold, it auto-generates a proposal (but never auto-applies — always waits for approval).
- Can also be triggered manually: `python -m agent.main --propose-improvement`.

---

## Phase 2 — Controlled Browser (Sandboxed Internet)

**Goal:** David can browse the internet for research through a single controlled channel. All access is logged. You can allow/block domains. No raw HTTP calls from agent code.

### Architecture principle
```
David agent code → BrowserTool API → Local Playwright browser → Internet
                                   ↓
                              Audit log (every URL, every page read)
```
Agent code never calls `requests`, `urllib`, or any socket directly for internet access.

### Step-by-Step Build Guide

**Step 1 — Install Playwright locally**
```powershell
pip install playwright
playwright install chromium
```
Add `playwright` to `requirements.txt`.

**Step 2 — Browser tool module (`agent/browser_tool.py`)**
- `BrowserTool` class wrapping a Playwright browser instance.
- Two methods David can call:
  - `search(query: str) -> list[SearchResult]` — uses a search engine, returns title + URL + snippet
  - `read_page(url: str) -> PageContent` — fetches and extracts readable text from a URL
- Both methods:
  - Check URL against a domain allow/block list before fetching
  - Append every request to `logs/browser_audit.jsonl` (timestamp, URL, status, content length)
  - Strip all JavaScript execution results — read HTML content only
  - Cap page content at configurable `BROWSER_MAX_PAGE_CHARS` (default 20,000)

**Step 3 — Domain allow/block list**
- Config file: `config/browser_policy.json` — lists allowed domains and blocked domains.
- Default: everything allowed except a hardcoded blocklist (known malware/phishing domains).
- Web UI Settings tab gets a `Browser Policy` section to manage this list.
- David cannot modify `browser_policy.json` autonomously — it is outside `workspace/projects/`.

**Step 4 — Memory integration**
- After `read_page()`, extracted content is summarized by the critic model and stored in memory:
  ```json
  { "source": "web_research", "url": "...", "summary": "...", "timestamp": "..." }
  ```
- Future goals load relevant web research summaries alongside lessons and facts.

**Step 5 — Planner integration**
- Add a `research_phase` step type to the planner contract.
- If a goal requires unknown information, the planner can include research steps before coding steps.
- Coder receives research summaries as additional context.

**Step 6 — Web UI audit panel**
- New `Browser` tab in the Web UI showing a live log of URLs David has visited.
- Per-entry: timestamp, URL, status, how many characters of content were used.
- `Block domain` button per entry.

---

## Phase 3 — Persistent Skill Library

**Goal:** After completing a goal type successfully, David extracts a reusable skill (template + pattern) so future similar goals start faster and with higher quality.

### Step-by-Step Build Guide

**Step 1 — Skill extractor (`agent/skills.py`)**
- After a successful run, the critic model is asked: "What is the reusable pattern from this goal? Output a skill name, description, file templates, and required commands."
- Output is saved to `workspace/templates/<skill_name>/`:
  - `skill.json` — name, description, tags, success rate, times used
  - `src/` — template source files with placeholder tokens
  - `tests/` — template test files

**Step 2 — Skill matcher**
- At the start of each new goal, scan `workspace/templates/` for skills whose tags match the goal.
- If a match is found, offer it to the planner as a starting context: "A similar goal succeeded using skill X — here is its structure."
- Planner can choose to use it, adapt it, or ignore it.

**Step 3 — Skill versioning**
- Each time a skill is used successfully, its `success_rate` and `times_used` counters update.
- Skills with 0% success rate over 3 uses are automatically flagged for review.
- You can view, edit, and delete skills from the Web UI `Skills` tab.

**Step 4 — Web UI Skills tab**
- Lists all skills with name, description, success rate, last used date.
- Click to view template files.
- `Delete` and `Edit description` actions.

---

## Phase 4 — Scheduled & Proactive Goals

**Goal:** David runs tasks on a schedule and reports proactively, without waiting for you to ask.

### Step-by-Step Build Guide

**Step 1 — Task queue (`agent/scheduler.py`)**
- Simple JSON-backed queue: `data/task_queue.json`.
- Each entry: `{ "goal": "...", "schedule": "daily@09:00", "last_run": "...", "enabled": true }`.
- A background scheduler thread checks the queue every minute and fires due tasks.

**Step 2 — Built-in scheduled tasks (enabled by default)**
- `nightly_health_check` — runs `pytest -q` across all past successful projects at 2am, reports regressions.
- `dependency_watcher` — checks `requirements.txt` files in all projects for available updates (via browser tool, not pip index directly).
- `morning_briefing` — at 9am, compiles: runs since yesterday, memory growth, pending proposals, any regressions.

**Step 3 — CLI scheduling**
```powershell
python -m agent.main --schedule "every day at 9am: summarize new Python security advisories"
python -m agent.main --schedule "every monday: run tests on all active projects"
```

**Step 4 — Web UI Scheduler tab**
- Lists all scheduled tasks with next-run time, last-run status, enable/disable toggle.
- `Run now` button for any task.
- `Add task` form.

---

## Phase 5 — Hardware Intelligence

**Goal:** David knows what GPU/CPU/RAM you have and uses that knowledge to recommend and auto-select models.

### Step-by-Step Build Guide

**Step 1 — Hardware profiler (`agent/hardware.py`)**
- On startup, collect:
  - GPU VRAM (via `nvidia-smi` or `rocm-smi` if available, else detect via Ollama)
  - CPU core count and RAM via Python `psutil`
  - Disk free space in workspace
- Cache result in `data/hardware_profile.json` (refresh daily).

**Step 2 — Model size database**
- `data/model_sizes.json` — maps known Ollama model names to approximate VRAM requirements.
- David updates this from browser research periodically (optional).

**Step 3 — Auto model selection**
- If `DAVID_MODEL=auto` in `.env`, David queries hardware profile + model size database and picks the largest model that fits in available VRAM.
- Logs the selection reason to telemetry.

**Step 4 — Pre-run warnings**
- Before starting a goal run, David checks:
  - Is disk space > 500MB? Warn if not.
  - Is VRAM sufficient for selected models? Warn if borderline.
  - Is Ollama responding? If not, print a clear error with fix instructions.

---

## Phase 6 — Wake Word + Voice-First Interaction

**Goal:** Say "Hey David" and he starts listening. Dictate goals naturally. He confirms and narrates progress.

### Step-by-Step Build Guide

**Step 1 — Local wake word detection**
- Install `openwakeword` (fully local, no cloud):
  ```powershell
  pip install openwakeword
  ```
- Background listener process monitors microphone for the wake phrase "Hey David".
- On detection: plays a short audio acknowledgment chime, opens voice input mode.

**Step 2 — Natural language goal dictation**
- After wake word, David records until silence (using existing VAD).
- Transcribes via Whisper (existing STT pipeline).
- Sends transcript through intent detection: is this a Goal, Ask, Teach, or Chat?

**Step 3 — Voice confirmation before goal runs**
- For Goal intent, David speaks confirmation before running:
  *"I'll create a renaming script for JPEG files using EXIF date metadata. Should I proceed?"*
- User says "yes" / "go ahead" / "cancel".
- Goal run never starts without spoken or typed confirmation.

**Step 4 — Progress narration**
- David narrates each loop stage transition via TTS:
  - *"Planning complete. Starting iteration one."*
  - *"Tests passed. Committing changes."*
  - *"Iteration three failed. Retrying with adjusted approach."*
- Narration can be muted from Settings without disabling voice input.

**Step 5 — Wake word config**
- `DAVID_WAKE_WORD=hey david` in `.env` (customizable).
- `DAVID_VOICE_FIRST=true` enables the background listener on server start.
- Wake word sensitivity tunable in Settings.

---

## Phase 7 — Multi-Agent Parallelism

**Goal:** For large complex goals, David spawns sub-agents that work on independent sub-tasks simultaneously.

### Step-by-Step Build Guide

**Step 1 — Goal decomposer**
- Planner gets a new output field: `parallel_subtasks: list[str]` — independent sub-goals that can run concurrently.
- Planner only uses this for goals where the steps have no shared file dependencies.

**Step 2 — Sub-agent runner (`agent/parallel_runner.py`)**
- Spawns one `DavidAgent` instance per sub-task in a separate thread.
- Each sub-agent writes to its own sub-folder: `workspace/projects/<slug>/subtask_<n>/`.
- Collects all `RunSummary` results and feeds them to a Coordinator review step.

**Step 3 — Coordinator role**
- After all sub-agents complete, Coordinator (critic model) merges results:
  - Checks for conflicts between sub-agent outputs
  - Produces a unified summary
  - Determines overall success/failure

**Step 4 — Web UI parallel lanes**
- Runs tab shows parallel sub-tasks as separate lanes under the parent run.
- Each lane has its own timeline, status, and iteration replay.

---

## Phase 8 — Security Audit Mode

**Goal:** David periodically verifies that he is living up to the privacy and security promises.

### Step-by-Step Build Guide

**Step 1 — Self-audit runner (`agent/security_audit.py`)**
Runs the following checks:
- **Secret scan**: grep `logs/`, `data/`, and `workspace/` for patterns matching API keys, passwords, tokens, SSH keys. Alerts if found.
- **Network audit**: verify `logs/browser_audit.jsonl` — confirm all outbound URLs went through the browser tool and none are unexpected.
- **Workspace boundary audit**: scan all files written in the last 24h and confirm every path is inside `workspace/projects/`.
- **Config integrity**: verify `safety.py` and `executor.py` have not been modified (compare against git hash).
- **Ollama URL audit**: confirm `DAVID_OLLAMA_URL` still points to localhost.

**Step 2 — Audit schedule**
- Runs automatically once per week (wired into the Phase 4 scheduler).
- Can be triggered manually: `python -m agent.main --security-audit`.

**Step 3 — Audit report**
- Output: `data/security_audit_<date>.json` with pass/fail per check and details.
- Web UI Dashboard shows a `Security Posture` card: last audit date, pass/fail summary, link to full report.
- Any failed check triggers a prominent warning banner in the Web UI.

**Step 4 — Immutability check**
- On every server startup, verify SHA256 hashes of `agent/safety.py`, `agent/executor.py`, `web/safety.py` against a stored baseline in `data/safety_hashes.json`.
- If any hash mismatches: refuse to start and print a clear error message.

---

## File Layout After All Phases Complete

```
agent/
  git_committer.py          ← Phase 0 (done)
  browser_tool.py           ← Phase 2
  hardware.py               ← Phase 5
  parallel_runner.py        ← Phase 7
  scheduler.py              ← Phase 4
  security_audit.py         ← Phase 8
  skills.py                 ← Phase 3
  self_improvement/
    analyzer.py             ← Phase 1
    proposer.py             ← Phase 1
    stager.py               ← Phase 1
    autonomous_playbook.py  ← existing

config/
  browser_policy.json       ← Phase 2

data/
  hardware_profile.json     ← Phase 5
  model_sizes.json          ← Phase 5
  safety_hashes.json        ← Phase 8
  security_audit_<date>.json ← Phase 8
  task_queue.json           ← Phase 4

docs/
  JARVIS_EVOLUTION_ROADMAP.md   ← this file
  SELF_IMPROVEMENT_LOG.md       ← Phase 1

logs/
  browser_audit.jsonl       ← Phase 2

workspace/
  templates/<skill_name>/   ← Phase 3

VERSION                     ← Phase 1
```

---

## How to Track Progress

Each phase has a natural completion milestone:

| Phase | Done When |
|---|---|
| 1 | David proposes and you approve his first self-upgrade |
| 2 | David successfully reads a web page during a goal run and cites it in memory |
| 3 | David reuses a saved skill for a new similar goal |
| 4 | David runs the nightly health check without being prompted |
| 5 | David selects a model automatically based on detected VRAM |
| 6 | You say "Hey David" and he starts listening |
| 7 | A complex goal completes via two parallel sub-agents |
| 8 | First weekly security audit passes all checks |
