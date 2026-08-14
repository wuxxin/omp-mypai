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
- **Pre-execution**: Environment and process variables eg. (`#[HINDSIGHT_API_URL]`, `#[HINDSIGHT_BANK_ID]`, `#[HOME]`) expand across all job configuration fields.
- **Post-execution**: Execution telemetry macros (`#[_OUTPUT]`, `#[_RETURN_CODE]`, `#[_HTTP_CODE]`) expand inside `result_prompt` and `result_error_prompt`.

#### Field Variable Substitution Targets

##### Pre-Execution Substitutions
Environment and process variables are expanded recursively across job fields before task execution:

- **`name`** (`str`): Task display name.
- **`description`** (`str`): Human-readable task description.
- **`action`** (`str`): Execution verb or executable path.
- **`args`** (`list` / `str`): Positional argument list or HTTP endpoint URL.
- **`kwargs`** (`dict` / `str`): Keyword argument dictionary for `omp`, `http`, or `python`. Not used for `kind: shell`.
- **`opts`** (`dict` / `str`): Dedicated options dictionary, including HTTP headers.
- **`result.action`** (`str`): Delivery action mode (`prompt`, `steer`, `followup`, `abort_and_prompt`, `ignore`).
- **`result.channel`** (`str`): Delivery target channel.

##### Post-Execution Substitutions
Execution telemetry macros (`#[_OUTPUT]`, `#[_RETURN_CODE]`, `#[_HTTP_CODE]`, `#[_ERROR]`, `#[_DURATION]`, `#[_JOB_ID]`, `#[_JOB_NAME]`, `#[_OBJECT]`) expanded inside result templates after task execution:

- **`result.prompt`** (`str`): Success prompt template evaluated when `return_code == 0` or HTTP status `< 400`. If empty `""`, success dispatch is skipped.
- **`result.error_prompt`** (`str`): Failure prompt template evaluated when `return_code != 0` or HTTP status `>= 400`.
- **`result.channel`** (`str`): Delivery target channel.

### 3.2 Variable Substitution Extension

1. **Environment Portability & Zero Hardcoding**:
   - Configuration templates (such as `example_jobs.yaml`) can be committed to repository control without embedding host-specific URLs, API keys, or project-specific memory bank IDs.
   - Placeholder substitution for `#[HINDSIGHT_API_URL]` and `#[HINDSIGHT_BANK_ID]` allows the exact same task definition to run unchanged across local, staging, and production environments.

2. **Recursive Traversal across Data Structures**:
   - HTTP request headers (`opts.headers`), payload bodies (`kwargs`), and positional argument lists (`args`) are nested data structures.
   - Applying `substitute_vars` recursively ensures that placeholders embedded inside nested structures (e.g. `opts["headers"]["Authorization"]` or `kwargs["reason"]`) expand seamlessly.

3. **Dual Syntax Support (`#{VAR}` and `#[VAR]`)**:
   - Supporting both `#{VAR}` and `#[VAR]` prevents syntax collision with shell string expansion, JSON templates, and YAML files.

4. **Bridging Execution Output with Agent Context**:
   - Post-execution telemetry macros (`#[_OUTPUT]`, `#[_RETURN_CODE]`, `#[_HTTP_CODE]`, `#[_OBJECT]`) convert raw process stdout and HTTP responses into structured prompt context for subsequent LLM turns.

### 3.3 Standardized Internal Execution Telemetry Macros
The following `_`-prefixed variables are populated after job execution and can be used inside `result_prompt` and `result_error_prompt`:

