# Heartbeat & Cron Runner Architectural Specification (`heartbeat.md`)

## Executive Summary

The **Heartbeat Daemon** (`mypai_tools.heartbeat`) is the background cron execution and lifecycle engine for **MyPAI**. It maintains periodic triggers, executes 4 primary job types (`omp`, `http`, `shell`, `python`), monitors process health via PID lockfiles, updates execution statistics in SQLite, and bridges external events directly into active or new **OMP** (oh-my-pi) sessions via the official `omp_rpc` Python SDK.

---

## 1. Primary Responsibilities & Functional Features

1. **Per-Project SQLite Database Sync**:
   - Manages cron job definitions stored in `$HOME/.omp/cron/projects/<project_hash>/cron.db`.
   - SQLite DB session helper is `get_db_session(project_dir: str)`.
   - Requires `cron` field for each job (e.g., standard 5-field syntax `"0 8 * * 0"` or immediate one-shot `"now"` trigger keyword; `cron` has no default value).
   - Dynamically syncs DB changes into memory every 10 seconds without requiring daemon restarts.

2. **APScheduler Version-Aware Crontab Normalization & One-Shot DateTriggers**:
   - **Recurring Crontabs**: Standard Unix crontab syntax where `0` = Sunday (or `7` = Sunday), e.g. `0 8 * * 0` or `* * * * *`.
   - **One-Shot Jobs (`cron: "now"`)**: When `cron` is `"now"`, `@now`, or `@once`, `heartbeat` uses APScheduler's `DateTrigger(run_date=datetime.now(timezone.utc))` with `misfire_grace_time=3600`. Upon execution completion, `heartbeat` automatically updates telemetry stats and sets `enabled=False` in SQLite so the task retains its history without repeating automatically.

3. **Distinctive `#[VARNAME]` Macro & Env Variable Substitution**:
   - Uses the unambiguous **`#[VARNAME]`** delimiter format for macro substitution across all string attributes (`url`, `action`, `args`, `kwargs`, `result_prompt`, `result_error_prompt`, `name`).

4. **Standardized Internal Execution Variables**:
   - Automatically populates standardized `_`-prefixed internal execution telemetry variables for result formatting in `result_prompt` / `result_error_prompt`:
     - **`#[_RETURNCODE]`**: Process exit status code (0 for success, non-zero for error).
     - **`#[_STDOUT]`**: Captured standard output text stream.
     - **`#[_STDERR]`**: Captured standard error text stream.
     - **`#[_STDCOMBINED]`**: Combined STDOUT + STDERR stream output.
     - **`#[_RESULT]`**: Executed return result value/string.

5. **Result Action Processing (`result_action`), Prompts & Delivery Channels (`result_channel`)**:
   - **`result_prompt`**: Template used on `exitlevel == 0`.
   - **`result_error_prompt`**: Template used on `exitlevel != 0` (falls back to `result_prompt` if empty).
   - **`result_action`**: Action with formatted result prompt when evaluated (`"ignore"`, `"prompt"`, `"steer"`, `"followup"`, `"abort_and_prompt"`).
   - **`result_channel`**: Target delivery channel (`""` for default no extra output, or `"signal"` for Signal messaging).

   *Example Error Handling Configuration*:
   ```python
   cron_add_job(
       name="Nightly Database Audit",
       cron="0 3 * * *",
       kind="shell",
       action="python3",
       args=["scripts/db_audit.py"],
       result_action="prompt",
       result_prompt="Nightly Database Audit completed successfully:\n#[_STDOUT]",
       result_error_prompt=(
           "ALERT: Cron entry 'Nightly Database Audit' failed!\n"
           "Exit Code: #[_RETURNCODE]\n\n"
           "STDERR:\n#[_STDERR]\n\n"
           "STDOUT:\n#[_STDOUT]\n\n"
           "Please inspect the mypai-tools skill and spawn a @fixer agent to resolve the issue."
       ),
   )
   ```

6. **Unified 4-Type Job Execution Engine**:
   - **`omp`**: Inter-process RPC into `omp` via `omp_rpc.RpcClient`.
   - **`http`**: Asynchronous HTTP client execution via `httpx.AsyncClient`.
   - **`shell`**: Subprocess CLI execution. Positional args in `args`, flags in `kwargs`.
   - **`python`**: In-process async Python execution via lambda or code snippet.

---

## 2. FastMCP Tool `cron_run_once` & Rescheduling

The `cron-scheduler` FastMCP server exposes `cron_run_once(...)`:
- **Immediate One-Shot Execution**: Schedules a task with `cron="now"`.
- **Signature Deduplication & Rescheduling**: If a job with matching `(name, kind, action, args, kwargs)` exists, `cron_run_once` updates its `cron` to `"now"`, sets `enabled=True`, and reschedules it rather than creating a duplicate row.
- **Telemetry Update**: Upon execution, `heartbeat` increments `total_calls`, updates `last_start`, `last_stop`, `last_runtime`, `last_returncode`, `last_output`, and marks `enabled=False`.

---

## 3. CLI Command Usage

```bash
# Continuous background daemon mode
python3 -m mypai_tools.heartbeat daemon [--project-dir /path/to/project]

# Execute single-pass for all active jobs and exit
python3 -m mypai_tools.heartbeat once [--project-dir /path/to/project]

# Import cron jobs from specified JSON file path
python3 -m mypai_tools.heartbeat import /path/to/jobs.json [--project-dir /path/to/project]

# Export all registered jobs to specified JSON file path
python3 -m mypai_tools.heartbeat export /path/to/jobs_export.json [--project-dir /path/to/project]
```
