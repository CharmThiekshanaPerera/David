# RUNNING.md — Running David in a New Environment

Last updated: 2026-11-14

This is the environment-agnostic version of the Quick Start in `README.md`, plus
every gotcha actually hit while standing David up and running a goal end-to-end.
Follow this when you move/clone the project to a new machine or a new path.

## 1. Prerequisites

- Python 3.11+ (project has been run under 3.10, 3.12, and 3.14; no version-specific
  code).
- [Ollama](https://ollama.com) installed and reachable at `127.0.0.1:11434` (David
  refuses non-localhost Ollama URLs by design — see `agent/safety.py` / `config.py`).
- At least one local model pulled, e.g.:
  ```
  ollama pull qwen2.5-coder:1.5b
  ```

## 2. Create the virtual environment

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

**Always activate the venv before running David** (`.\.venv\Scripts\activate`, or
source `.venv-win/Scripts/activate` in a POSIX-style shell on Windows). Do not just
invoke `.venv\Scripts\python.exe` by full path without activating first:
`agent/executor.py` resolves commands the Coder proposes (like `python -m pip
install ...`) via the inherited `PATH`, and if the venv's `Scripts` directory isn't
first on `PATH`, those commands can silently run against a *different* Python
installation than the one David itself is running under — producing confusing
"module not installed" failures even though the package is installed in the venv you
think you're using. (This was the root cause of a multi-hour debugging session on
2026-09-15 — verify with `python -c "import flask; print(flask.__file__)"` after
activating if anything looks inconsistent.)

## 3. Configure `.env`

```powershell
copy .env.example .env
```

Set `DAVID_MODEL` to a model you've actually pulled (`ollama list` to check). If you
want different models per role, also set `PLANNER_MODEL`, `CODER_MODEL`,
`CRITIC_MODEL`.

**Important**: if you've ever run the web Control Center, `data/control_settings.json`
has its own `planner_model` / `coder_model` / `critic_model` fields that **override**
`.env` for anything going through the web UI. Keep both in sync, or you'll fix
`.env` and still see the old model used. Check with:

```powershell
curl http://127.0.0.1:8787/api/status
```
(`coder_model_used` / `critic_model_used` in the response reflect what's actually
active.)

## 4. Verify Ollama

```powershell
ollama list
curl http://127.0.0.1:11434/api/tags
```

Confirm the model name in `.env` / `control_settings.json` exactly matches one of the
models listed — a mismatch produces a 500 from Ollama ("llama runner process has
terminated") on the first real request, not at startup.

## 5. Run it

CLI:
```powershell
python -m agent.main --self-diagnostics
python -m agent.main --goal "Create a Python TODO app with tests"
```

Web Control Center:
```powershell
python -m web.server
```
Then open `http://127.0.0.1:8787`.

## 6. Things that will bite you

- **One shared venv for everything.** A goal's `pip install package==X` installs
  into the *same* venv the main app uses. If the web UI or CLI breaks right after a
  goal run, suspect a dependency it changed:
  ```powershell
  pip install -r requirements.txt
  ```
- **Don't launch two `agent.main` or `web.server` processes against the same
  project/port.** They race on the same shared venv and workspace files. Check for
  stragglers before relaunching:
  ```powershell
  Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*agent.main*' }
  ```
- **A command that never exits always "fails."** `agent/executor.py` runs every
  command synchronously with a timeout (`DAVID_COMMAND_TIMEOUT_SEC`, default 45s).
  David's own Coder prompt now avoids proposing blocking commands (`app.run()`,
  `flask run`), but if you're writing goals by hand, don't ask it to "run the server
  and check it responds" as a verification step — ask for a pytest test using an
  in-process test client instead.
- **Small local models are an unreliable Critic.** If a run fails with a Critic
  `analysis` that contradicts the actual generated code, that's a known capability
  limit of small models doing self-review (see `AGENTS.md`), not necessarily a bug.
  Verify by hand (read the generated file, run it yourself) before assuming the code
  is actually broken.

## 7. Moving the project to a new path

If you move this folder to a new location (new drive, new parent directory):

1. **Do not move `.venv-win` / `.venv` with it and expect it to still work.**
   Virtualenv activation scripts (`Scripts/activate`, `activate.ps1`, `activate.bat`)
   bake in the absolute path they were created at. Delete the venv and recreate it
   fresh at the new location (step 2 above) — it's cheap.
2. Re-copy `.env` from `.env.example` if it doesn't already exist at the new
   location, or just keep the existing one — it has no path-sensitive values.
3. `data/control_settings.json`, `memory/long_term.json`, and `logs/telemetry.jsonl`
   have no absolute-path dependencies that break on move; they carry forward as-is.
4. Historical entries in `logs/telemetry.jsonl` and old run records under
   `workspace/projects/` reference the *old* absolute path in `project_path` fields.
   That's just historical log data — harmless, not something to fix retroactively.
5. After moving, sanity-check with `python -m agent.main --self-diagnostics` before
   running a real goal.
