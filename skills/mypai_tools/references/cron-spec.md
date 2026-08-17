# MyPAI Cron Task Scheduler Specification (`cron-spec.md`)

## Executive Summary

The **Cron Task Scheduler** subsystem in `mypai_daemon` manages scheduled and background execution for **MyPAI**. Tasks are stored per workspace in SQLite databases located at `mypai_plugin_data/daemon/agent-<basedir>-<shorthash>.db` (with WAL mode and 30s busy timeout enabled).

Cron capabilities are exposed directly to the persistent agent via **Host Tools** (`omp_rpc.host_tool`) without intermediate MCP subprocesses or HTTP loopback calls.

---

## 1. 2-Tier Architecture & Concurrency Model

1. **Background Execution Plane (Parallel & Non-Blocking)**:
   - Executors (`http`, `python`, `shell`, `acp`) run concurrently as background asyncio tasks.
   - Guarded by an active execution registry (`running_jobs: dict[str, asyncio.Task]`).
   - **Overlapping Cron Job Policy**: If a job ID is currently active in `running_jobs` when its next trigger fires, the duplicate run is **skipped and logged** in telemetry.
2. **Turn Queue Plane (Strictly Serialized for OMP RPC)**:
   - OMP RPC turns and executor completion results route through the prioritized **Turn Queue**.
   - If an executor completes with `result.action` (or `result.error_action`) other than `log` (`prompt`, `steer`, `followup`), it enqueues a turn item tagged with `is_result_call=True` and `origin_job_id=job_id`.
   - Result turns cannot trigger downstream cron jobs or recurse into event loops.
   - For `omp` kind cron jobs: `result.action` and `result.error_action` must be `log` (or ignored) to prevent infinite recursive self-prompting loops.

---

## 2. Pydantic Job Definition Schema

```python
from typing import Any, Literal
from pydantic import BaseModel, Field


class JobOpts(BaseModel):
    """Configuration options for job execution engines."""

    timeout_sec: int | None = None
    # Default timeouts by kind:
    # - "omp": 10s (fast async turn dispatch)
    # - "acp": 10s (fast async delegation dispatch)
    # - "shell": 120s (standard harness shell timeout)
    # - "python": 5s (fast in-process evaluation)
    # - "http": 30s (network IO request)

    timezone: str = "local"  # "local" (default) or "UTC"
    env: dict[str, str] = Field(default_factory=dict)  # Environment variables for shell kind
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP custom headers
    error_on: str | None = None  # Optional Python lambda string evaluating return code / error
    disable_on: str | None = None  # Optional Python lambda string to auto-disable job


class JobResult(BaseModel):
    """Result and error routing rules."""

    action: Literal["log", "prompt", "steer", "followup", "abort_and_prompt"] = "log"
    prompt: str = ""
    error_action: Literal["log", "prompt", "steer", "followup", "abort_and_prompt"] = "log"
    error_prompt: str = ""
    channel: str = ""


class CronJobSchema(BaseModel):
    """Canonical Cron Job Definition Schema."""

    id: str | None = None
    name: str
    description: str = ""
    cron: str  # 5-field cron expression or "now"
    enabled: bool = True
    kind: Literal["omp", "acp", "shell", "python", "http"] = "omp"
    action: str = "prompt"  # HTTP verb (any-case), shell binary, python code, or RPC verb
    args: list[Any] | str = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    opts: JobOpts = Field(default_factory=JobOpts)
    result: JobResult = Field(default_factory=JobResult)

    # Execution Telemetry (Read-Only / State Updates)
    total_runs: int = 0
    total_failures: int = 0
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_runtime: float = 0.0
    last_returncode: int = 0
    last_httpcode: int = 0
    last_output: str = ""
    last_error: str = ""
    created_at: str | None = None
    updated_at: str | None = None
```

---

## 3. SQLite Database Schema (`cron_jobs` table)

```sql
CREATE TABLE cron_jobs (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    cron VARCHAR(255) NOT NULL,
    kind VARCHAR(32) NOT NULL DEFAULT 'omp',
    action TEXT NOT NULL DEFAULT 'prompt',
    enabled BOOLEAN DEFAULT 1,
    args TEXT DEFAULT '',
    kwargs TEXT DEFAULT '',
    opts TEXT DEFAULT '',
    result TEXT DEFAULT '',
    total_runs INTEGER NOT NULL DEFAULT 0,
    total_failures INTEGER NOT NULL DEFAULT 0,
    next_run_at VARCHAR(64),
    last_run_at VARCHAR(64),
    last_runtime FLOAT DEFAULT 0.0,
    last_returncode INTEGER DEFAULT 0,
    last_httpcode INTEGER DEFAULT 0,
    last_output TEXT DEFAULT '',
    last_error TEXT DEFAULT '',
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
```

---

## 4. Native Host Tools (`host_tool`)

Registered directly into `omp_rpc.RpcClient` session:

- **`add_job(name, cron, kind='omp', action='prompt', args=None, kwargs=None, opts=None, result=None, description='')`**: Register a new recurring scheduled task.
- **`run_once(name, kind='omp', action='prompt', args=None, kwargs=None, opts=None, result=None)`**: Queue or execute an immediate one-shot task (`cron="now"`).
- **`list_jobs(include_disabled=True)`**: List registered jobs with execution telemetry.
- **`disable_job(job_id)`** / **`enable_job(job_id)`**: Toggle job enabled state.
- **`update_job(job_id, ...)`**: Update parameters of an existing job.
- **`delete_job(job_id)`**: Delete job entry.
- **`import_jobs(file_path)`** / **`export_jobs(file_path)`**: YAML/JSON backup & restore.
- **`global_enable()`** / **`global_disable()`**: Toggle global daemon cron execution state.
- **`status()`**: Get status overview of scheduled cron jobs.

---

## 5. Telemetry & Execution Macros

### 5.1 Environment Variable Expansion (`#{VAR}` / `#[VAR]`)
Pre-execution substitution recurses across all job fields, replacing `#{VAR}` and `#[VAR]` with environment variables (e.g. `#[HINDSIGHT_API_URL]`).

### 5.2 Post-Execution Internal Macros
Inside `result.prompt` and `result.error_prompt`, execution variables are interpolated:

| Macro Variable | Description | Value |
| :--- | :--- | :--- |
| **`#[_ACTION]`** | Action string | Target command, Python snippet, HTTP method, or RPC verb |
| **`#[_ARGS]`** | Positional arguments | Serialized JSON array or positional string |
| **`#[_KWARGS]`** | Keyword arguments | Serialized JSON dictionary of keyword parameters |
| **`#[_OPTS]`** | Options dictionary | Serialized JSON dictionary of execution options |
| **`#[_RETURN_CODE]`** | Process return code | Process exit status or `0` on success |
| **`#[_HTTP_CODE]`** | HTTP status code | HTTP response status (e.g. `200`, `404`, `500`) |
| **`#[_OUTPUT]`** | Process output | Process `stdout`, HTTP response body, or Python return string |
| **`#[_ERROR]`** | Process error | Process `stderr`, HTTP error details, or Python traceback |
| **`#[_OBJECT]`** | Serialized object | JSON representation of return object |
| **`#[_DURATION]`** | Execution runtime | Measured duration in seconds |
| **`#[_JOB_ID]`** | Job Identifier | Database cron job ID |
| **`#[_JOB_NAME]`** | Job Display Name | Registered job name |
