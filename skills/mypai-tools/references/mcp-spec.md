# MyPAI FastMCP Tool Servers Specification (`mcp-spec.md`)

## Executive Summary

`mypai_tools` exposes three FastMCP tool servers that allow AI agents to schedule automated background tasks, send/receive Signal messages, and process speech STT/TTS. 

1. **`chat-channel`** (`mypai_tools.chat_mcp`): Signal messaging tools delegating to `mypai_tools.signal_client.SignalClient`.
2. **`cron-scheduler`** (`mypai_tools.cron_mcp`): Cron task management tools issuing REST requests to `mypai_daemon` (`/api/v1/cron/...`).
3. **`local-speech`** (`mypai_tools.speech_mcp`): Local Whisper STT (:50090) and TTS synthesis (:50095).

---

## 1. Signal Messaging MCP Server (`chat-channel`)

Interacts with `signal-cli-rest-api` via the shared `mypai_tools.signal_client.SignalClient` SDK.

### 1.1 `get_next_unread_message`
- **Signature**: `get_next_unread_message(sender: str | None = None) -> dict[str, Any]`
- **Behavior**:
  - Fetches the single **oldest unread message** (FIFO order).
  - Automatically dispatches **Read Receipt** (`POST /v1/receipts`) $\rightarrow$ shows **two white checkmarks** 🗸🗸 on sender's app.
  - Automatically dispatches **Typing Indicator** (`POST /v1/typing-indicator`) $\rightarrow$ shows **"Typing..."** on sender's app.
  - **Attachment Handling**: Extracts attachment files from `signal-cli-rest-api`, saves them to `$PROJECT_DIR/scratch/signal_attachments/`, and returns resolved local file paths.
- **Return Schema**:
  ```json
  {
    "status": "success",
    "sender": "+15559992222",
    "message": "Here is the architectural diagram and audio note",
    "timestamp": 1723420000000,
    "attachments": [
      {
        "filename": "diagram.png",
        "content_type": "image/png",
        "file_path": "/home/user/project/scratch/signal_attachments/1723420000_diagram.png",
        "size_bytes": 1048576
      }
    ],
    "remaining_unread_count": 0
  }
  ```
  *(Returns `{"status": "empty", "message": "No unread Signal messages."}` when queue is empty).*

### 1.2 `send_signal_message`
- **Signature**: `send_signal_message(recipient: str, message: str, attachments: list[str] | None = None) -> dict[str, Any]`
- **Behavior**: Dispatches outbound message via `POST /v2/send`. Accepts local file paths in `attachments` list.
- **Return Schema**: `{"status": "sent", "recipient": "+15559992222", "attachments_sent": 1}`

### 1.3 `list_signal_chats`
- **Signature**: `list_signal_chats() -> dict[str, Any]`
- **Behavior**: Queries registered Signal contacts and group IDs via `GET /v1/contacts`.

---

## 2. Cron Task Scheduler MCP Server (`cron-scheduler`)

All FastMCP tools in `cron_mcp.py` execute HTTP REST calls targeting `mypai_daemon` (`http://127.0.0.1:52080/api/v1/cron/...`) to avoid database WAL locks.

### Tools List & API Mapping

1. **`cron_add_job(name, cron, kind='omp', action='prompt', url='', args=None, kwargs=None, result_prompt='', result_error_prompt='', result_action='ignore', result_channel='')`**: Calls `POST /api/v1/cron/jobs`.
2. **`cron_run_once(...)`**: Calls `POST /api/v1/cron/jobs/run_once`. Queues/reschedules a one-shot job (`cron="now"`).
3. **`cron_list_jobs(include_disabled=True)`**: Calls `GET /api/v1/cron/jobs`.
4. **`cron_disable_job(job_id)`**: Calls `POST /api/v1/cron/jobs/{job_id}/disable`.
5. **`cron_enable_job(job_id)`**: Calls `POST /api/v1/cron/jobs/{job_id}/enable`.
6. **`cron_modify_job(job_id, ...)`**: Calls `PUT /api/v1/cron/jobs/{job_id}`.
7. **`cron_remove_job(job_id)`**: Calls `DELETE /api/v1/cron/jobs/{job_id}`.
8. **`cron_import_jobs(file_path)`**: Reads JSON file and calls `POST /api/v1/cron/import`.
9. **`cron_export_jobs(file_path)`**: Calls `GET /api/v1/cron/export` and writes JSON file.

---

## 3. Local Speech Processing MCP Server (`local-speech`)

- **`transcribe_audio(audio_path, language=None)`**: Transcribe audio via local Whisper STT server (`http://localhost:50090/v1/audio/transcriptions`).
- **`synthesize_speech(text, voice=None)`**: Synthesize speech audio via local TTS server (`http://localhost:50095/v1/audio/speech`).
