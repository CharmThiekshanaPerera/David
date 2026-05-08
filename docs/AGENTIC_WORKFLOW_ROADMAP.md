# Agentic Workflow Roadmap

Last updated: 2026-02-22

## Purpose

Define a practical roadmap for evolving David's end-to-end agentic workflow while preserving strict safety boundaries and human oversight.

## Non-Negotiable Guardrails

- Keep all autonomous file writes inside `workspace/projects/<project_slug>/`.
- Keep command execution restricted to approved prefixes (`python`, `pytest`) unless explicitly expanded by policy.
- Keep path traversal and absolute-path write protections enforced.
- Keep `agent/safety.py` and `web/safety.py` protected from autonomous edits.
- Keep high-impact actions gated by explicit user confirmation.

## Current Baseline

- Structured loop is implemented: planner -> coder -> safety guard -> executor -> critic -> memory.
- Project isolation is implemented under `workspace/projects/`.
- Run artifacts, timeline, replay, compare, and bundle export/import are implemented in the web control center.
- Imported bundle viewing is read-only and separated from live workspace state.
- Teach/ask factual memory path is separated from normal goal runs.
- Telemetry and metrics are persisted for debugging and trend analysis.

## Canonical Agentic Workflow (Target Shape)

1. Goal intake and scope normalization.
2. Project selection/creation and context loading.
3. Plan synthesis with measurable success criteria.
4. Risk-aware edit proposal with test strategy.
5. Safety validation of proposed writes and commands.
6. Controlled execution (`python`/`pytest`) with timeout guards.
7. Critique and root-cause analysis for failures.
8. Iterative retry loop until success or hard stop.
9. Run artifact packaging (plan, diffs, execution, audit, memory snapshot).
10. Human review path (preview, approvals, replay, compare).
11. Reflection-to-memory indexing for future runs.

## Milestones

### M1: Reliability and Determinism (Target: March 2026)

- Add stronger preflight checks before first execution.
- Add deterministic test ordering and stable run metadata stamping.
- Expand regression tests for bundle import/export and read-only viewer invariants.
- Add policy tests for ambiguous goal handling and project target resolution.
- Exit criteria:
  - No unhandled exceptions across full test suite.
  - Imported bundle viewer APIs consistently return read-only workspace identity.
  - Run failure modes produce actionable critic output and audit traces.

### M2: Planning and Edit Quality (Target: April 2026)

- Introduce plan-quality scoring (clarity, testability, risk coverage).
- Add diff-based editing as primary write mode.
- Add rollback-safe staging for multi-file edits.
- Enforce optional TDD-first mode with explicit red-green checkpoints.
- Exit criteria:
  - Lower average iterations-until-green on repeated goal categories.
  - Higher first-pass test success for template-based goals.
  - Reduced noisy edits and lower touched-file count per successful run.

### M3: Memory and Learning Effectiveness (Target: May 2026)

- Improve lesson retrieval ranking using structured tags and optional local embeddings.
- Separate short-lived session hints from durable long-term lessons.
- Add confidence decay/reinforcement for lessons based on outcomes.
- Add "memory influence" telemetry to show which lessons affected planning.
- Exit criteria:
  - Fewer repeated failure signatures across similar goals.
  - Clear evidence of lesson reuse in planner/coder rationale.
  - Stable memory growth without low-signal accumulation.

### M4: Human Governance and Operational Scale (Target: June 2026)

- Add task queue with per-goal priority and cancellation controls.
- Add approval policy presets (strict, balanced, fast).
- Add richer trace IDs and per-iteration state snapshots for post-mortems.
- Add run health scorecards in dashboard and exported bundles.
- Exit criteria:
  - Multiple queued goals can run without cross-project contamination.
  - Approval/audit trails are complete and exportable.
  - Post-run diagnostics are fast enough for routine triage.

## Priority Backlog (Next 6 Items)

1. Harden preflight checks and failure messaging.
2. Implement diff-based patch application path.
3. Add plan-quality scoring and store score in run metadata.
4. Expand bundle viewer regression tests for `files/timeline/audit/replay/compare`.
5. Add lesson ranking signals from run outcomes.
6. Add queue runner with bounded concurrency.

## Success Metrics

- `pass_rate`: percentage of goal runs ending in success.
- `iterations_until_green`: median iterations before all tests pass.
- `time_to_success_sec`: median run duration to success.
- `retry_count`: average retries per run.
- `memory_reuse_rate`: fraction of successful runs citing prior lessons.
- `approval_latency_sec`: median time from approval request to decision.

## Operating Cadence

- Weekly: review failed runs, top error categories, and regression trends.
- Biweekly: ship one reliability change and one quality change.
- Monthly: prune low-signal memory entries and refresh roadmap priorities.
