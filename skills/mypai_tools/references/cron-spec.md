# MyPAI Cron Task Scheduler Usage Specification (`cron-spec.md`)

## Executive Summary

The **Cron Task Scheduler** subsystem in `mypai_daemon` manages background execution for **MyPAI**. Tasks are stored per workspace in SQLite databases located at `mypai_plugin_data/daemon/agent-<basedir>-<shorthash>.db` (with WAL mode and 30s busy timeout enabled).

---

## 1. Cron Schedule Expressions & One-Shot Triggers

1. **Standard 5-Field Unix Crontabs**:
   - Syntax: `"minute hour dom month dow"` (e.g. `"0 3 * * *"` for 3 AM daily).
   - **APScheduler Version Normalization**: On APScheduler < 4.0, day-of-week `0` (Sunday) is automatically remapped to `6` so standard cron syntax (`0 = Sunday`) is always honored.

2. **One-Shot Execution (`cron="now"`)**:
   - When `cron` is `"now"`, `@now`, or `@once`, `mypai_daemon` uses APScheduler's `DateTrigger(run_date=now)` with `misfire_grace_time=3600`.
   - Upon execution completion, `mypai_daemon` records telemetry stats and sets `enabled=False` in SQLite so the task retains execution history without repeating.

---

## 2. Supported Job Engines (`kind`)

