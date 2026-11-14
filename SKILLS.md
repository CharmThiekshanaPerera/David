# SKILLS.md — What David Can Do Today, and What's Next

Last updated: 2026-11-14

This is a capability inventory: what's actually implemented and usable right now,
versus what's on the roadmap. See `docs/AGENTIC_WORKFLOW_ROADMAP.md` for the
agentic-loop roadmap and the JARVIS vision memory for the longer-range product
direction.

## Implemented skills

### Autonomous coding (core)
- `python -m agent.main --goal "<goal>"` — runs the full Planner -> Coder -> Safety
  -> Executor -> Critic -> Memory loop against an isolated project directory under
  `workspace/projects/<slug>/`.
- `--max-iterations N` — override the iteration cap for one run.
- `--self-diagnostics` — checks config, paths, and memory file integrity without
  running a goal.
- `--chat` — interactive REPL (`/goal`, `/ask`, `/teach`, `bye`) over the same loop.
- TDD mode (`TDD_MODE=true`) — Planner is instructed to write failing tests first; the
  loop tracks red/green phase and only accepts success after a green run following a
  captured red run.

### Explicit memory
- `--teach "<message>"` — extracts structured `(subject, predicate, object)` facts
  and stores them in `memory/long_term.json`. Never happens implicitly during a
  `--goal` run.
- `--ask "<question>"` — answers strictly from stored facts; refuses to use outside
  model knowledge (`FACT_QA_PROMPT`).
- Reflection lessons are written automatically after every iteration/run and reused
  as context in future runs (see AGENTS.md's Memory section for the feedback-loop
  caveat).

### Controlled web browsing
- `agent/browser_tool.py` (`BrowserTool`, `BrowserPolicy`) — domain allow/deny policy
  enforced from `config/browser_policy.json`, with an audit log of every fetch.
- `agent/web_search.py` — search + fetch, with answers constrained to retrieved page
  content only (no outside model knowledge leakage).
- Deep Search mode — multi-page synthesis into a structured markdown report
  (`DEEP_SEARCH_PROMPT`).
- All internet access funnels through this one controlled path — nothing else in the
  codebase makes outbound HTTP calls to arbitrary hosts.

### Web Control Center (`web/`)
- Flask app (`web/server.py`, default `http://127.0.0.1:8787`) — dashboard, run
  controls, timeline/replay/compare for past runs, approvals queue, bundle
  import/export, memory/chat UI, uploads.
- Streaming status via SSE with a polling fallback.
- Per-role model override at runtime (`planner_model` / `coder_model` /
  `critic_model` in `data/control_settings.json`) — **this takes priority over
  `.env`**; if you change `DAVID_MODEL` and nothing changes, check this file too.
- Approval policies (`strict`/`balanced`/`fast`) gate risky/large edits.
- Demo mode for showing the UI without live runs.

### Vision (upload analysis)
- `web/vision_service.py` + `web/upload_analysis.py` — optional local vision model
  enrichment of uploaded images/files (`upload_vision_mode`, `upload_vision_model` in
  `data/control_settings.json`).

### Voice (local, offline)
- `web/voice_service.py` — STT via Whisper CLI, whisper.cpp CLI, or the Whisper
  Python API (`voice_stt_engine`); TTS via browser speech synthesis or Piper
  (`voice_tts_engine`).
- Manual, continuous, and VAD-gated (voice-activity-detection) input modes; configurable
  stop phrases, chunking, and speech rate — all in `data/control_settings.json`.

### Self-improvement playbook
- `agent/self_improvement/autonomous_playbook.py` — a separate autonomous loop,
  surfaced in the Control Center behind `autonomous_self_improvement_mode`, with its
  own persisted state (`agent/self_improvement/autonomous_state.json`).

## Known gaps (fixed or mitigated 2026-09-15, still worth knowing)
- Small local models (`qwen2.5-coder:1.5b`) are workable as Coder but unreliable as
  Critic for self-review — see AGENTS.md. Pull a larger model for `CRITIC_MODEL` if
  this keeps biting you.
- Dependencies install into one shared venv, not a per-generated-project one — a
  goal's `pip install` can affect the rest of the app.

## Roadmap (not yet built here)

From the JARVIS-inspired long-range vision (local, privacy-preserving, JARVIS-like
assistant) and `docs/AGENTIC_WORKFLOW_ROADMAP.md`:

1. **Self-evolution hardening** (current focus) — plan-quality scoring, diff-based
   edits, rollback-safe staging, stronger TDD red/green enforcement.
2. **Browser** — implemented (see above); next: richer multi-step browsing tasks.
3. **Skills framework** — a formal, pluggable skill registry for David (this file is
   the informal precursor).
4. **Scheduler** — recurring/autonomous task execution without a human kicking off
   each goal.
5. **Hardware integration** — device/sensor hooks.
6. **Voice-first interaction** — voice is implemented as an input/output mode today;
   voice-first means making it the primary interface, not an add-on to the web UI.
7. **Multi-agent collaboration** — coordinating more than one David instance/role
   concurrently (today's loop is strictly sequential, one role at a time).
8. **Security audit** — formal review pass over the safety guard, command allow-list,
   and workspace isolation before trusting David with more autonomy.
