---
name: mypai-tools
description: Complete guide for using mypai_tools MCP services (cron-scheduler, chat-channel, local-speech) and background daemons (heartbeat, input_spooler, chat_bridge). Use when scheduling automated jobs, executing one-shot 'now' tasks, processing Signal messages, handling STT/TTS audio, or interacting with per-project cron entries.
---

# `mypai_tools` MCP Services & Background Daemons

`mypai_tools` provides a comprehensive suite of MCP tool servers, background daemons, and execution services.

---

## 1. Documentation Index & Location Matrix

| Component Type | Component Name | Implementation Module | Architectural Spec / File | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **MCP Server** | `cron-scheduler` | `mypai_tools.cron_mcp` | [mcp.json](../../mcp.json) | Cron schedule CRUD operations, `cron_run_once`, & job imports/exports |
| **MCP Server** | `chat-channel` | `mypai_tools.chat_mcp` | [mcp.json](../../mcp.json) | Signal messaging interface (`signal-cli-rest-api`) |
| **MCP Server** | `local-speech` | `mypai_tools.speech_mcp` | [mcp.json](../../mcp.json) | Local Speech-to-Text (Whisper) & Text-to-Speech synthesis |
| **Daemon** | `heartbeat` | `mypai_tools.heartbeat` | [heartbeat.md](../../tools/mypai_tools/heartbeat.md) | Cron runner and execution daemon, SQLite WAL manager |
| **Daemon** | `input_spooler` | `mypai_tools.input_spooler` | [input_spooler.md](../../tools/mypai_tools/input_spooler.md) | Inbox directory watcher, STT pipeline, & Hindsight retention |
| **Daemon** | `chat_bridge` | `mypai_tools.chat_bridge` | [chat_bridge.md](../../tools/mypai_tools/chat_bridge.md) | Signal chat event listener & OMP session steering bridge |

---

## 2. Task Scheduling & One-Shot Execution (`cron-scheduler`)

Per-project cron tasks are stored in SQLite databases located at `$HOME/.omp/cron/cron-<project_hash>.db`.

### `cron_add_job` Task Registration
- Use **`cron_add_job(name, cron, kind, action, args, kwargs, result_prompt, result_error_prompt, result_action, result_channel)`** to register a scheduled task in the project SQLite DB (`~/.omp/cron/cron-<project_hash>.db`).
- **`name`**: Human-readable task name (e.g. `'Nightly DB Audit'`).
- **`cron`**: Standard 5-field cron expression (e.g. `'0 3 * * *'`) or `'now'` for immediate execution.
- **`kind`**: Execution engine kind (`'omp'`, `'http'`, `'shell'`, `'python'`).
- **`action`**: Execution command/verb/code (e.g. `'prompt'`, `'POST'`, CLI binary name, or Python lambda).

### `cron_run_once` Immediate One-Shot Execution
- Use **`cron_run_once(name, kind, action, args, kwargs, ...)`** to queue a task for immediate execution (`cron="now"`).
- Uses APScheduler `DateTrigger(run_date=now)` with `misfire_grace_time=3600`.
- If an exact matching job `(name, kind, action, args, kwargs)` exists, it reschedules the job (`cron="now"`, `enabled=True`).
- Upon execution, `heartbeat` records telemetry and sets `enabled=False` so it retains history without repeating.

---

## 3. Standardized Cron Kind Reference & Parameter Specifications

All job executors return a **Standardized Result Object**:
```json
{
  "status": "success | error",
  "kind": "omp | http | shell | python",
  "action": "<string>",
  "return_code": 0,
  "output": "<primary captured output text>",
  "error": "<captured error text>",
  "object": <unformatted Python object / parsed JSON dict or list / None>,
  "duration_sec": 0.123
}
```

### 3.1 `omp` Job Kind (OMP RPC Engine)
- **Input Parameters Used**:
  - `action`: RPC verb (`'prompt'`, `'prompt_and_wait'`, `'steer'`, `'followup'`, `'abort_and_prompt'`, `'switch_session'`, `'branch'`).
  - `args`: Optional positional argument list (e.g. session path for `switch_session`).
  - `kwargs`: Optional dictionary containing `{"prompt": "..."}` or custom RPC kwargs.
  - `result_prompt` / `result_error_prompt`: Templated prompt context.
- **Return Fields**: `status`, `kind`, `action`, `return_code`, `output` (assistant text or RPC payload string), `error`, `object`, `duration_sec`.

### 3.2 `http` Job Kind (Generic HTTP Request Engine)
- **Input Parameters Used**:
  - `action`: HTTP method verb (`'GET'`, `'POST'`, `'PUT'`, `'DELETE'`, `'PATCH'`).
  - `args`: Target API endpoint URL string or `["https://endpoint.com/api", optional_body_payload]`.
  - `kwargs`: Dictionary containing optional request parameters and optional `headers` dictionary (`{"headers": {"Authorization": "..."}}`).
