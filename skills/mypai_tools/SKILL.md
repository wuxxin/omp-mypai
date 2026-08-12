---
name: mypai_tools
description: Guide for mypai_tools MCP services (cron-scheduler, chat-channel, local-speech) and mypai_daemon background environment. Use when scheduling automated jobs, executing one-shot 'now' tasks, processing Signal messages, handling speech STT/TTS, or inspecting daemon session state.
---

# `mypai_tools` MCP Services & Daemon Environment

`mypai_tools` provides FastMCP tool servers, a background coordinator daemon (`mypai_daemon`), and speech processing engines for **MyPAI**.

---

## Architecture & Location Index

| Component Type | Name | Module | Spec File / Reference | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Daemon** | `mypai_daemon` | `mypai_tools.daemon` | [daemon-spec.md](references/daemon-spec.md) | Central coordinator, OMP RPC session manager, Event Queue turn serializer |
| **REST/WS API** | `daemon API` | `mypai_tools.daemon.api` | [daemon-api-spec.md](references/daemon-api-spec.md) | REST endpoints (`/api/v1/...`) supporting `prompt`, `steer`, `followup`, `abort_and_prompt` & WS stream |
| **WebUI** | `Single-Page SPA` | `mypai_tools.webui` | [web-ui-spec.md](references/web-ui-spec.md) | Embedded glassmorphism dashboard served at `http://127.0.0.1:52080/` |
| **Scheduler** | `Cron Engine` | `mypai_tools.scheduler` | [scheduler-usage.md](references/scheduler-usage.md) | Per-project SQLite task scheduler (`cron-<hash>.db`) and macro engine |
| **Sidecar** | `input_spooler` | `mypai_tools.input_spooler` | [input_spooler.md](references/input_spooler.md) | Inbox directory watcher, STT pipeline, & Hindsight retention sidecar |
| **MCP Server** | `cron-scheduler` | `mypai_tools.cron_mcp` | [mcp.json](../../mcp.json) | Cron schedule CRUD operations & one-shot `cron_run_once` execution |
| **MCP Server** | `chat-channel` | `mypai_tools.chat_mcp` | [mcp.json](../../mcp.json) | Signal messaging tools using `mypai_tools.signal_client` SDK |
| **MCP Server** | `local-speech` | `mypai_tools.speech_mcp` | [mcp.json](../../mcp.json) | Local Speech-to-Text (Whisper :50090) & Text-to-Speech synthesis (:50095) |

---

## 1. Cron Task Scheduler (`cron-scheduler`)

Per-project cron entries are stored in SQLite databases located at `mypai_plugin_data/daemon/agent-<basedir>-<shorthash>.db`. `cron_mcp` calls `mypai_daemon` REST API (`/api/v1/cron/jobs`) to avoid DB WAL locking.

### MCP Tools List
- **`cron_add_job(name, cron, kind, action, url, args, kwargs, result_prompt, result_error_prompt, result_action, result_channel)`**: Register a recurring crontab task.
  - `cron`: Standard 5-field cron string (e.g. `'0 3 * * *'`) or `'now'` for immediate execution.
  - `kind`: Execution engine (`'omp'`, `'http'`, `'shell'`, `'python'`).
  - `action`: Execution verb (`'prompt'`, `'POST'`, binary name, or Python lambda).
- **`cron_run_once(...)`**: Queue or reschedule an immediate one-shot task (`cron="now"`).
  - Uses APScheduler `DateTrigger`. Upon execution completion, updates telemetry stats and sets `enabled=False`.
- **`cron_list_jobs(include_disabled=True)`**: List registered jobs with execution telemetry.
- **`cron_disable_job(job_id)`** / **`cron_enable_job(job_id)`**: Toggle job enabled state.
- **`cron_modify_job(job_id, ...)`**: Update parameters of existing job.
- **`cron_remove_job(job_id)`**: Delete job entry.
- **`cron_import_jobs(file_path)`** / **`cron_export_jobs(file_path)`**: JSON backup & restore.

### Telemetry Macros & Result Actions
- **Input Substitution**: `#{VAR}` and `#[VAR]` expand environment variables.
- **Execution Telemetry Macros**: `#[_RETURN_CODE]`, `#[_OUTPUT]`, `#[_ERROR]`, `#[_OBJECT]`, `#[_HTTP_CODE]`, `#[_DURATION]`, `#[_JOB_ID]`, `#[_JOB_NAME]`.
- **Result Actions (`result_action`)**: `"ignore"` (default), `"prompt"`, `"steer"`, `"followup"`, `"abort_and_prompt"`.

---

## 2. Signal Messaging (`chat-channel`)

Integrates with local `signal-cli-rest-api` daemon via `mypai_tools.signal_client.SignalClient` SDK.

