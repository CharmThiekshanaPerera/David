# AGENTS.md — David's Internal Agent Roles

Last updated: 2026-11-14

David is not one model call — it's a fixed loop of specialized roles, each with its
own system prompt (`agent/prompts.py`) and, optionally, its own local Ollama model.
This file documents those roles, how they're wired together, and known reliability
limits discovered while running David end-to-end.

## The Loop

```
Planner -> Coder -> Safety Guard -> Executor -> Critic -> Memory
```

Implemented in `agent/loop.py` (`DavidAgent.run`). One pass through Coder -> Safety
-> Executor -> Critic is one "iteration"; the loop repeats until the Critic reports
`success`, chooses `abort`, or `max_iterations` is reached (default 8, env
`DAVID_MAX_ITERATIONS`, overridable with `--max-iterations`).

## Roles

### 1. Planner (`agent/planner.py`, `PLANNER_SYSTEM_PROMPT`)
- Input: goal text, memory context (reusable lessons), workspace/project context.
- Output: a JSON plan — 3 to 7 ordered steps plus objective success criteria.
- Runs once per goal (or once per re-plan if plan-quality scoring rejects the first
  attempt — see `agent/plan_quality.py`).
- Model: `PLANNER_MODEL` env var, falling back to `DAVID_MODEL`.

### 2. Coder (`agent/coder.py`, `CODER_SYSTEM_PROMPT`)
- Input: goal, plan, current iteration, critic feedback from the previous iteration.
- Output: JSON with `edits` (full file contents, path-relative-to-project), `commands`
  (must start with `python` or `pytest`), and `done`/`done_reason`.
- Runs once per iteration.
- Model: `CODER_MODEL` env var, falling back to `DAVID_MODEL`.
- **Fallback behavior**: if the model's response isn't valid JSON, `agent/coder.py`
  returns an empty-edits, empty-commands `CoderOutput` rather than guessing a command
  (fixed 2026-09-15 — it used to default to `pytest -q`, which produced a confusing
  "no tests collected" result and fed the Critic's hallucination problem below).

### 3. Safety Guard (`agent/safety.py`, `SafetyGuard`)
- Validates every proposed edit path and every proposed command before anything runs.
- Rules (non-negotiable, see `docs/AGENTIC_WORKFLOW_ROADMAP.md`):
  - All edits must resolve inside the active project's root
    (`workspace/projects/<slug>/`) — no `..`, no absolute paths, no drive paths.
  - Per-file and per-run byte limits (`DAVID_MAX_FILE_WRITE_BYTES`,
    `DAVID_MAX_TOTAL_WRITE_BYTES`).
  - Commands must start with an allowed prefix (`DAVID_ALLOWED_COMMANDS`, default
    `python,pytest`).
  - `agent/safety.py` and `web/safety.py` themselves are meant to never be edited
    autonomously by David.

### 4. Executor (`agent/executor.py`, `RestrictedExecutor`)
- Runs only safety-validated commands, synchronously, with `shell=False`, inside the
  active project directory, with a trimmed environment (`PATH`, `SYSTEMROOT`,
  `WINDIR`, `VIRTUAL_ENV`, `PYTHONPATH` only) and a hard timeout
  (`DAVID_COMMAND_TIMEOUT_SEC`, default 45s).
- **Known limitation — blocking commands always "fail"**: a command that never exits
  on its own (`app.run()`, `flask run`, any dev server) will always hit the timeout
  and always be scored as a failure, regardless of whether the code is correct. The
  Coder prompt now explicitly forbids proposing such commands for verification and
  requires a pytest test using the framework's in-process test client instead (fixed
  2026-09-15).
- **Known limitation — shared venv**: there is one Python environment for the whole
  project (`.venv-win`), not one per generated project. A coder-proposed
  `pip install package==X` runs against that same shared venv, so it can downgrade or
  remove a package the main app (web UI, other tools) depends on. The Coder prompt
  now tells the model to check importability before installing and avoid pinning a
  version that differs from what's already satisfied — but this is a prompt-level
  mitigation, not a hard guarantee. If you see the web UI or CLI suddenly broken after
  a goal run, suspect a dependency the agent changed and `pip install -r
  requirements.txt` (or reinstall the specific package) to recover.

### 5. Critic (`agent/critic.py`, `CRITIC_SYSTEM_PROMPT`)
- Input: goal, plan, the Coder's JSON (including full edit content), and the raw
  execution results (stdout/stderr/returncode/timed_out) for every command that ran.
- Output: `status` (`success|retry|abort`), `analysis`, `next_actions`, and portable
  `lessons` that get written to long-term memory.
- Model: `CRITIC_MODEL` env var, falling back to `DAVID_MODEL`.
- If the Critic's own JSON fails to parse, `Critic._fallback_review` makes a
  deterministic success/retry call purely from `returncode`/`timed_out`, bypassing
  model judgment entirely.
- **Known limitation — false-negative hallucination**: with a small local model
  (`qwen2.5-coder:1.5b`), the Critic has been observed claiming a defect ("doesn't
  import Flask") that's directly contradicted by the edit content it was given in the
  same prompt. The prompt now requires the Critic to ground any claimed defect in the
  literal provided evidence and to recognize a timed-out server-like command as a
  command-choice problem rather than invent an unrelated code defect (added
  2026-09-15). This reduces but does not eliminate the problem — it is a capability
  ceiling of a 1.5B-parameter model doing self-review, not something prompt wording
  alone fully solves. If goals keep failing on plausible-sounding but factually wrong
  Critic analysis, the fix is a larger/more capable `CRITIC_MODEL`, not another prompt
  tweak.

### 6. Memory (`agent/memory.py`, `LongTermMemory`)
- Stores `facts` (only via explicit `--teach`), `lessons` (from Critic output after
  every iteration), and `preferences`.
- Lessons are re-injected as context into future Planner/Coder/Critic prompts
  (`memory_context_injected` telemetry event). This means a bad/hallucinated lesson
  from one run can bias later runs — if the Critic keeps repeating a wrong
  explanation across unrelated goals, check `memory/long_term.json` for a stale
  lesson worth pruning.

## Separate, non-loop agent paths

- **Teach/Ask** (`agent/qa.py`, `MemoryTeacherQA`) — `--teach` extracts explicit facts
  via `TEACH_EXTRACTOR_PROMPT`; `--ask` answers strictly from stored facts via
  `FACT_QA_PROMPT` (refuses to use outside model knowledge).
- **Web search / Deep search** (`agent/web_search.py`, `WEB_QA_PROMPT`,
  `DEEP_SEARCH_PROMPT`) — used by the controlled browser tool, answers constrained to
  fetched page content only.
- **Self-improvement playbook** (`agent/self_improvement/autonomous_playbook.py`) —
  a separate autonomous loop surfaced in the web Control Center
  (`autonomous_self_improvement_mode`); state persisted in
  `agent/self_improvement/autonomous_state.json`.

## Debugging a run

Raw stdout/stderr from executed commands are **not** persisted to `logs/telemetry.jsonl`
(only lengths are, in a debug log line in `loop.py`). If you need to know exactly what
a command printed, reproduce it by hand in the project directory:

```powershell
cd workspace/projects/<slug>
.venv-win\Scripts\python.exe <same command the coder proposed>
```

`logs/telemetry.jsonl` is append-only JSON-lines; filter by date and `event_type`
(`run_started`, `plan_created`, `plan_quality_scored`, `coder_output`,
`iteration_complete`, `run_complete`) to reconstruct what happened.