- **Return Fields**: `status`, `kind`, `action`, `return_code` (`0` on 2xx/3xx; HTTP status code on 4xx/5xx/network error), `output` (response body string), `error` (HTTP error message), `object` (parsed JSON response or string), `duration_sec`.

### 3.3 `shell` Job Kind (CLI Process Executor)
- **Input Parameters Used**:
  - `action`: Base CLI binary or script executable (e.g. `'python3'`, `'ls'`, `'echo'`).
  - `args`: Positional arguments list (e.g. `["-la", "/home"]`).
  - `kwargs`: Dictionary of flag parameters (e.g. `{"verbose": True, "output": "file.txt"}`).
- **Return Fields**: `status`, `kind`, `action` (full quoted CLI string), `return_code` (process exit status), `output` (captured `stdout`), `error` (captured `stderr`), `object` (`{"exit_code": N, "command": "..."}`), `duration_sec`.

### 3.4 `python` Job Kind (In-Process Python Lambda & Async Code)
- **Input Parameters Used**:
  - `action`: Python lambda expression string (e.g. `'lambda args, kwargs: {"count": len(args)}'`) or multiline python script snippet.
  - `args`: Positional arguments list passed into lambda or namespace.
  - `kwargs`: Keyword arguments dictionary passed into lambda or namespace.
- **Return Fields**: `status`, `kind`, `action`, `return_code` (`0` for success, `1` for exception), `output` (stringified return value), `error` (exception traceback string), `object` (pristine unformatted return object), `duration_sec`.

---

## 4. Distinctive `#{VAR}` / `#[VAR]` Macro Delimiters & Delivered `#[_` Internal Variables

- **Macro Syntax**: All string attributes (`action`, `args`, `kwargs`, `result_prompt`, `result_error_prompt`) substitute both `#{VARNAME}` and `#[VARNAME]` placeholders (e.g. `#{HINDSIGHT_API_URL}`, `#[HOME]`) before execution.

- **Delivered Internal Execution Variables**: `result_prompt` and `result_error_prompt` support standardized `_`-prefixed internal telemetry variables:

| Macro Variable | Description | Delivered Content |
| :--- | :--- | :--- |
| **`#[_RETURN_CODE]`** | Process / status return code | Shell exit status, `0` for 2xx HTTP / Python / OMP success, non-zero for errors |
| **`#[_OUTPUT]`** | Primary captured output stream | Shell stdout, HTTP response body text, Python return value string, OMP assistant text |
| **`#[_ERROR]`** | Primary captured error details | Shell stderr, HTTP error details, Python exception traceback, OMP error trace |
| **`#[_OBJECT]`** | Serialized return object | JSON string representation of `object` (`json.dumps(res["object"])`) |
| **`#[_HTTP_CODE]`** | HTTP status code | HTTP response status (e.g. `200`, `404`, `500`); default `0` for non-HTTP |
| **`#[_DURATION]`** | Execution runtime | Measured runtime in seconds (e.g. `0.234`) |
| **`#[_JOB_ID]`** | Task identifier | Database cron job ID |
| **`#[_JOB_NAME]`** | Human-readable name | Registered cron task name |

- **Result Prompts, Action & Channel**:
  - `result_prompt`: Template used on `return_code == 0`.
  - `result_error_prompt`: Template used on `return_code != 0` (falls back to `result_prompt` if empty).
  - `result_action`: `"ignore"` (default), `"prompt"`, `"steer"`, `"followup"`, `"abort_and_prompt"`.
  - `result_channel`: `""` / `None` (default no extra output), or `"signal"` for Signal messaging.

---

## 5. MCP Tools List
- `cron_add_job`: Add a recurring crontab task.
- `cron_run_once`: Queue/reschedule an immediate one-shot task (`cron="now"`).
- `cron_list_jobs`: List active and historical jobs with execution telemetry.
- `cron_disable_job` / `cron_enable_job`: Toggle job enabled state (`enabled: bool`).
- `cron_modify_job`: Update existing job properties.
- `cron_remove_job`: Delete job entry.
- `cron_import_jobs` / `cron_export_jobs`: JSON backup/restore.

---

## 6. Signal Messaging (`chat-channel`)

Interacts with local `signal-cli-rest-api` daemon to send and receive Signal messages.

---

## 7. Audio & Speech Processing (`local-speech`)

Processes audio transcription (`transcribe_audio`) via local Whisper (port 50090) and speech synthesis (`synthesize_speech`) via TTS server (port 50095).

---

## 8. References & Technical Guides

- [Autofix Cron Entries Guide](references/autofix-cron-entries.md): Detailed guide for configuring `result_error_prompt` to capture error telemetry and automatically delegate fixes to a `@fixer` subagent.
