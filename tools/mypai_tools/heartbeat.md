# Heartbeat & Cron Runner Architectural Specification (`heartbeat.md`)

## Executive Summary

The **Heartbeat Daemon** (`mypai_tools.heartbeat`) is the background cron execution and lifecycle engine for **MyPAI**. It maintains periodic triggers, executes 4 primary job types (`rpc`, `http`, `shell`, `python`), monitors process health via PID lockfiles, updates execution statistics in SQLite, and bridges external events directly into active or new **OMP** (oh-my-pi) sessions via the official `omp_rpc` Python SDK.

---

## 1. Primary Responsibilities & Functional Features

1. **Per-Project SQLite Database Sync**:
   - Manages cron job definitions stored in `$HOME/.omp/cron/projects/<project_hash>/cron.db`.
   - Uses `AsyncIOScheduler` to trigger jobs based on standard 5-field cron syntax (e.g. `0 8 * * 0`).
   - Dynamically syncs DB changes into memory every 10 seconds without requiring daemon restarts.

2. **APScheduler Version-Aware Crontab Normalization**:
   - **User Convention**: Always expect standard Unix crontab syntax where `0` = Sunday (or `7` = Sunday), `1` = Monday, ..., `6` = Saturday.
   - **APScheduler Version Resolution**: `apscheduler < 4.0` historically used `0` = Monday, whereas `apscheduler >= 4.0` fixed `0` = Sunday. The `normalize_cron_expression()` helper automatically detects the installed APScheduler version and transparently remaps day-of-week tokens (`0` -> `6`, `1` -> `0`, ..., `7` -> `6`) when running on `apscheduler < 4.0`.

3. **Distinctive `#[VARNAME]` Macro & Env Variable Substitution**:
   - Uses the unambiguous **`#[VARNAME]`** delimiter format for macro substitution across all string attributes (`url`, `action`, `args`, `kwargs`, `output_prompt`, `name`).
   - **Why `#[VARNAME]`?**: Never collides with JSON objects (`{"key": "val"}`), Python string format braces (`{}`), or shell variable syntax (`$VAR`/`${VAR}`).

4. **Standardized Internal Execution Variables**:
   - Automatically populates standardized `_`-prefixed internal execution telemetry variables for result formatting in `output_prompt`:
     - **`#[_RETURNCODE]`**: Process exit status code (0 for success, non-zero for error).
     - **`#[_STDOUT]`**: Captured standard output text stream.
     - **`#[_STDERR]`**: Captured standard error text stream.
     - **`#[_STDCOMBINED]`**: Combined STDOUT + STDERR stream output.
     - **`#[_RESULT]`** / **`#[_OUTPUT]`**: Executed return result value/string.

5. **Environment Variable Inheritance for Subprocesses**:
   - Subprocesses spawned by `shell` job types explicitly inherit the complete set of environment variables active in the `heartbeat` daemon process via `env=os.environ.copy()`.
   - Python in-process jobs natively access `os.environ` and `omp.env` exports (`PATH`, `VIRTUAL_ENV`, `PYTHONPATH`, etc.).

6. **SQLite WAL Mode & Concurrency Safety**:
   - Configures SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`) and `PRAGMA busy_timeout=30000;`.
   - Guarantees non-blocking concurrent writes between the MCP server (`cron_mcp`) and the Heartbeat background daemon.

7. **Unified 4-Type Job Execution Engine**:
   - **`rpc`**: Inter-process RPC triggering into `omp` via mandatory `omp_rpc.RpcClient`. `action` specifies RPC method (`prompt`, `steer`, `followup`, `abort_and_prompt`, `switch_session`, `branch`). Prompt text is supplied in `kwargs.prompt`.
   - **`http`**: Asynchronous HTTP client execution via `httpx.AsyncClient`. `action` specifies HTTP method verb (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`). URL in `url`, request body & headers in `kwargs`.
   - **`shell`**: Subprocess CLI execution. `action` specifies base binary/script executable (e.g. `python3`, `ls`, `echo`). Positional args in `args`, flags in `kwargs`.
   - **`python`**: In-process async Python execution. `action` specifies a Python **lambda expression** or code snippet to execute.

---

## 2. Unified Job Specification & Field Usage Matrix

### Universal Metadata Fields (Applies to All Job Types)

| Field | Type | Support | Macro Substitution? | Description |
| :--- | :--- | :--- | :---: | :--- |
| **`id`** | `str` | **Required** | No | Unique job identifier string (e.g. `"job_work_sweep"`). |
| **`name`** | `str` | **Required** | `#[VARNAME]` | Human-readable job name. |
| **`cron_expression`** | `str` | **Required** | No | Standard 5-field cron string (e.g. `"0 8 * * 0"` where `0` = Sunday). |
| **`type`** | `str` | **Required** | No | Primary engine selection: `"rpc"`, `"http"`, `"shell"`, or `"python"`. |
| **`action`** | `str` | **Required** | **`#[VARNAME]`** | Primary executable / verb for **ALL** job types (RPC verb, HTTP method, Shell binary, Python lambda/code). |
| **`enabled`** | `bool` | **Required** | No | Task schedule status (`true` / `false`). |
| **`target_channel`** | `str` | **Optional** | No | Notification output channel (defaults to `"signal"`). |
| **`output_prompt`** | `str` | **Optional** | **`#[VARNAME]`** | Output context template supporting `#[_STDOUT]`, `#[_STDERR]`, `#[_RETURNCODE]`, `#[_RESULT]`. |

