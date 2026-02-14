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

## 7. How To Test the Web UI (Step-by-Step + Samples)

This section gives a full test flow that covers all tabs and safety controls.

## A) Pre-checks

1. Start Ollama:

```bash
ollama serve
```

2. Start web server:

```bash
python -m web.server --host 127.0.0.1 --port 8787
```

3. Open browser:

```text
http://127.0.0.1:8787
```

4. Open a second terminal for API tests.

## B) Automated tests

Run web tests only:

```bash
pytest -q tests/test_web_api.py tests/test_web_safety.py
```

Run full suite:

```bash
pytest -q
```

What this validates:

- API route behavior (status, run, run details, memory).
- rejection of invalid commands.
- workspace/path safety checks.

## C) API smoke tests with sample payloads

1. Health/status:

```bash
curl -s http://127.0.0.1:8787/healthz
curl -s http://127.0.0.1:8787/api/status
```

2. Ask run sample:

```bash
curl -s -X POST http://127.0.0.1:8787/api/run \
  -H 'Content-Type: application/json' \
  -d '{"command":"/ask Who is your father?"}'
```

3. Goal preview sample:

```bash
curl -s -X POST http://127.0.0.1:8787/api/run \
  -H 'Content-Type: application/json' \
  -d '{"command":"/goal Create hello.py and test_hello.py", "preview": true}'
```

4. Invalid command sample (must fail):

```bash
curl -s -X POST http://127.0.0.1:8787/api/run \
  -H 'Content-Type: application/json' \
  -d '{"command":"ls -la"}'
```

Expected:

- valid commands return `ok: true`.
- invalid command returns `ok: false`.

## D) Full UI test flow (all tabs)

1. Dashboard tab:
   - enter goal: `Create a simple calculator module with pytest tests`.
   - enable `Run preview`.
   - click `Start Goal`.
   - expected: status changes to `preview_ready` and progress reaches `100`.

2. Runs tab:
   - click `Refresh`.
   - expected: new run row appears with mode `goal`.
   - click `View` on the run.
   - expected: timeline shows `plan_created`, `coder_output`, and preview/result events.

3. Diff Viewer tab:
   - use the same run ID.
   - click `Load Diffs`.
   - expected: patch text appears for one or more files.

4. CLI Mirror tab:
   - send `/teach My name is Alice`.
   - send `/ask What is my name?`
   - expected: runs queue successfully and result output appears.

5. Memory tab:
   - expected: facts list includes the new taught fact.
   - conflict sample:
     - send `/teach My name is Bob`.
   - expected: conflict warning appears or approval request is created before overwrite.

6. Settings tab:
   - set:
     - `risky_multi_file_threshold = 2`
     - `risky_large_edit_bytes = 3000`
   - click `Save Settings`.
   - expected: success message and values persist on refresh.

7. Approval flow (Dashboard):
   - start a non-preview goal likely to touch multiple files:
     - `Create two files: app.py and test_app.py with passing pytest tests`.
   - expected: `Pending Approvals` shows a risky-edit request.
   - click `Reject` first, verify run becomes `rejected`.
   - run again and click `Approve`, verify run continues.

8. Telemetry tab:
   - expected: total iterations and chart values increase after each run.
   - expected: regression warning count remains `0` unless tests start failing after passing.

9. Logs tab:
   - click `Refresh logs`.
   - expected: entries visible for `web_control_center.log` and `telemetry.jsonl`.

10. Safe mode test:
   - in Settings set `safe_mode=true` and save.
   - from Dashboard start non-preview `/goal`.
   - expected: run blocked with read-only/safe mode error.
   - start preview goal with safe mode on.
   - expected: preview run allowed.

11. Retry + Bundle test (Runs):
   - pick a failed/rejected run.
   - click `Retry`, expected new run created.
   - click `Bundle`, expected zip download of run artifacts.

## E) Test sample commands for quick copy/paste

- `/goal Create hello.py and test_hello.py with one passing pytest test`
- `/goal Refactor hello.py and keep tests passing`
- `/ask Who is your father?`
- `/teach My favorite language is Python`
- `/teach My favorite language is Go` (conflict sample)

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