### MCP Tools List
- **`get_next_unread_message(sender=None)`**: Fetch the single oldest unread message (FIFO order).
  - Automatically dispatches **Read Receipt** (`POST /v1/receipts`) $\rightarrow$ shows **two white checkmarks** 🗸🗸.
  - Automatically dispatches **Typing Indicator** (`POST /v1/typing-indicator`) $\rightarrow$ shows **"Typing..."**.
  - Automatically saves incoming attachments to `$PROJECT_DIR/scratch/signal_attachments/` and returns local file paths in payload.
  - Returns `{"status": "empty"}` when queue is drained.
- **`send_signal_message(recipient, message, attachments=None)`**: Dispatch outbound Signal message. Accepts local file paths in `attachments` list.
- **`list_signal_chats()`**: List registered Signal contacts and group IDs.

---

## 3. Speech & Audio Processing (`local-speech`)

- **`transcribe_audio(audio_path, language=None)`**: Transcribe audio via local Whisper STT server (`http://localhost:50090/v1/audio/transcriptions`).
- **`synthesize_speech(text, voice=None)`**: Synthesize speech audio via local TTS server (`http://localhost:50095/v1/audio/speech`).

---

## 4. Input Spooler Sidecar (`input_spooler`)

Persistent asynchronous sidecar daemon (`python3 -m mypai_tools.input_spooler daemon`) for automated inbox processing:
- **Inbox Gating & Hashing**: Watches `~/Recordings/Inbox` for voice/document drops. Implements 10s quiescence gating and SHA256 idempotency deduplication (`~/.omp/spooler/processed_hashes.json`).
- **STT & Memory Retention**: Parses `.md`/`.json` metadata sidecars, transcribes audio via local Whisper STT (`:50090`), and retains facts in Hindsight memory (`:8888`).
- **Agent Notification**: Notifies `mypai_daemon` via `POST http://127.0.0.1:52080/api/v1/session/prompt` (or `/steer`, `/followup`) upon completion.

---

## 5. `mypai_daemon` Environment Overview

* **Host & Port**: `http://127.0.0.1:52080`
* **Session Persistence & Title**: Maintains persistent `omp --mode rpc --auto-approve` session. Reattaches to existing session UUID saved in DB `project_settings` table or creates a new session. Display title is set to `"mypai_daemon - running"`. Automatically recovers from RPC crashes with `--continue`.
* **Queue Serializer**: Multi-Producer Single-Consumer (MPSC) queue serializing prompt turns from Signal webhooks, Input Spooler, Cron, and WebUI.
* **Signal Whitelist Entanglement**: Configured with `SIGNAL_ACCOUNT` and `SIGNAL_ALLOWED_SENDER`. Receives webhooks on `POST /api/v1/signal/webhook`, ignores unauthorized senders, and enqueues a light notification turn for whitelisted messages: `"NEW Signal message received from {sender}. Read with chat_mcp."`

---

## References & Technical Guides

For detailed specifications, API schemas, UI design, and implementation references, read these reference documents:

- [Daemon Core Architecture](references/daemon-spec.md): Process lifecycle, MPSC event queue, RPC session manager, Signal entanglement, & `SignalClient` SDK.
- [Daemon REST & WebSocket API](references/daemon-api-spec.md): OpenAPI endpoint schemas (`/api/v1/...`) supporting `prompt`, `steer`, `followup`, `abort_and_prompt`, & WebSocket stream (`/api/v1/ws`).
- [FastMCP Tool Servers Specification](references/mcp-spec.md): FastMCP tool signatures & return schemas for `chat-channel`, `cron-scheduler`, and `local-speech`.
- [Embedded Single-Page WebUI](references/web-ui-spec.md): Glassmorphism SPA design, live transcript stream, prompt/steer input box, & cron dashboard.
- [Cron Scheduler Usage](references/scheduler-usage.md): Cron expression syntax, `@now` triggers, job engines (`omp`, `http`, `shell`, `python`), telemetry macros, & SQLite schema.
- [Input Spooler Specification](references/input_spooler.md): Inbox directory watcher, STT transcription pipeline, Hindsight memory retention, & `mypai_daemon` REST notifications.
- [Daemon Test Architecture](references/daemon-testing.md): Hermetic test suite structure, fixtures (`FakeRpcClient`, `in_memory_db`), and test coverage matrix.
- [CLI Command Usage](references/cli-usage.md): Command line options (`--agent-dir`, `--port`, `--once`, `import`, `export`, `pytest`).
- [Autofix Cron Entries Guide](references/autofix-cron-entries.md): Guide for configuring `result_error_prompt` to delegate automated fixes to a `@fixer` subagent.
- [Legacy Heartbeat Specification](references/old-heartbeat.md): Historical spec for the former heartbeat daemon.
