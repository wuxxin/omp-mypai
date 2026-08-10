# `result_error_prompt` Usage & Autofix Cron Entries Guide

This document illustrates how to configure a cron entry with `result_error_prompt` so that whenever execution fails (`exitlevel != 0`), it automatically formats standard error, standard output, and exit code telemetry, references the `mypai-tools` skill, and requests OMP to delegate a fix to a `@fixer` agent.

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
    result_prompt="Nightly Database Audit completed successfully:\n```log\n#[_STDOUT]\n```\n",
    result_error_prompt=(
        "ALERT: Cron entry 'Nightly Database Audit' failed!\n"
        "Exit Code (exitlevel): #[_RETURNCODE]\n\n"
        "STDERR:\n```log\n#[_STDERR]\n```\n"
        "STDOUT:\n```log\n#[_STDOUT]\n```\n"
        "Please inspect the mypai-tools skill (skills/mypai-tools/SKILL.md) "
        "and spawn a @fixer agent to debug and fix this failure."
    ),
)
```

---

## 2. JSON Configuration Import (`cron_import_jobs`)

```json
{
  "name": "Sync External Metrics",
  "cron": "*/15 * * * *",
  "kind": "shell",
  "action": "curl",
  "args": ["-f", "https://api.example.com/metrics/sync"],
  "result_action": "steer",
  "result_prompt": "Metrics synced successfully:\n#[_STDOUT]",
  "result_error_prompt": "Cron entry 'Sync External Metrics' failed with exitlevel #[_RETURNCODE]!\n\nSTDERR:\n```log\n#[_STDERR]\n```\nSTDOUT:\n```log\n#[_STDOUT]\n```\nPlease consult the mypai-tools skill instructions and spawn a @fixer agent to analyze and patch the error.\n",
  "enabled": true
}
```

---

## 3. Macro Telemetry Variable Cheat Sheet

When evaluated on execution completion, `result_error_prompt` expands the following standardized `_`-prefixed variables:

| Macro Variable | Description |
| :--- | :--- |
| **`#[_RETURNCODE]`** | Process exit code (`0` for success, non-zero for failure/error) |
| **`#[_STDERR]`** | Captured standard error text stream |
| **`#[_STDOUT]`** | Captured standard output text stream |
| **`#[_STDCOMBINED]`** | Combined `STDOUT` + `STDERR` output |
| **`#[_RESULT]`** | Python return result / JSON object |
