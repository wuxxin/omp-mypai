# `result_error_prompt` Usage & Autofix Cron Entries Guide

This document illustrates how to configure a cron entry with `result_error_prompt` so that whenever execution fails (`return_code != 0`), it automatically formats standard error, standard output, and exit code telemetry, references the `mypai_tools` skill, and requests OMP to delegate a fix to a `@fixer` agent.

---

## 1. FastMCP Tool Usage (`cron_add_job` / `cron_run_once`)

```python
from mypai_tools.cron_mcp import cron_add_job

cron_add_job(
    name="Nightly Database Audit",
    cron="0 3 * * *",  # Every night at 3:00 AM
    kind="shell",
    action="python3",
    args=["scripts/db_audit.py"],
    result_action="prompt",  # Routes prompt to OMP session ('prompt', 'steer', 'followup', 'abort_and_prompt')
    result_prompt="Nightly Database Audit completed successfully:\n```log\n#[_OUTPUT]\n```\n",
    result_error_prompt=(
        "ALERT: Cron entry 'Nightly Database Audit' failed!\n"
        "Return Code: #[_RETURN_CODE] (Duration: #[_DURATION]s)\n\n"
        "ERROR:\n```log\n#[_ERROR]\n```\n"
        "OUTPUT:\n```log\n#[_OUTPUT]\n```\n"
        "Please inspect the mypai_tools skill (skills/mypai_tools/SKILL.md) "
        "and spawn a @fixer agent to debug and fix this failure."
    ),
)
```

---

## 2. YAML Configuration Import (`jobs.yaml` / `cron_import_jobs`)

```yaml
jobs:
  - name: Sync External Metrics
    cron: "*/15 * * * *"
    kind: http
    action: POST
    url: "#[HINDSIGHT_API_URL]/v1/default/banks/#[HINDSIGHT_BANK_ID]/reflect"
    result_action: steer
    result_prompt: "Metrics synced successfully for bank #[HINDSIGHT_BANK_ID]:\n#[_OUTPUT]"
    result_error_prompt: |-
      Cron entry 'Sync External Metrics' failed with return code #[_RETURN_CODE] (HTTP #[_HTTP_CODE])!

      ERROR:
      ```log
      #[_ERROR]
      ```
      OUTPUT:
      ```log
      #[_OUTPUT]
      ```
      Please consult the mypai_tools skill instructions and spawn a @fixer agent to analyze and patch the error.
    enabled: true
```

---

## 3. Macro Telemetry Variable Cheat Sheet

When evaluated on execution completion, `result_error_prompt` expands the following standardized `_`-prefixed variables:

| Macro Variable | Description | Delivered Content |
| :--- | :--- | :--- |
| **`#[_RETURN_CODE]`** | Status / Exit code | Process exit status, `0` for 2xx HTTP / Python / OMP success, non-zero for errors |
| **`#[_OUTPUT]`** | Primary output stream | Shell stdout, HTTP response body text, Python return string, OMP assistant text |
| **`#[_ERROR]`** | Primary error stream | Shell stderr, HTTP error details, Python exception traceback, OMP error trace |
| **`#[_OBJECT]`** | Serialized return object | JSON string representation of `object` (`json.dumps(res["object"])`) |
| **`#[_HTTP_CODE]`** | HTTP status code | HTTP response status (e.g. `200`, `404`, `500`); `0` for non-HTTP |
| **`#[_DURATION]`** | Execution runtime | Measured execution runtime in seconds (e.g. `0.234`) |
| **`#[_JOB_ID]`** | Task identifier | Database cron job ID |
| **`#[_JOB_NAME]`** | Task name | Registered cron task name |
