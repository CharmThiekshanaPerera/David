# David Control Center Web UI

This document explains the local web interface for David, how to use each tab, and how to test it safely.

## 1. What It Is

`David Control Center` is a local-only web app that runs on the same machine as David and provides:

- run control (`/goal`, `/ask`, `/teach`) from browser,
- real-time status and progress,
- timeline + diff visibility for each run,
- approvals for risky actions,
- telemetry and logs for debugging.

It is designed to stay offline and safety-first.

## 2. Architecture

Main files:

- `web/server.py`: CLI entrypoint to start the web server.
- `web/app.py`: Flask routes and API endpoints.
- `web/control_center.py`: run manager, approvals, artifact storage, safety workflows.
- `web/safety.py`: helper validators for run IDs and workspace path safety.
- `web/static/index.html`: tabbed UI.
- `web/static/app.js`: frontend logic and polling.
- `web/static/styles.css`: styling.

Run artifacts:

- `data/runs/<run_id>/meta.json`
- `data/runs/<run_id>/plan.json`
- `data/runs/<run_id>/timeline.jsonl`
- `data/runs/<run_id>/iterations/<n>/coder.json`
- `data/runs/<run_id>/iterations/<n>/execution.json`
- `data/runs/<run_id>/iterations/<n>/critic.json`
- `data/runs/<run_id>/iterations/<n>/diffs.json`
- `data/runs/<run_id>/result.json`

## 3. Start the Web UI

From project root:

```bash
source .venv-linux/bin/activate
pip install -r requirements.txt
python -m web.server --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

If using Windows PowerShell:

```powershell
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m web.server --host 127.0.0.1 --port 8787
```

## 4. UI Walkthrough

## Dashboard

- Start Goal: runs `/goal ...`.
- Run preview: if enabled, generates diffs without writing files.
- Stop Active: requests graceful stop for current run.
- Status card: state, model, iteration, last command, safe mode.
- Pending Approvals: approve/reject risky edits or memory conflicts.
- Progress bar: based on iteration progress.

## Runs

- Search/filter run history.
- View run details and timeline events.
- Retry failed runs.
- Download run bundle (`.zip`) for a selected run.
- Explain Failure panel summarizes the first failing command/error.

## Diff Viewer

- Load a run ID and inspect per-iteration unified patches.
- Shows file-level added/removed line counts and patch text.

## Memory

- Facts list and lessons list from `memory/long_term.json`.
- Conflict detector warns if one subject/predicate has multiple values.

## Telemetry

- Summary: total iterations, success rate, error frequency, average duration.
- Duration chart: recent iteration durations.
- Regression detector warning count (tests fail after previously passing runs).

## Logs

- Tail view of:
  - `logs/web_control_center.log`
  - `logs/telemetry.jsonl`

## Settings

- `safe_mode`: read-only posture for risky operations.
- `rate_limit_seconds`: blocks spam `/goal` starts.
- `max_iterations_override`: overrides configured max iterations when > 0.
- `risky_large_edit_bytes`: threshold for approval gate.
- `risky_multi_file_threshold`: threshold for approval gate.
- `run_preview_default`: default preview behavior.

## CLI Mirror

- Sends commands like:
  - `/goal Create a TODO app`
  - `/ask Who is your father?`
  - `/teach My name is Charm Thiekshana.`

## 5. API Endpoints

- `GET /api/status`
- `POST /api/run`
- `POST /api/stop`
- `GET /api/runs`
- `GET /api/run/<run_id>`
- `POST /api/run/<run_id>/retry`
- `GET /api/run/<run_id>/bundle`
- `GET /api/memory`
- `GET /api/telemetry/tail`
- `GET /api/logs/tail`
- `GET /api/settings`
- `POST /api/settings`
- `GET /api/approvals`
- `POST /api/approval/<approval_id>`
- `GET /healthz`

## 6. Safety Model

- Local-only bind by default (`127.0.0.1`).
- No arbitrary shell execution endpoints.
- Supported command inputs are only `/goal`, `/ask`, `/teach`.
- File edits remain under `workspace/` via existing SafetyGuard rules.
- Risky edit operations require explicit approve/reject.
- Memory conflict writes from `/teach` require explicit approve/reject.
- User input is treated as untrusted data.

## 7. How To Test the Web UI

## A) Automated tests

Run web tests only:

```bash
pytest -q tests/test_web_api.py tests/test_web_safety.py
```

Run all project tests:

```bash
pytest -q
```

Coverage of web tests:

- API route behavior using Flask test client.
- invalid command rejection.
- run detail retrieval.
- memory endpoint response.
- safety helper validation for run ID + workspace path traversal.

## B) API smoke tests (manual)

Start server, then in another terminal:

```bash
curl -s http://127.0.0.1:8787/healthz
curl -s http://127.0.0.1:8787/api/status
curl -s -X POST http://127.0.0.1:8787/api/run -H 'Content-Type: application/json' -d '{"command":"/ask Who is your father?"}'
curl -s http://127.0.0.1:8787/api/runs
```

Expected:

- `healthz` returns `{"ok": true, "status": "up"}`.
- status endpoint returns `ok: true`.
- run endpoint accepts `/ask`, `/goal`, `/teach` and rejects others.

## C) Manual UI test checklist

1. Dashboard load:
   - page opens at `http://127.0.0.1:8787` with 8 tabs visible.
2. Start preview run:
   - run `/goal ...` with `Run preview` enabled.
   - verify run status becomes `preview_ready`.
   - verify diff visible in Diff Viewer.
3. Run real goal:
   - disable preview and start `/goal ...`.
   - verify progress bar and iteration updates.
   - check Runs timeline events update.
4. Approval gate:
   - in Settings, temporarily lower thresholds (example: `risky_multi_file_threshold=2`).
   - run a goal likely to touch multiple files.
   - verify Pending Approvals shows request.
   - verify Approve and Reject both work.
5. Memory conflict gate:
   - use CLI Mirror:
     - `/teach My name is Alice`
     - `/teach My name is Bob`
   - verify conflict/approval behavior and Memory conflict warnings.
6. Logs and telemetry:
   - verify Telemetry values update after runs.
   - verify Logs tab shows recent entries.
7. Retry and bundle:
   - select run in Runs tab.
   - click `Retry`, verify new run appears.
   - click `Bundle`, verify zip download.
8. Safe mode:
   - set `safe_mode=true` in Settings.
   - verify write attempts are blocked or require preview.

## 8. Troubleshooting

- `No module named flask`:
  - run `pip install -r requirements.txt`.
- UI loads but no updates:
  - check server terminal for tracebacks.
  - open `Logs` tab and inspect `web_control_center.log`.
- `Rate limit active` when starting runs:
  - lower `rate_limit_seconds` in Settings.
- `No active run` on stop:
  - expected when nothing is currently running.
- Ollama connection errors:
  - ensure `ollama serve` is running locally and model is available.
