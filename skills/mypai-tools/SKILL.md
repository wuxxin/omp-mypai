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
| **MCP Server** | `cron-scheduler` | `mypai_tools.cron_mcp` | [mcp.json](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/mcp.json) | Cron schedule CRUD operations, `cron_run_once`, & job imports/exports |
| **MCP Server** | `chat-channel` | `mypai_tools.chat_mcp` | [mcp.json](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/mcp.json) | Signal messaging interface (`signal-cli-rest-api`) |
| **MCP Server** | `local-speech` | `mypai_tools.speech_mcp` | [mcp.json](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/mcp.json) | Local Speech-to-Text (Whisper) & Text-to-Speech synthesis |
| **Daemon** | `heartbeat` | `mypai_tools.heartbeat` | [heartbeat.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/tools/mypai_tools/heartbeat.md) | Cron runner daemon, SQLite WAL manager, & RPC poke engine |
| **Daemon** | `input_spooler` | `mypai_tools.input_spooler` | [input_spooler.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/tools/mypai_tools/input_spooler.md) | Inbox directory watcher, STT pipeline, & Hindsight retention |
| **Daemon** | `chat_bridge` | `mypai_tools.chat_bridge` | [chat_bridge.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/tools/mypai_tools/chat_bridge.md) | Signal chat event listener & OMP session steering bridge |

---

## 2. Task Scheduling & One-Shot Execution (`cron-scheduler`)

Per-project cron tasks are stored in SQLite databases located at `$HOME/.omp/cron/projects/<project_hash>/cron.db`.

### `cron_add_job` Task Registration
- Use **`cron_add_job(name, cron, kind, action, url, args, kwargs, result_prompt, result_error_prompt, result_action, result_channel)`** to register a scheduled task in the project SQLite DB (`~/.omp/cron/projects/<project_hash>/cron.db`).
- **`name`**: Human-readable task name (e.g. `'Nightly DB Audit'`).
- **`cron`**: Standard 5-field cron expression (e.g. `'0 3 * * *'`) or `'now'` for immediate execution.
- **`kind`**: Execution engine kind (`'omp'`, `'http'`, `'shell'`, `'python'`).
- **`action`**: Execution command/verb/code (e.g. `'prompt'`, `'POST'`, CLI string, or Python lambda).

### `cron_run_once` Immediate One-Shot Execution
- Use **`cron_run_once(name, kind, action, args, kwargs, ...)`** to queue a task for immediate execution (`cron="now"`).
- Uses APScheduler `DateTrigger(run_date=now)` with `misfire_grace_time=3600`.
- If an exact matching job `(name, kind, action, args, kwargs)` exists, it reschedules the job (`cron="now"`, `enabled=True`).
- Upon execution, `heartbeat` records telemetry and sets `enabled=False` so it retains history without repeating.

### Recurring Crontab Standard & Version Normalization
Always specify standard Unix crontab syntax where **`0` = Sunday** (or `7` = Sunday).
`mypai_tools` transparently detects whether `apscheduler < 4.0` or `apscheduler >= 4.0` is installed and normalizes the day-of-week field automatically so `0` always means Sunday.

### Distinctive `#[VARNAME]` Macro Delimiter & Standardized Internal Variables
- **`#[VARNAME]` Macro Syntax**: All string attributes (`action`, `url`, `args`, `kwargs`, `result_prompt`, `result_error_prompt`) substitute `#[VARNAME]` placeholders (e.g. `#[HINDSIGHT_API_URL]`, `#[HINDSIGHT_BANK_ID]`, `#[HOME]`) before execution.
- **Internal Execution Variables**: `result_prompt` and `result_error_prompt` support standardized `_`-prefixed internal telemetry variables:
  - `#[_RETURNCODE]`: Process exit status code
  - `#[_STDOUT]`: Standard output text
  - `#[_STDERR]`: Standard error text
  - `#[_STDCOMBINED]`: Combined stdout + stderr text
  - `#[_RESULT]`: Result object / string
- **Result Prompts, Action & Channel**:
  - `result_prompt`: Template used on `exitlevel == 0`.
  - `result_error_prompt`: Template used on `exitlevel != 0` (falls back to `result_prompt` if empty).
  - `result_action`: `"ignore"` (default), `"prompt"`, `"steer"`, `"followup"`, `"abort_and_prompt"`.
  - `result_channel`: `""` / `None` (default no extra output), or `"signal"` for Signal messaging.

### MCP Tools List
- `cron_add_job`: Add a recurring crontab task.
- `cron_run_once`: Queue/reschedule an immediate one-shot task (`cron="now"`).
- `cron_list_jobs`: List active and historical jobs with execution telemetry.
- `cron_disable_job` / `cron_enable_job`: Toggle job enabled state (`enabled: bool`).
- `cron_modify_job`: Update existing job properties.
- `cron_remove_job`: Delete job entry.
- `cron_import_jobs` / `cron_export_jobs`: JSON backup/restore.

---

## 3. Signal Messaging (`chat-channel`)

Interacts with local `signal-cli-rest-api` daemon to send and receive Signal messages.

---

## 4. Audio & Speech Processing (`local-speech`)

Processes audio transcription (`transcribe_audio`) via local Whisper (port 50090) and speech synthesis (`synthesize_speech`) via TTS server (port 50095).

---

## 5. References & Technical Guides

- [Autofix Cron Entries Guide](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/skills/mypai-tools/references/autofix-cron-entries.md): Detailed guide for configuring `result_error_prompt` to capture error telemetry and automatically delegate fixes to a `@fixer` subagent.