| Macro Variable | Description | Delivered Content |
| :--- | :--- | :--- |
| **`#[_ACTION]`** | Executed action string | Target CLI command, Python code/lambda, HTTP method, or RPC verb |
| **`#[_ARGS]`** | Positional arguments | Positional argument string or serialized JSON array |
| **`#[_KWARGS]`** | Keyword arguments | Serialized JSON dictionary of keyword parameters |
| **`#[_OPTS]`** | Options dictionary | Serialized JSON dictionary of execution options (headers, timeout, etc.) |
| **`#[_RETURN_CODE]`** | Status / Exit code | Process exit status, `0` for 2xx HTTP / Python / OMP success, non-zero for errors |
| **`#[_OUTPUT]`** | Primary output | Shell stdout, HTTP response body text, Python return string, OMP assistant text |
| **`#[_ERROR]`** | Primary error details | Shell stderr, HTTP error details, Python exception traceback, OMP error trace |
| **`#[_OBJECT]`** | Serialized return object | JSON string representation of `object` (`json.dumps(res["object"])`) |
| **`#[_HTTP_CODE]`** | HTTP status code | HTTP response status (e.g. `200`, `404`, `500`); default `0` for non-HTTP |
| **`#[_DURATION]`** | Execution runtime | Measured runtime in seconds (e.g. `0.234`) |
| **`#[_JOB_ID]`** | Task identifier | Database cron job ID |
| **`#[_JOB_NAME]`** | Human-readable name | Registered cron task name |

---

### 4. Result Actions, Result Prompts & Centralized Prompt Evaluator (`mypai_tools.tools.evaluate_and_dispatch_result_prompt`)

All job executors (`python`, `shell`, `http`, `omp`) route result prompt evaluation and delivery through `evaluate_and_dispatch_result_prompt`.

* **Nested `result:` Block**:
  In YAML/JSON configurations (such as `example_jobs.yaml`), result dispatch rules are structured as a nested `result` dictionary or flattened attributes (`result_prompt`, `result_error_prompt`, `result_action`):
  ```yaml
  result:
    action: prompt # 'ignore' | 'prompt' | 'steer' | 'followup' | 'abort_and_prompt'
    prompt: "" # Template for success (if empty "", do NOT trigger on success)
    error_prompt: "CRON ERROR: #[_ERROR]" # Template for error
    channel: "" # Target channel ("signal" or default "")
  ```
* **Empty `result.prompt: ""` Handling on Success**:
  - When execution succeeds (`return_code == 0` or HTTP status `< 400`), `result.prompt` (stripped of whitespace) is evaluated.
  - **If `result.prompt` is empty (`""` or whitespace-only)**: `mypai_daemon` does **NOT** trigger any action on success. Result dispatch is skipped entirely.
* **`result.error_prompt` Handling on Error**:
  - When execution fails (`return_code != 0`, HTTP status `>= 400`, or exception), `result.error_prompt` (stripped of whitespace) is evaluated.
  - If `result.error_prompt` is non-empty, macros are substituted and `result.action` is triggered.
* **`result_channel`**: Target delivery channel (`""` for default OMP session, or `"signal"` for Signal messaging).

---

## 5. Job Types & Options

#### `omp` Job (OMP RPC Engine)
- **Input Parameters Used**:
  - `action`: RPC verb (`'prompt'`, `'prompt_and_wait'`, `'steer'`, `'followup'`, `'abort_and_prompt'`, `'switch_session'`, `'branch'`).
  - `args`: Optional positional argument list (e.g. session path for `switch_session`).
  - `kwargs`: Keyword arguments dictionary containing `{"prompt": "..."}` prompt string.
  - `result`: Nested result block (`action`, `prompt`, `error_prompt`, `channel`).
- **Return Fields**: `status`, `kind`, `action`, `return_code`, `output` (assistant text or RPC payload string), `error`, `object`, `duration_sec`.

#### `http` Job (Generic HTTP Request Engine)
- **Input Parameters Used**:
  - `action`: HTTP method verb (`'GET'`, `'POST'`, `'PUT'`, `'DELETE'`, `'PATCH'`).
  - `args`: Target API endpoint URL string or `["https://endpoint.com/api", optional_body_payload]`.
  - `kwargs`: Dictionary containing optional request parameters and request body payload.
  - `opts`: Optional configuration options, eg. HTTP headers `opts: {headers: {"Content-Type": "application/json"}}`).