---

### Detailed Field Usage & Macro Substitution Matrix

| Field Name | `rpc` | `http` | `shell` | `python` | Macro Substitution? | Exact Field Usage Explanation |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`action`** | **Req** | **Req** | **Req** | **Req** | **`#[VARNAME]`** | **RPC**: RPC verb (`prompt`, `steer`, `followup`, `abort_and_prompt`, `switch_session`, `branch`).<br>**HTTP**: HTTP method verb (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`).<br>**Shell**: Base CLI executable / binary string (e.g. `"python3"`, `"ls"`, `"echo"`).<br>**Python**: Python lambda expression (e.g. `"lambda args, kwargs: len(args) * 2"`). |
| **`url`** | N/A | **Req** | N/A | N/A | **`#[VARNAME]`** | **HTTP**: Target REST API endpoint URL (supports placeholders `#[HINDSIGHT_API_URL]`, `#[HINDSIGHT_BANK_ID]`, `#[OMP_RPC_URL]`). |
| **`args`** | Opt | Opt | Opt | Opt | **`#[VARNAME]`** | **RPC**: Positional argument list.<br>**HTTP**: Positional body payload.<br>**Shell**: Positional argument list (e.g. `["-m", "mypai_tools.input_spooler"]`).<br>**Python**: Positional arguments list passed to lambda/code. |
| **`kwargs`** | **Req** | Opt | Opt | Opt | **`#[VARNAME]`** | **RPC**: Keyword arguments dictionary containing `"prompt"` text string (`{"prompt": "Audit active tasks"}`).<br>**HTTP**: Request body JSON dictionary + optional merged `"headers"` dict.<br>**Shell**: CLI flag dictionary (e.g. `{"inbox": "#[HOME]/Inbox", "quiescence-sec": 10}`).<br>**Python**: Keyword arguments dictionary passed to lambda/code. |
| **`output_prompt`** | Opt | Opt | Opt | Opt | **`#[VARNAME]`** | Context template supporting `#[_STDOUT]`, `#[_STDERR]`, `#[_RETURNCODE]`, `#[_RESULT]` interpolation (e.g. `"Exit code #[_RETURNCODE]: #[_STDOUT]"`). |
| **`output_type`** | N/A | N/A | Opt | N/A | No | **Shell**: Stream capture mode: `"stdout"` (default), `"stderr"`, or `"combined"`. |
| **`output_action`** | N/A | N/A | Opt | N/A | No | **Shell**: Event routing back to OMP: `"ignore"` (default), `"prompt"`, `"steer"`, `"followup"`, or `"abort_and_prompt"`. |

---

## 3. Example Job Schema Configurations

### 1. `"rpc"` Job Type Example
```json
{
  "id": "job_work_sweep",
  "name": "Periodic Work Sweep Audit",
  "cron_expression": "*/30 * * * *",
  "type": "rpc",
  "action": "prompt",
  "kwargs": {
    "prompt": "Audit active project tasks in bank #[HINDSIGHT_BANK_ID]."
  },
  "enabled": true
}
```

### 2. `"http"` Job Type Example (`#[VARNAME]` Macro Substitution)
```json
{
  "id": "job_health_sync",
  "name": "Hindsight Reflection Sweep",
  "cron_expression": "0 */2 * * *",
  "type": "http",
  "action": "POST",
  "url": "#[HINDSIGHT_API_URL]/v1/default/banks/#[HINDSIGHT_BANK_ID]/reflect",
  "output_prompt": "Hindsight reflection result: #[_RESULT]",
  "kwargs": {
    "query": "Periodic health reflection sweep",
    "reason": "scheduled_health_sync",
    "headers": {
      "Content-Type": "application/json"
    }
  },
  "enabled": true
}
```

### 3. `"shell"` Job Type Example (Internal Telemetry `#[_RETURNCODE]`, `#[_STDOUT]`)
```json
{
  "id": "job_spooler_check",
  "name": "Inbox Spooler One-shot Check",
  "cron_expression": "0 * * * *",
  "type": "shell",
  "action": "python3",
  "args": ["-m", "mypai_tools.input_spooler"],
  "kwargs": {
    "inbox": "#[HOME]/Recordings/Inbox",
    "quiescence-sec": 10
  },
  "output_prompt": "Spooler process exited with code #[_RETURNCODE]. Output:\n#[_STDOUT]",
  "output_type": "stdout",
  "output_action": "ignore",
  "enabled": true
}
```

### 4. `"python"` Job Type Example (Lambda Expression & `#[_RESULT]`)
```json
{
  "id": "job_custom_calc",
  "name": "In-process Python Lambda Audit",
  "cron_expression": "0 12 * * *",
  "type": "python",
  "action": "lambda args, kwargs: {'status': 'ok', 'count': len(args)}",
  "args": ["task1", "task2"],
  "kwargs": {"env": "prod"},
  "output_prompt": "Python lambda evaluation result: #[_RESULT]",
  "enabled": true
}
```

---

## 4. CLI Command Usage

```bash
# Continuous background daemon mode
python3 -m mypai_tools.heartbeat daemon [--project-dir /path/to/project]

# Execute single-pass for all active jobs and exit
python3 -m mypai_tools.heartbeat once [--project-dir /path/to/project]

# Export all registered jobs to JSON file
python3 -m mypai_tools.heartbeat --export /tmp/jobs_backup.json

# Import jobs from JSON file into project SQLite database
python3 -m mypai_tools.heartbeat --import /tmp/jobs_backup.json
```
