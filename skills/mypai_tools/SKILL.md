---
name: mypai_tools
description: Guide for mypai_tools MCP services (cron, signal_chat, local-speech) and mypai_daemon background environment. Use when scheduling automated jobs, executing one-shot 'now' tasks, processing Signal messages, handling speech STT/TTS, or inspecting daemon session state.
---

# `mypai_tools` MCP Services & Daemon Environment

`mypai_tools` provides FastMCP tool servers, a background coordinator daemon (`mypai_daemon`), and speech processing engines for **MyPAI**.

---

## 1. Cron Task Scheduler (`cron`)

Per-project cron entries are stored in SQLite databases located at `mypai_plugin_data/daemon/agent-<basedir>-<shorthash>.db`. `cron_mcp` calls `mypai_daemon` REST API (`/api/v1/cron/jobs`) to avoid DB WAL locking.

### MCP Tools List (`mcp__cron_*`)
- **`add_job(name, cron, kind, action, url, args, kwargs, result_prompt, result_error_prompt, result_action, result_channel)`**: Register a recurring crontab task.
  - `cron`: Standard 5-field cron string (e.g. `'0 3 * * *'`) or `'now'` for immediate execution.
  - `kind`: Execution engine (`'omp'`, `'http'`, `'shell'`, `'python'`).
  - `action`: Execution verb (`'prompt'`, `'POST'`, binary name, or Python lambda).
- **`run_once(...)`**: Queue or reschedule an immediate one-shot task (`cron="now"`).
  - Uses APScheduler `DateTrigger`. Upon execution completion, updates telemetry stats and sets `enabled=False`.
- **`list_jobs(include_disabled=True)`**: List registered jobs with execution telemetry.
- **`disable_job(job_id)`** / **`enable_job(job_id)`**: Toggle job enabled state.
- **`modify_job(job_id, ...)`**: Update parameters of existing job.
- **`delete_job(job_id)`**: Delete job entry.
- **`import_jobs(file_path)`** / **`export_jobs(file_path)`**: JSON/YAML backup & restore.
- **`global_enable()`** / **`global_disable()`**: Toggle global daemon cron execution state.
- **`status()`**: Get status overview of scheduled cron jobs.

### Telemetry Macros & Result Actions
- **Input Substitution**: `#{VAR}` and `#[VAR]` expand environment variables.
- **Execution Telemetry Macros**: `#[_ACTION]`, `#[_ARGS]`, `#[_KWARGS]`, `#[_OPTS]`, `#[_RETURN_CODE]`, `#[_OUTPUT]`, `#[_ERROR]`, `#[_OBJECT]`, `#[_HTTP_CODE]`, `#[_DURATION]`, `#[_JOB_ID]`, `#[_JOB_NAME]` (strictly `_UPPERCASE` syntax).
- **Result Actions (`result_action`)**: `"ignore"` (default), `"prompt"`, `"steer"`, `"followup"`, `"abort_and_prompt"`.

---

## 2. Signal Messaging (`signal_chat`)

Integrates with local `signal-cli-rest-api` daemon via `mypai_tools.signal_client.SignalClient` SDK.

### MCP Tools List (`mcp__signal_chat_*`)
- **`read_message(sender=None)`**: Fetch the single oldest unread message (FIFO order).
  - Automatically dispatches **Read Receipt** (`POST /v1/receipts`) $\rightarrow$ shows **two white checkmarks** 🗸🗸.
  - Automatically dispatches **Typing Indicator** (`POST /v1/typing-indicator`) $\rightarrow$ shows **"Typing..."**.
  - Automatically saves incoming attachments to `$PROJECT_DIR/scratch/signal_attachments/` and returns local file paths in payload.
  - Returns `{"status": "empty"}` when queue is drained.
- **`send_message(recipient, message, attachments=None)`**: Dispatch outbound Signal message. Accepts local file paths in `attachments` list.
- **`list_chats()`**: List registered Signal contacts and group IDs.

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

## 6. References & Technical Guides

For detailed architectural specifications, REST API schemas, UI designs, and command guides, consult these reference documents:

- **[Daemon Core Architecture](references/daemon-spec.md)** (`mypai_tools.daemon`): Central coordinator, OMP RPC session manager, MPSC Event Queue turn serializer, & Signal entanglement.
- **[Daemon REST & WebSocket API](references/daemon-api-spec.md)** (`mypai_tools.daemon.api`): OpenAPI REST endpoints (`/api/v1/...`) supporting `prompt`, `steer`, `followup`, `abort_and_prompt`, & WebSocket stream (`/api/v1/ws`).
- **[ACP Intra-Agent Tool Specification](references/acp-tool-spec.md)** (`mypai_tools.acp`): ACP worker process pool, stdio JSON-RPC framing, 8 host tools (`acp_task`, etc.), REST state control (`/api/v1/acp/*`), & SQLite settings.
- **[Embedded Single-Page WebUI](references/web-ui-spec.md)** (`mypai_tools.webui`): Glassmorphism SPA served at `http://127.0.0.1:52080/` with live transcript stream & cron manager.
- **[Cron Scheduler Usage](references/cron-spec.md)** (`mypai_tools.scheduler`): Per-project SQLite task scheduler (`cron-<hash>.db`), `@now` triggers, job engines (`omp`, `http`, `shell`, `python`), & telemetry macros.
- **[Input Spooler Specification](references/input_spooler.md)** (`mypai_tools.input_spooler`): Inbox directory watcher, 10s quiescence gating, Whisper STT pipeline, Hindsight memory retention, & REST notifications.
- **[FastMCP Tool Servers Specification](references/mcp-spec.md)** (`cron_mcp`, `chat_mcp`, `speech_mcp`): FastMCP tool signatures & return schemas for `cron` (`mcp__cron_*`), `signal_chat` (`mcp__signal_chat_*`), and `local-speech`.
- **[Daemon CLI Command Usage](references/daemon-cli-usage.md)** (`mypai_tools.daemon.main`): Command line interface (`serve`, `once`, `import`, `export`) & environment flags (`--agent-dir`, `--port`).
- **[Daemon Test Architecture](references/daemon-testing.md)** (`src/tests/`): Hermetic test suite structure, fixtures (`FakeRpcClient`, `in_memory_db`), and test coverage matrix.