* **`omp`**: Executes RPC actions into `omp` (`prompt`, `steer`, `followup`).
* **`http`**: Executes async HTTP requests (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`) via `httpx.AsyncClient`.
* **`shell`**: Executes CLI binary or script processes. `args` passed as positional list, `kwargs` as CLI flags.
* **`python`**: Executes in-process Python lambda expressions or code snippets.

---

## 3. Macro Variable Substitutions & Telemetry Macros

### 3.1 Environment & Field Variable Substitution Spec

All job fields support recursive macro variable expansion of both `#{VARNAME}` and `#[VARNAME]` syntax. Substitution occurs:
- **Pre-execution**: Environment and process variables (`#[HINDSIGHT_API_URL]`, `#[HINDSIGHT_BANK_ID]`, `#[HOME]`) expand across all job configuration fields.
- **Post-execution**: Execution telemetry macros (`#[_OUTPUT]`, `#[_RETURN_CODE]`, `#[_HTTP_CODE]`) expand inside `result_prompt` and `result_error_prompt`.

#### Field Variable Substitution Target Matrix

| Job Field | Data Type | Expansion Timing | Target Description & Usage Examples |
| :--- | :--- | :--- | :--- |
| **`url`** | `str` | Pre-Execution | API endpoint URLs (e.g. `#[HINDSIGHT_API_URL]/v1/default/banks/#[HINDSIGHT_BANK_ID]/reflect`). |
| **`action`** | `str` | Pre-Execution | Execution verb or executable path (e.g. `POST`, `#[CUSTOM_SCRIPT_PATH]`, `prompt`). |
| **`name`** | `str` | Pre-Execution | Task display name (e.g. `Reflection Sweep #[HINDSIGHT_BANK_ID]`). |
| **`description`** | `str` | Pre-Execution | Human-readable task description. |
| **`args`** | `list` / `dict` / `str` | Pre-Execution (Recursive) | Positional argument lists (e.g. `["--bank", "#[HINDSIGHT_BANK_ID]"]`). |
| **`kwargs`** | `dict` / `list` / `str` | Pre-Execution (Recursive) | Keyword argument dictionary, including nested headers (`{"Authorization": "Bearer #[API_TOKEN]"}`), request body payloads, and prompt kwargs. |
| **`result_prompt`** | `str` | Post-Execution | Success prompt template evaluated when `return_code == 0` (e.g. `Reflect on #[HINDSIGHT_BANK_ID]: #[_OUTPUT]`). |
| **`result_error_prompt`** | `str` | Post-Execution | Failure prompt template evaluated when `return_code != 0` (e.g. `Error #[_RETURN_CODE] on #[HINDSIGHT_BANK_ID]: #[_ERROR]`). |
| **`result_channel`** | `str` | Pre / Post-Execution | Delivery target channel (e.g. `#[DEFAULT_CHANNEL]` or `signal`). |

### 3.2 Rationale & Architectural Arguments for Variable Substitution Extension

1. **Environment Portability & Zero Hardcoding**:
   - Configuration templates (such as `default_jobs.json`) can be committed to repository control without embedding host-specific URLs, API keys, or project-specific memory bank IDs.
   - Placeholder substitution for `#[HINDSIGHT_API_URL]` and `#[HINDSIGHT_BANK_ID]` allows the exact same task definition to run unchanged across local, staging, and production environments.

2. **Recursive Traversal across Data Structures**:
   - HTTP request headers (`kwargs.headers`), payload bodies (`kwargs.query`), and CLI flag dicts (`kwargs`) are nested data structures.
   - Applying `substitute_vars` recursively ensures that placeholders embedded inside nested structures (e.g. `kwargs["headers"]["Authorization"]` or `kwargs["reason"]`) expand seamlessly.

3. **Dual Syntax Support (`#{VAR}` and `#[VAR]`)**:
   - Supporting both `#{VAR}` and `#[VAR]` prevents syntax collision with shell string expansion, JSON templates, and YAML files.

4. **Bridging Execution Output with Agent Context**:
   - Post-execution telemetry macros (`#[_OUTPUT]`, `#[_RETURN_CODE]`, `#[_HTTP_CODE]`, `#[_OBJECT]`) convert raw process stdout and HTTP responses into structured prompt context for subsequent LLM turns.

### 3.3 Standardized Internal Execution Telemetry Macros
The following `_`-prefixed variables are populated after job execution and can be used inside `result_prompt` and `result_error_prompt`:

| Macro Variable | Description | Delivered Content |
| :--- | :--- | :--- |
| **`#[_RETURN_CODE]`** | Status / Exit code | Process exit status, `0` for 2xx HTTP / Python / OMP success, non-zero for errors |
| **`#[_OUTPUT]`** | Primary output | Shell stdout, HTTP response body text, Python return string, OMP assistant text |
| **`#[_ERROR]`** | Primary error details | Shell stderr, HTTP error details, Python exception traceback, OMP error trace |
| **`#[_OBJECT]`** | Serialized return object | JSON string representation of `object` (`json.dumps(res["object"])`) |
| **`#[_HTTP_CODE]`** | HTTP status code | HTTP response status (e.g. `200`, `404`, `500`); default `0` for non-HTTP |
| **`#[_DURATION]`** | Execution runtime | Measured runtime in seconds (e.g. `0.234`) |
| **`#[_JOB_ID]`** | Task identifier | Database cron job ID |
| **`#[_JOB_NAME]`** | Human-readable name | Registered cron task name |

---

## 4. Result Actions & Result Channels

* **`result_prompt`**: Template evaluated when `return_code == 0`.
* **`result_error_prompt`**: Template evaluated when `return_code != 0` (falls back to `result_prompt` if empty).
* **`result_action`**: Action triggered upon completion:
  - `"ignore"`: Record telemetry in DB only (default).
  - `"prompt"`: Queue result prompt into OMP session.
  - `"steer"`: Inject high-priority interrupt turn.
  - `"followup"`: Append turn followup.
  - `"abort_and_prompt"`: Abort current turn and prompt result.
* **`result_channel`**: Target delivery channel (`""` for default OMP session, or `"signal"` for Signal messaging).

---

## 5. Job Types

#### `omp` Job (OMP RPC Engine)
- **Input Parameters Used**:
  - `action`: RPC verb (`'prompt'`, `'prompt_and_wait'`, `'steer'`, `'followup'`, `'abort_and_prompt'`, `'switch_session'`, `'branch'`).
  - `args`: Optional positional argument list (e.g. session path for `switch_session`).
  - `kwargs`: Optional dictionary containing `{"prompt": "..."}` or custom RPC kwargs.
  - `result_prompt` / `result_error_prompt`: Templated prompt context.
- **Return Fields**: `status`, `kind`, `action`, `return_code`, `output` (assistant text or RPC payload string), `error`, `object`, `duration_sec`.

#### `http` Job (Generic HTTP Request Engine)
- **Input Parameters Used**:
  - `action`: HTTP method verb (`'GET'`, `'POST'`, `'PUT'`, `'DELETE'`, `'PATCH'`).
  - `args`: Target API endpoint URL string or `["https://endpoint.com/api", optional_body_payload]`.
  - `kwargs`: Dictionary containing optional request parameters and optional `headers` dictionary (`{"headers": {"Authorization": "..."}}`).
- **Return Fields**: `status`, `kind`, `action`, `return_code` (`0` on 2xx/3xx; HTTP status code on 4xx/5xx/network error), `output` (response body string), `error` (HTTP error message), `object` (parsed JSON response or string), `duration_sec`.

#### `shell` Job (CLI Process Executor)
- **Input Parameters Used**:
  - `action`: Base CLI binary or script executable (e.g. `'python3'`, `'ls'`, `'echo'`).
  - `args`: Positional arguments list (e.g. `["-la", "/home"]`).
  - `kwargs`: Dictionary of flag parameters (e.g. `{"verbose": True, "output": "file.txt"}`).
- **Return Fields**: `status`, `kind`, `action` (full quoted CLI string), `return_code` (process exit status), `output` (captured `stdout`), `error` (captured `stderr`), `object` (`{"exit_code": N, "command": "..."}`), `duration_sec`.

#### `python` Job (In-Process Python Lambda & Async Code)
- **Input Parameters Used**:
  - `action`: Python lambda expression string (e.g. `'lambda args, kwargs: {"count": len(args)}'`) or multiline python script snippet.
  - `args`: Positional arguments list passed into lambda or namespace.
  - `kwargs`: Keyword arguments dictionary passed into lambda or namespace.
- **Return Fields**: `status`, `kind`, `action`, `return_code` (`0` for success, `1` for exception), `output` (stringified return value), `error` (exception traceback string), `object` (pristine unformatted return object), `duration_sec`.

## 6. SQLite Database Schema (`cron_jobs` table)

```sql
CREATE TABLE cron_jobs (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    cron VARCHAR(255) NOT NULL,
    kind VARCHAR(32) NOT NULL DEFAULT 'omp',
    action TEXT NOT NULL DEFAULT 'prompt',
    result_action VARCHAR(32) DEFAULT 'ignore',
    result_prompt TEXT DEFAULT '',
    result_error_prompt TEXT DEFAULT '',
    result_channel VARCHAR(64) DEFAULT '',
    enabled BOOLEAN DEFAULT 1,
    url TEXT DEFAULT '',
    args TEXT DEFAULT '',
    kwargs TEXT DEFAULT '',
    last_start VARCHAR(64),
    last_stop VARCHAR(64),
    last_runtime FLOAT DEFAULT 0.0,
    last_returncode INTEGER DEFAULT 0,
    last_output TEXT DEFAULT '',
    total_calls INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
```


---

## 7.  Autofix Cron Entry Example

```yaml

jobs:
  - name: Nightly Database Audit
    # Every night at 3:00 AM
    cron: "0 3 * * *"
    kind: shell
    action: python3
    args:
      - scripts/db_audit.py
    result:
      action: prompt
      # Routes prompt to OMP session ('prompt', 'steer', 'followup', 'abort_and_prompt')
      prompt: |
        Nightly Database Audit completed successfully
        ``log
        #[_OUTPUT]
        ```
      error_prompt: |
        CRON ERROR:: Cron Job '#[_JOB_NAME} failed!
        JOB_ID: #[_JOB_ID]
        RETURN_CODE: #[_RETURN_CODE]
        DURATION:  #[_DURATION]
        ERROR:
        ```log
        #[_ERROR]\n
        ```
        OUTPUT:
        ```log
        #[_OUTPUT]
        ```
        ACTIONS suggested: Disable this Please inspect the mypai_tools skill (skills/mypai_tools/SKILL.md)
        and spawn a @fixer agent to debug and fix this failure.

```