- **Return Fields**: `status`, `kind`, `action`, `return_code` (`0` on 2xx/3xx; HTTP status code on 4xx/5xx/network error), `output` (response body string), `error` (HTTP error message), `object` (parsed JSON response or string), `duration_sec`.

#### `shell` Job (CLI Process Executor)
- **Input Parameters Used**:
  - `action`: Base CLI binary or script executable (e.g. `'python3'`, `'ls'`, `'echo'`).
  - `args`: Positional arguments list or command arguments (e.g. `["scripts/db_audit.py", "--quick"]`).
  - `opts`: Optional configuration options.
- **Return Fields**: `status`, `kind`, `action` (full quoted CLI string), `return_code` (process exit status), `output` (captured `stdout`), `error` (captured `stderr`), `object` (`{"exit_code": N, "command": "..."}`), `duration_sec`.

#### `python` Job (In-Process Python Lambda & Async Code)
- **Input Parameters Used**:
  - `action`: Python lambda expression string (e.g. `'lambda args, kwargs: {"count": len(args)}'`) or multiline python script snippet.
  - `args`: Positional arguments list passed into lambda or namespace.
  - `kwargs`: Keyword arguments dictionary passed into lambda or namespace.
  - `opts`: Optional execution options.
- **Return Fields**: `status`, `kind`, `action`, `return_code` (`0` for success, `1` for exception), `output` (stringified return value), `error` (exception traceback string), `object` (pristine unformatted return object), `duration_sec`.

---

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
    args TEXT DEFAULT '',
    kwargs TEXT DEFAULT '',
    opts TEXT DEFAULT '',
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

## 7. Example Jobs Configuration (`config/example_jobs.yaml`)

```yaml
jobs:
  - name: Periodic Work Sweep Audit
    description: Audit active project tasks, verify pending commitments, and reflect on progress
    cron: "*/30 * * * *"
    enabled: true
    kind: omp
    action: prompt
    args: []
    kwargs:
      prompt: Audit active project tasks, verify pending commitments, and reflect on progress. Use 300 words.

  - name: Hindsight Reflection Sweep
    description: Trigger Hindsight memory reflection sweep across active project memory banks
    cron: "0 */2 * * *"
    enabled: true
    kind: http
    action: POST
    args:
      - "#[HINDSIGHT_API_URL]/v1/default/banks/#[HINDSIGHT_BANK_ID]/reflect"
    kwargs:
      query: Periodic health reflection sweep
      reason: scheduled_health_sync
    opts:
      headers:
        Content-Type: application/json
    result:
      action: prompt
      prompt: ""  # Don't trigger on success
      error_prompt: |-
        CRONJOB ERROR: Error triggering Hindsight reflection sweep across project #[HINDSIGHT_BANK_ID] memory bank.
        job_id: #{_JOB_ID}
        job_name: #{_JOB_NAME}
        http_code: #[_HTTP_CODE]
        error: #[_ERROR]

  - name: Nightly Database Backup & Audit
    description: Run automated database health audit and backup script
    cron: "0 3 * * *"
    enabled: true
    kind: shell
    action: python3
    args:
      - scripts/db_audit.py
      - --quick
    result:
      action: prompt
      prompt: |-
        Nightly Database Audit completed successfully for #[_JOB_NAME].
        Output:
        ```log
        #[_OUTPUT]
        ```
      error_prompt: |-
        CRON ERROR: Shell job '#[_JOB_NAME]' failed with return code #[_RETURN_CODE].
        Error details:
        ```log
        #[_ERROR]
        ```

  - name: System Resource Metric Calculation
    description: Compute memory usage and system uptime stats in-process
    cron: "0 * * * *"
    enabled: true
    kind: python
    action: "lambda args, kwargs: {'status': 'healthy', 'uptime_sec': kwargs.get('uptime', 3600)}"
    args: []
    kwargs:
      uptime: 86400
    result:
      action: ignore
      prompt: ""
      error_prompt: |-
        CRON ERROR: Python metric calculation failed for '#[_JOB_NAME]'.
        Error: #[_ERROR]
```


