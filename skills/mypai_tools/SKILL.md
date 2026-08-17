---
name: mypai_tools
description: Guide for mypai_tools host tools (cron), MCP services (signal_chat, local-speech), and mypai_daemon background environment. Use when scheduling automated jobs, executing one-shot 'now' tasks, processing Signal messages, handling speech STT/TTS, or inspecting daemon session state.
---

# `mypai_tools` Host Tools, MCP Services & Daemon Environment

`mypai_tools` provides native host tools, FastMCP tool servers, and a background coordinator daemon (`mypai_daemon`) for **MyPAI**.

---

## 1. Cron Task Scheduler (Native Host Tools)

Per-project cron entries are stored in SQLite databases located at `mypai_plugin_data/daemon/agent-<basedir>-<shorthash>.db`. Cron operations are registered as native in-process **Host Tools** in `omp_rpc`.

### Host Tools List
- **`add_job(name, cron, kind='omp', action='prompt', args=None, kwargs=None, opts=None, result=None, description='')`**: Register a recurring crontab task.
  - `cron`: Standard 5-field cron string (e.g. `'0 3 * * *'`) or `'now'` for immediate execution.
  - `kind`: Execution engine (`'omp'`, `'http'`, `'shell'`, `'python'`, `'acp'`).
  - `action`: Execution verb (`'prompt'`, `'POST'`, binary name, or Python lambda).
- **`run_once(...)`**: Queue or reschedule an immediate one-shot task (`cron="now"`).
  - Upon completion, updates telemetry stats and sets `enabled=False`.
- **`list_jobs(include_disabled=True)`**: List registered jobs with execution telemetry.
- **`disable_job(job_id)`** / **`enable_job(job_id)`**: Toggle job enabled state.
- **`update_job(job_id, ...)`**: Update parameters of existing job.
- **`delete_job(job_id)`**: Delete job entry.
- **`import_jobs(file_path)`** / **`export_jobs(file_path)`**: JSON/YAML backup & restore.
- **`global_enable()`** / **`global_disable()`**: Toggle global daemon cron execution state.
- **`status()`**: Get status overview of scheduled cron jobs.

### Telemetry Macros & Result Actions
- **Input Substitution**: `#{VAR}` and `#[VAR]` expand environment variables.
- **Execution Telemetry Macros**: `#[_ACTION]`, `#[_ARGS]`, `#[_KWARGS]`, `#[_OPTS]`, `#[_RETURN_CODE]`, `#[_OUTPUT]`, `#[_ERROR]`, `#[_OBJECT]`, `#[_HTTP_CODE]`, `#[_DURATION]`, `#[_JOB_ID]`, `#[_JOB_NAME]`.
- **Result Actions (`result.action`)**: `"log"` (default), `"prompt"`, `"steer"`, `"followup"`, `"abort_and_prompt"`.

---

## 2. Signal Messaging (`signal_chat` MCP Server)

Integrates with local `signal-cli-rest-api` daemon via `mypai_tools.signal_client.SignalClient` SDK.

### MCP Tools List (`mcp__signal_chat_*`)
- **`read_message(sender=None)`**: Fetch the single oldest unread message (FIFO order).
  - Automatically dispatches **Read Receipt** (`POST /v1/receipts`) $\rightarrow$ shows **two white checkmarks** 🗸🗸.
  - Automatically dispatches **Typing Indicator** (`POST /v1/typing-indicator`) $\rightarrow$ shows **"Typing..."**.
  - Automatically saves incoming attachments to `$PROJECT_DIR/scratch/signal_attachments/`.
- **`send_message(recipient, message, attachments=None)`**: Dispatch outbound Signal message. Accepts local file paths in `attachments` list.
- **`list_chats()`**: List registered Signal contacts and group IDs.

---

## 3. Speech & Audio Processing (`local-speech` MCP Server)

- **`transcribe_audio(audio_path, language=None)`**: Transcribe audio via local Whisper STT server (`http://localhost:50090/v1/audio/transcriptions`).
- **`synthesize_speech(text, voice=None)`**: Synthesize speech audio via local TTS server (`http://localhost:50095/v1/audio/speech`).

---

## 4. Input Spooler Sidecar (`input_spooler`)

Persistent asynchronous sidecar daemon (`python3 -m mypai_tools.input_spooler daemon`):
- **Inbox Gating & Hashing**: Watches `~/Recordings/Inbox` for voice/document drops with 10s quiescence gating and SHA256 deduplication.
- **STT & Memory Retention**: Transcribes audio via local Whisper STT (`:50090`) and retains facts in Hindsight memory (`:8888`).
- **Agent Notification**: Notifies `mypai_daemon` via `POST http://127.0.0.1:52080/api/v1/session/prompt`.

---

## 5. `mypai_daemon` Environment Overview

* **Host & Port**: `http://127.0.0.1:52080`
* **Session Persistence**: Maintains persistent `omp --mode rpc --auto-approve` session. Display title is set to `"mypai_daemon - running"`.
* **2-Tier Architecture**: Concurrent background executors (`http`, `python`, `shell`, `acp`) with `running_jobs` duplicate prevention + Serialized OMP RPC Turn Queue with priority-flush state machine.
* **Signal Whitelist Filter**: Receives webhooks on `POST /api/v1/signal/webhook`, drops unauthorized senders, and enqueues light notification turns for whitelisted messages.

---

## 6. References & Technical Guides

- **[Daemon Core Architecture](references/daemon-spec.md)** (`mypai_tools.daemon`): 2-Tier execution architecture, Turn Queue priority-flush resolver, and lifecycle management.
- **[Daemon REST & WebSocket API](references/daemon-api-spec.md)** (`mypai_tools.daemon.api`): OpenAPI REST endpoints (`/api/v1/...`) and WebSocket stream (`/api/v1/ws`).
- **[ACP Intra-Agent Tool Specification](references/acp-tool-spec.md)** (`mypai_tools.acp`): Async worker pool, host tools, and task store.
- **[Embedded WebUI](references/web-ui-spec.md)** (`mypai_tools.webui`): 3-tab SPA with streaming indicators and Gravity keyboard shortcuts.
- **[Cron Scheduler Usage](references/cron-spec.md)** (`mypai_tools.scheduler`): Pydantic job schema, concurrency registry, and telemetry macros.
- **[Input Spooler Specification](references/input_spooler.md)** (`mypai_tools.input_spooler`): Inbox directory watcher and STT pipeline.
- **[FastMCP Tool Servers Specification](references/mcp-spec.md)** (`chat_mcp`, `speech_mcp`): FastMCP tool signatures and schemas.
- **[Daemon CLI Command Usage](references/daemon-cli-usage.md)** (`mypai_tools.daemon.main`): Subcommand usage and flags.
- **[Daemon Test Architecture](references/daemon-testing.md)** (`src/tests/`): Test battery and fixtures.
